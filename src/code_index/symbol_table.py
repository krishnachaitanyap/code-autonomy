"""
Symbol table: per-entity index of all Python classes, functions, and methods.

Enhanced AST walk that captures line ranges, docstrings, signatures, and
parent class context — building on consciousness AST extraction.
"""

import ast
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.constants import CODE_EXTENSIONS, SKIP_DIRS
from src.consciousness.core import (
    _ast_name,
    _ast_annotation_str,
    _ast_extract_params,
    _ast_decorator_name,
)


@dataclass
class SymbolEntry:
    """A single symbol (function, class, or method) in the codebase."""

    fqn: str  # "src/agent/analyzer.py::generate_changes_with_agent"
    file_path: str  # "src/agent/analyzer.py"
    name: str  # "generate_changes_with_agent"
    symbol_type: str  # "function" | "class" | "method" | "async function"
    line_start: int
    line_end: int
    signature: str  # Full signature string
    docstring_summary: str = ""  # First line of docstring (or "")
    parent_class: Optional[str] = None  # For methods: parent class FQN
    decorators: list[str] = field(default_factory=list)
    params: list[str] = field(default_factory=list)
    return_type: str = ""
    bases: list[str] = field(default_factory=list)  # For classes: base class names
    language: str = "python"  # "python" | "java"


class SymbolTable:
    """Index of all symbols, with lookup by FQN, name, and file."""

    def __init__(self) -> None:
        self._by_fqn: dict[str, SymbolEntry] = {}
        self._by_name: dict[str, list[SymbolEntry]] = {}
        self._by_file: dict[str, list[SymbolEntry]] = {}
        self._by_type: dict[str, list[SymbolEntry]] = {}

    def add(self, entry: SymbolEntry) -> None:
        self._by_fqn[entry.fqn] = entry
        self._by_name.setdefault(entry.name, []).append(entry)
        self._by_file.setdefault(entry.file_path, []).append(entry)
        self._by_type.setdefault(entry.symbol_type, []).append(entry)

    def get_by_fqn(self, fqn: str) -> Optional[SymbolEntry]:
        return self._by_fqn.get(fqn)

    def get_by_name(self, name: str) -> list[SymbolEntry]:
        return self._by_name.get(name, [])

    def get_by_file(self, path: str) -> list[SymbolEntry]:
        return self._by_file.get(path, [])

    def get_by_type(self, symbol_type: str) -> list[SymbolEntry]:
        """Return all entries of a given type (e.g. 'class', 'function')."""
        return self._by_type.get(symbol_type, [])

    @property
    def all_entries(self) -> list[SymbolEntry]:
        return list(self._by_fqn.values())

    @property
    def all_fqns(self):
        """Return dict keys view — O(1) ``in`` checks, no copy."""
        return self._by_fqn.keys()

    @property
    def all_files(self):
        """Return dict keys view — O(1) ``in`` checks, no copy."""
        return self._by_file.keys()

    def __len__(self) -> int:
        return len(self._by_fqn)

    def to_dict(self) -> list[dict]:
        """Serialize for JSON storage."""
        result = []
        for entry in self._by_fqn.values():
            d = {
                "fqn": entry.fqn,
                "file_path": entry.file_path,
                "name": entry.name,
                "symbol_type": entry.symbol_type,
                "line_start": entry.line_start,
                "line_end": entry.line_end,
                "signature": entry.signature,
                "docstring_summary": entry.docstring_summary,
                "parent_class": entry.parent_class,
                "decorators": entry.decorators,
                "params": entry.params,
                "return_type": entry.return_type,
                "bases": entry.bases,
            }
            if entry.language != "python":
                d["language"] = entry.language
            result.append(d)
        return result

    @classmethod
    def from_dict(cls, data: list[dict]) -> "SymbolTable":
        """Deserialize from JSON."""
        table = cls()
        for d in data:
            entry = SymbolEntry(
                fqn=d["fqn"],
                file_path=d["file_path"],
                name=d["name"],
                symbol_type=d["symbol_type"],
                line_start=d["line_start"],
                line_end=d["line_end"],
                signature=d["signature"],
                docstring_summary=d.get("docstring_summary", ""),
                parent_class=d.get("parent_class"),
                decorators=d.get("decorators", []),
                params=d.get("params", []),
                return_type=d.get("return_type", ""),
                bases=d.get("bases", []),
                language=d.get("language", "python"),
            )
            table.add(entry)
        return table


def _get_docstring_summary(node) -> str:
    """Extract first line of docstring from a class/function AST node."""
    doc = ast.get_docstring(node)
    if doc:
        first_line = doc.strip().split("\n")[0].strip()
        return first_line
    return ""


def _build_signature(name: str, params: list[str], return_type: str,
                     symbol_type: str, decorators: list[str],
                     bases: list[str]) -> str:
    """Build a human-readable signature string."""
    parts = []
    for d in decorators:
        parts.append(f"@{d}")
    if symbol_type == "class":
        base_str = f"({', '.join(bases)})" if bases else ""
        parts.append(f"class {name}{base_str}")
    elif symbol_type == "async function":
        ret = f" -> {return_type}" if return_type else ""
        parts.append(f"async def {name}({', '.join(params)}){ret}")
    else:
        ret = f" -> {return_type}" if return_type else ""
        parts.append(f"def {name}({', '.join(params)}){ret}")
    return "\n".join(parts)


def extract_symbols_from_source(
    rel_path: str, content: str, tree: "ast.Module | None" = None
) -> list[SymbolEntry]:
    """Extract all symbols from a Python source file using AST.

    Enhanced version of ``_extract_python_signatures_ast`` that captures
    line ranges, docstrings, and parent class context.

    Args:
        rel_path: Relative file path within the repo.
        content: Source code text.
        tree: Optional pre-parsed AST tree. If provided, ``ast.parse`` is skipped.
    """
    if tree is None:
        try:
            tree = ast.parse(content)
        except SyntaxError:
            return []

    entries: list[SymbolEntry] = []
    _method_locations: set[tuple[int, str]] = set()  # (line_start, name) of methods already added

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            bases = [_ast_name(b) for b in node.bases if _ast_name(b)]
            decorators = [_ast_decorator_name(d) for d in node.decorator_list
                          if _ast_decorator_name(d)]
            fqn = f"{rel_path}::{node.name}"
            sig = _build_signature(node.name, [], "", "class", decorators, bases)
            entry = SymbolEntry(
                fqn=fqn,
                file_path=rel_path,
                name=node.name,
                symbol_type="class",
                line_start=node.lineno,
                line_end=node.end_lineno or node.lineno,
                signature=sig,
                docstring_summary=_get_docstring_summary(node),
                decorators=decorators,
                bases=bases,
            )
            entries.append(entry)

            # Extract methods within the class
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    params = _ast_extract_params(child)
                    return_type = _ast_annotation_str(child.returns) if child.returns else ""
                    child_decorators = [_ast_decorator_name(d) for d in child.decorator_list
                                        if _ast_decorator_name(d)]
                    sym_type = "method"
                    method_fqn = f"{rel_path}::{node.name}.{child.name}"
                    method_sig = _build_signature(
                        child.name, params, return_type,
                        "async function" if isinstance(child, ast.AsyncFunctionDef) else "function",
                        child_decorators, [],
                    )
                    method_entry = SymbolEntry(
                        fqn=method_fqn,
                        file_path=rel_path,
                        name=child.name,
                        symbol_type=sym_type,
                        line_start=child.lineno,
                        line_end=child.end_lineno or child.lineno,
                        signature=method_sig,
                        docstring_summary=_get_docstring_summary(child),
                        parent_class=fqn,
                        decorators=child_decorators,
                        params=params,
                        return_type=return_type,
                    )
                    entries.append(method_entry)
                    _method_locations.add((child.lineno, child.name))

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Skip methods already processed inside ClassDef (O(1) lookup)
            if (node.lineno, node.name) in _method_locations:
                continue

            params = _ast_extract_params(node)
            return_type = _ast_annotation_str(node.returns) if node.returns else ""
            decorators = [_ast_decorator_name(d) for d in node.decorator_list
                          if _ast_decorator_name(d)]
            sym_type = "async function" if isinstance(node, ast.AsyncFunctionDef) else "function"
            fqn = f"{rel_path}::{node.name}"
            sig = _build_signature(node.name, params, return_type, sym_type, decorators, [])
            entry = SymbolEntry(
                fqn=fqn,
                file_path=rel_path,
                name=node.name,
                symbol_type=sym_type,
                line_start=node.lineno,
                line_end=node.end_lineno or node.lineno,
                signature=sig,
                docstring_summary=_get_docstring_summary(node),
                decorators=decorators,
                params=params,
                return_type=return_type,
            )
            entries.append(entry)

    return entries


def _estimate_java_end_line(content: str, start_line: int) -> int:
    """Estimate the closing brace line for a Java declaration using brace-matching.

    String/comment-aware: skips braces inside string literals and comments.
    """
    lines = content.splitlines()
    depth = 0
    in_string = False
    string_char = None
    in_line_comment = False
    in_block_comment = False

    for i in range(start_line - 1, len(lines)):
        line = lines[i]
        j = 0
        in_line_comment = False
        while j < len(line):
            ch = line[j]
            next_ch = line[j + 1] if j + 1 < len(line) else ""

            if in_block_comment:
                if ch == "*" and next_ch == "/":
                    in_block_comment = False
                    j += 2
                    continue
                j += 1
                continue

            if in_line_comment:
                j += 1
                continue

            if in_string:
                if ch == "\\" and j + 1 < len(line):
                    j += 2  # skip escaped char
                    continue
                if ch == string_char:
                    in_string = False
                j += 1
                continue

            if ch == "/" and next_ch == "/":
                in_line_comment = True
                j += 2
                continue
            if ch == "/" and next_ch == "*":
                in_block_comment = True
                j += 2
                continue
            if ch in ('"', "'"):
                in_string = True
                string_char = ch
                j += 1
                continue

            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return i + 1  # 1-based line number

            j += 1

    return min(start_line + 50, len(lines))


def _extract_javadoc_summary(content: str, start_line: int) -> str:
    """Scan backward from start_line to find a Javadoc comment and extract its first sentence."""
    lines = content.splitlines()
    idx = start_line - 2  # 0-based, line before declaration
    while idx >= 0 and lines[idx].strip() == "":
        idx -= 1
    if idx < 0:
        return ""

    # Check if we're at the end of a block comment
    end_line = idx
    if not lines[end_line].strip().endswith("*/"):
        return ""

    # Walk back to find the start of the comment
    while idx >= 0:
        stripped = lines[idx].strip()
        if stripped.startswith("/**") or stripped.startswith("/*"):
            break
        idx -= 1
    else:
        return ""

    if not lines[idx].strip().startswith("/**"):
        return ""

    # Extract text between /** and */
    doc_lines = []
    for i in range(idx, end_line + 1):
        line = lines[i].strip()
        line = line.lstrip("/").lstrip("*").strip()
        if line and not line.startswith("@"):
            doc_lines.append(line)

    text = " ".join(doc_lines)
    # First sentence
    for sep in (".", "\n"):
        pos = text.find(sep)
        if pos > 0:
            return text[: pos + 1].strip()
    return text.strip()[:120]


def _build_java_signature(
    name: str, modifiers: list, annotations: list,
    kind: str, extends: list | None = None,
    implements: list | None = None,
    params: list | None = None, return_type: str = "",
    type_params: list | None = None, throws: list | None = None,
) -> str:
    """Build a human-readable Java signature string."""
    parts = []
    for ann in (annotations or []):
        ann_name = ann.name if hasattr(ann, "name") else str(ann)
        parts.append(f"@{ann_name}")

    mod_str = " ".join(modifiers or [])

    if kind == "class":
        tp = ""
        if type_params:
            tp = "<" + ", ".join(str(tp) for tp in type_params) + ">"
        ext_str = ""
        if extends:
            ext_names = [e.name if hasattr(e, "name") else str(e) for e in extends]
            ext_str = " extends " + ", ".join(ext_names)
        impl_str = ""
        if implements:
            impl_names = [i.name if hasattr(i, "name") else str(i) for i in implements]
            impl_str = " implements " + ", ".join(impl_names)
        parts.append(f"{mod_str} class {name}{tp}{ext_str}{impl_str}".strip())
    elif kind == "interface":
        tp = ""
        if type_params:
            tp = "<" + ", ".join(str(tp) for tp in type_params) + ">"
        ext_str = ""
        if extends:
            ext_names = [e.name if hasattr(e, "name") else str(e) for e in extends]
            ext_str = " extends " + ", ".join(ext_names)
        parts.append(f"{mod_str} interface {name}{tp}{ext_str}".strip())
    elif kind == "enum":
        parts.append(f"{mod_str} enum {name}".strip())
    elif kind == "method":
        param_strs = []
        for p in (params or []):
            p_type = p.type.name if hasattr(p, "type") and hasattr(p.type, "name") else str(getattr(p, "type", ""))
            p_name = p.name if hasattr(p, "name") else str(p)
            param_strs.append(f"{p_type} {p_name}")
        ret = return_type or "void"
        throws_str = ""
        if throws:
            throws_str = " throws " + ", ".join(throws)
        parts.append(f"{mod_str} {ret} {name}({', '.join(param_strs)}){throws_str}".strip())
    elif kind == "constructor":
        param_strs = []
        for p in (params or []):
            p_type = p.type.name if hasattr(p, "type") and hasattr(p.type, "name") else str(getattr(p, "type", ""))
            p_name = p.name if hasattr(p, "name") else str(p)
            param_strs.append(f"{p_type} {p_name}")
        parts.append(f"{mod_str} {name}({', '.join(param_strs)})".strip())

    return "\n".join(parts)


def extract_java_symbols_from_source(
    rel_path: str, content: str, tree: object = None
) -> list[SymbolEntry]:
    """Extract all symbols from a Java source file using javalang AST.

    Args:
        rel_path: Relative file path within the repo.
        content: Source code text.
        tree: Optional pre-parsed javalang CompilationUnit.
    """
    try:
        import javalang
    except ImportError:
        return []

    if tree is None:
        try:
            tree = javalang.parse.parse(content)
        except Exception:
            return []

    entries: list[SymbolEntry] = []

    def _process_type_decl(decl, parent_fqn: str | None = None):
        """Process a class, interface, or enum declaration recursively."""
        if not hasattr(decl, "name") or not decl.name:
            return

        name = decl.name
        if parent_fqn:
            fqn = f"{parent_fqn}.{name}"
        else:
            fqn = f"{rel_path}::{name}"

        # Determine kind
        kind = "class"
        if isinstance(decl, javalang.tree.InterfaceDeclaration):
            kind = "interface"
        elif isinstance(decl, javalang.tree.EnumDeclaration):
            kind = "enum"

        # Modifiers and annotations
        modifiers = list(decl.modifiers or [])
        annotations = list(decl.annotations or [])
        decorator_names = [a.name if hasattr(a, "name") else str(a) for a in annotations]

        # Extends / Implements
        extends_list = []
        implements_list = []
        bases = []
        if hasattr(decl, "extends") and decl.extends:
            if isinstance(decl.extends, list):
                extends_list = decl.extends
            else:
                extends_list = [decl.extends]
            bases.extend(e.name if hasattr(e, "name") else str(e) for e in extends_list)
        if hasattr(decl, "implements") and decl.implements:
            implements_list = list(decl.implements)
            bases.extend(i.name if hasattr(i, "name") else str(i) for i in implements_list)

        # Type parameters
        type_params = list(decl.type_parameters or []) if hasattr(decl, "type_parameters") else []

        # Line info
        line_start = decl.position[0] if hasattr(decl, "position") and decl.position else 1
        line_end = _estimate_java_end_line(content, line_start)

        sig = _build_java_signature(
            name, modifiers, annotations, kind if kind != "class" else "class",
            extends=extends_list or None, implements=implements_list or None,
            type_params=type_params or None,
        )

        docstring = _extract_javadoc_summary(content, line_start)

        entry = SymbolEntry(
            fqn=fqn,
            file_path=rel_path,
            name=name,
            symbol_type="class",  # all type decls stored as "class" for hierarchy builder
            line_start=line_start,
            line_end=line_end,
            signature=sig,
            docstring_summary=docstring,
            decorators=decorator_names,
            bases=bases,
            language="java",
        )
        entries.append(entry)

        # Process members in body
        body = getattr(decl, "body", None) or []
        for member in body:
            actual = member
            # javalang wraps body members; for type declarations body is a list
            # of declaration objects directly
            if isinstance(member, (
                javalang.tree.MethodDeclaration,
                javalang.tree.ConstructorDeclaration,
            )):
                _process_method(member, fqn)
            elif isinstance(member, (
                javalang.tree.ClassDeclaration,
                javalang.tree.InterfaceDeclaration,
                javalang.tree.EnumDeclaration,
            )):
                _process_type_decl(member, fqn)

    def _process_method(decl, parent_fqn: str):
        """Process a method or constructor declaration."""
        is_constructor = not hasattr(decl, "return_type")
        name = decl.name if not is_constructor else "<init>"
        method_fqn = f"{parent_fqn}.{name}"

        modifiers = list(decl.modifiers or [])
        annotations = list(decl.annotations or [])
        decorator_names = [a.name if hasattr(a, "name") else str(a) for a in annotations]

        params_list = list(decl.parameters or [])
        param_strs = []
        for p in params_list:
            p_type = p.type.name if hasattr(p, "type") and hasattr(p.type, "name") else str(getattr(p, "type", ""))
            p_name = p.name if hasattr(p, "name") else str(p)
            param_strs.append(f"{p_type} {p_name}")

        return_type = ""
        if hasattr(decl, "return_type") and decl.return_type:
            return_type = decl.return_type.name if hasattr(decl.return_type, "name") else str(decl.return_type)

        throws = list(decl.throws or []) if hasattr(decl, "throws") and decl.throws else []

        line_start = decl.position[0] if hasattr(decl, "position") and decl.position else 1
        line_end = _estimate_java_end_line(content, line_start)

        kind = "constructor" if is_constructor else "method"
        sig = _build_java_signature(
            decl.name, modifiers, annotations, kind,
            params=params_list, return_type=return_type,
            throws=throws,
        )

        docstring = _extract_javadoc_summary(content, line_start)

        entry = SymbolEntry(
            fqn=method_fqn,
            file_path=rel_path,
            name=name,
            symbol_type="method",
            line_start=line_start,
            line_end=line_end,
            signature=sig,
            docstring_summary=docstring,
            parent_class=parent_fqn,
            decorators=decorator_names,
            params=param_strs,
            return_type=return_type,
            language="java",
        )
        entries.append(entry)

    # Walk top-level type declarations
    for type_decl in (tree.types or []):
        if isinstance(type_decl, (
            javalang.tree.ClassDeclaration,
            javalang.tree.InterfaceDeclaration,
            javalang.tree.EnumDeclaration,
        )):
            _process_type_decl(type_decl)

    return entries


def build_symbol_table(
    repo_path: str,
    file_contents: "dict[str, str] | None" = None,
    file_asts: "dict[str, ast.Module] | None" = None,
    file_java_trees: "dict[str, object] | None" = None,
) -> SymbolTable:
    """Walk the repository and build a SymbolTable of all Python and Java symbols.

    Args:
        repo_path: Repository root path.
        file_contents: Optional pre-read file contents ``{rel_path: source}``.
            If provided, skips ``os.walk`` + ``read_text``.
        file_asts: Optional pre-parsed AST trees ``{rel_path: ast.Module}``.
            Passed through to ``extract_symbols_from_source``.
        file_java_trees: Optional pre-parsed Java trees ``{rel_path: CompilationUnit}``.
            Passed through to ``extract_java_symbols_from_source``.
    """
    table = SymbolTable()

    if file_contents is not None:
        for rel_path, content in file_contents.items():
            if rel_path.endswith(".py"):
                tree = file_asts.get(rel_path) if file_asts else None
                for entry in extract_symbols_from_source(rel_path, content, tree=tree):
                    table.add(entry)
            elif rel_path.endswith(".java"):
                jtree = file_java_trees.get(rel_path) if file_java_trees else None
                for entry in extract_java_symbols_from_source(rel_path, content, tree=jtree):
                    table.add(entry)
    else:
        repo = Path(repo_path)
        for dirpath, dirnames, filenames in os.walk(repo):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
            for fname in filenames:
                fpath = Path(dirpath) / fname
                rel_path = str(fpath.relative_to(repo)).replace("\\", "/")
                if fname.endswith(".py"):
                    try:
                        content = fpath.read_text(encoding="utf-8", errors="replace")
                    except Exception:
                        continue
                    tree = file_asts.get(rel_path) if file_asts else None
                    for entry in extract_symbols_from_source(rel_path, content, tree=tree):
                        table.add(entry)
                elif fname.endswith(".java"):
                    try:
                        content = fpath.read_text(encoding="utf-8", errors="replace")
                    except Exception:
                        continue
                    jtree = file_java_trees.get(rel_path) if file_java_trees else None
                    for entry in extract_java_symbols_from_source(rel_path, content, tree=jtree):
                        table.add(entry)

    return table
