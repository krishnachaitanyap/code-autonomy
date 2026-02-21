"""
Import resolution: maps local import names to in-repo FQNs.

For each Python file, parses ``import`` and ``from ... import`` statements,
converts module paths to file paths, and resolves imported names to their
symbol table FQNs.  External (stdlib/third-party) imports are skipped.

For Java files, resolves single-type, static, wildcard, and same-package
imports against the in-repo symbol table.
"""

import ast
import re
from pathlib import Path

from src.code_index.symbol_table import SymbolTable


def _module_to_file_candidates(module_path: str, repo_path: str) -> list[str]:
    """Convert a dotted module path to possible file paths within the repo.

    E.g. ``src.agent.tools`` → ``["src/agent/tools.py", "src/agent/tools/__init__.py"]``
    """
    parts = module_path.split(".")
    base = "/".join(parts)
    return [
        f"{base}.py",
        f"{base}/__init__.py",
    ]


def _resolve_relative_import(
    importing_file: str, module: str, level: int
) -> str:
    """Resolve a relative import to an absolute module path.

    ``level`` is the number of leading dots (1 = current package, 2 = parent, etc.).
    """
    parts = importing_file.replace("\\", "/").split("/")
    # Go up `level` directories from the file's directory
    if len(parts) > level:
        base_parts = parts[:-(level)]
    else:
        base_parts = []
    if module:
        return ".".join(base_parts + module.split("."))
    return ".".join(base_parts)


def resolve_imports(
    repo_path: str,
    symbol_table: SymbolTable,
    file_asts: "dict[str, ast.Module] | None" = None,
    file_contents: "dict[str, str] | None" = None,
) -> dict[str, dict[str, str]]:
    """Build per-file import resolution map.

    Returns ``{file_path: {local_name: target_fqn}}``

    Only in-repo modules are resolved.  stdlib and third-party imports are
    silently skipped.

    Args:
        repo_path: Repository root path.
        symbol_table: Built symbol table.
        file_asts: Optional pre-parsed AST trees ``{rel_path: ast.Module}``.
            If provided, skips ``read_text`` + ``ast.parse`` for cached files.
        file_contents: Optional pre-read file contents ``{rel_path: source}``.
            Used for Java import resolution.
    """
    repo = Path(repo_path)
    # Reuse file list from symbol table instead of re-walking the repo
    existing_files: set[str] = set(symbol_table.all_files)

    result: dict[str, dict[str, str]] = {}

    # --- Python import resolution ---
    for rel_path in existing_files:
        if not rel_path.endswith(".py"):
            continue

        # Use cached AST if available, otherwise read + parse from disk
        if file_asts is not None and rel_path in file_asts:
            tree = file_asts[rel_path]
        else:
            fpath = repo / rel_path
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(content)
            except (SyntaxError, UnicodeDecodeError):
                continue

        file_imports: dict[str, str] = {}

        for node in tree.body:  # imports are module-level; skip walking entire AST
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                level = node.level or 0

                # Resolve relative imports
                if level > 0:
                    module = _resolve_relative_import(rel_path, module, level)

                # Find the target file
                target_file = _find_target_file(module, existing_files)
                if target_file is None:
                    continue

                # Resolve each imported name
                for alias in node.names:
                    imported_name = alias.name
                    local_name = alias.asname or imported_name

                    if imported_name == "*":
                        continue

                    # Try to find the symbol in the target file
                    target_fqn = _resolve_name_in_file(
                        imported_name, target_file, symbol_table
                    )
                    if target_fqn:
                        file_imports[local_name] = target_fqn

            elif isinstance(node, ast.Import):
                # ``import src.agent.tools`` → local name ``src`` (or aliased)
                for alias in node.names:
                    module = alias.name
                    target_file = _find_target_file(module, existing_files)
                    if target_file is None:
                        continue
                    local_name = alias.asname or module
                    # Map to the module file itself (no specific symbol)
                    file_imports[local_name] = target_file

        if file_imports:
            result[rel_path] = file_imports

    # --- Java import resolution ---
    java_imports = resolve_java_imports(repo_path, symbol_table, file_contents)
    for rel_path, imports in java_imports.items():
        if rel_path in result:
            result[rel_path].update(imports)
        else:
            result[rel_path] = imports

    return result


def resolve_java_imports(
    repo_path: str,
    symbol_table: SymbolTable,
    file_contents: "dict[str, str] | None" = None,
) -> dict[str, dict[str, str]]:
    """Resolve Java import statements to in-repo FQNs.

    Handles:
    - Single-type imports: ``import com.example.UserService``
    - Static imports: ``import static com.example.Constants.MAX_SIZE``
    - Wildcard imports: ``import com.example.*``
    - Same-package implicit: classes in the same directory are automatically visible

    Returns ``{file_path: {local_name: target_fqn}}``.
    """
    existing_files = set(symbol_table.all_files)
    java_files = [f for f in existing_files if f.endswith(".java")]
    if not java_files:
        return {}

    # Build package-to-files map: "com/example" → ["com/example/UserService.java", ...]
    pkg_to_files: dict[str, list[str]] = {}
    for f in java_files:
        pkg_dir = "/".join(f.split("/")[:-1]) if "/" in f else ""
        pkg_to_files.setdefault(pkg_dir, []).append(f)

    # Build a quick map of class simple name → FQN for all Java classes
    java_class_fqns: dict[str, list[str]] = {}
    for entry in symbol_table.get_by_type("class"):
        if getattr(entry, "language", "python") == "java" and "::" in entry.fqn:
            java_class_fqns.setdefault(entry.name, []).append(entry.fqn)

    # Regex for Java import statements
    import_re = re.compile(
        r"^\s*import\s+(static\s+)?([a-zA-Z_][\w.]*(?:\.\*)?)\s*;",
        re.MULTILINE,
    )

    result: dict[str, dict[str, str]] = {}

    for rel_path in java_files:
        content = None
        if file_contents and rel_path in file_contents:
            content = file_contents[rel_path]
        else:
            fpath = Path(repo_path) / rel_path
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
            except Exception:
                content = ""

        file_imports: dict[str, str] = {}

        # Parse import statements via regex (faster than full AST for this)
        for match in import_re.finditer(content or ""):
            is_static = bool(match.group(1))
            import_path = match.group(2)

            if import_path.endswith(".*"):
                # Wildcard import: import com.example.*
                pkg_path = import_path[:-2].replace(".", "/")
                # Find all in-repo classes in that package
                for pkg_dir, files in pkg_to_files.items():
                    if pkg_dir == pkg_path or pkg_dir.endswith("/" + pkg_path):
                        for f in files:
                            for entry in symbol_table.get_by_file(f):
                                if entry.symbol_type == "class" and "::" in entry.fqn:
                                    simple_name = entry.fqn.split("::")[-1].split(".")[0]
                                    file_imports[simple_name] = entry.fqn
            elif is_static:
                # Static import: import static com.example.Constants.MAX_SIZE
                parts = import_path.rsplit(".", 1)
                if len(parts) == 2:
                    class_path, member_name = parts
                    simple_class = class_path.rsplit(".", 1)[-1]
                    # Find the class, then look for the member
                    for fqn in java_class_fqns.get(simple_class, []):
                        member_fqn = f"{fqn}.{member_name}"
                        if symbol_table.get_by_fqn(member_fqn):
                            file_imports[member_name] = member_fqn
                            break
                    else:
                        # Even if member not found, map the class
                        for fqn in java_class_fqns.get(simple_class, []):
                            file_imports[member_name] = fqn
                            break
            else:
                # Single-type import: import com.example.UserService
                simple_name = import_path.rsplit(".", 1)[-1]
                # Look up in symbol table by simple name
                for fqn in java_class_fqns.get(simple_name, []):
                    file_imports[simple_name] = fqn
                    break

        # Same-package implicit: classes in the same directory are visible
        file_dir = "/".join(rel_path.split("/")[:-1]) if "/" in rel_path else ""
        for sibling in pkg_to_files.get(file_dir, []):
            if sibling == rel_path:
                continue
            for entry in symbol_table.get_by_file(sibling):
                if entry.symbol_type == "class" and "::" in entry.fqn:
                    simple_name = entry.fqn.split("::")[-1].split(".")[0]
                    if simple_name not in file_imports:
                        file_imports[simple_name] = entry.fqn

        if file_imports:
            result[rel_path] = file_imports

    return result


def _find_target_file(module: str, existing_files: set[str]) -> str | None:
    """Find which repo file a dotted module path refers to."""
    candidates = _module_to_file_candidates(module, "")
    for candidate in candidates:
        if candidate in existing_files:
            return candidate
    return None


def _resolve_name_in_file(
    name: str, target_file: str, symbol_table: SymbolTable
) -> str | None:
    """Look up a name in the symbol table for a given file."""
    # Direct match: file::name
    fqn = f"{target_file}::{name}"
    if symbol_table.get_by_fqn(fqn):
        return fqn

    # Check if it's a class method (unlikely for top-level import but handle it)
    entries = symbol_table.get_by_file(target_file)
    for entry in entries:
        if entry.name == name:
            return entry.fqn

    # Could be a submodule or re-export — return file-level reference
    return None
