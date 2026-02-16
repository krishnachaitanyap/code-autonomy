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
            result.append({
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
            })
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


def extract_symbols_from_source(rel_path: str, content: str) -> list[SymbolEntry]:
    """Extract all symbols from a Python source file using AST.

    Enhanced version of ``_extract_python_signatures_ast`` that captures
    line ranges, docstrings, and parent class context.
    """
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


def build_symbol_table(repo_path: str) -> SymbolTable:
    """Walk the repository and build a SymbolTable of all Python symbols."""
    repo = Path(repo_path)
    table = SymbolTable()

    for dirpath, dirnames, filenames in os.walk(repo):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fname in filenames:
            if not fname.endswith(".py"):
                continue
            fpath = Path(dirpath) / fname
            rel_path = str(fpath.relative_to(repo)).replace("\\", "/")
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for entry in extract_symbols_from_source(rel_path, content):
                table.add(entry)

    return table
