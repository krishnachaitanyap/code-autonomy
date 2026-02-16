"""
Import resolution: maps local import names to in-repo FQNs.

For each Python file, parses ``import`` and ``from ... import`` statements,
converts module paths to file paths, and resolves imported names to their
symbol table FQNs.  External (stdlib/third-party) imports are skipped.
"""

import ast
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
) -> dict[str, dict[str, str]]:
    """Build per-file import resolution map.

    Returns ``{file_path: {local_name: target_fqn}}``

    Only in-repo modules are resolved.  stdlib and third-party imports are
    silently skipped.
    """
    repo = Path(repo_path)
    # Reuse file list from symbol table instead of re-walking the repo
    existing_files: set[str] = set(symbol_table.all_files)

    result: dict[str, dict[str, str]] = {}

    for rel_path in existing_files:
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
