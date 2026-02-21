"""
Enhanced dependency graph with import-resolved cross-file edges.

Post-processes the existing call graph from ``src/context/call_graph`` by
resolving callee names through the import map, then builds both forward
(caller→callees) and reverse (callee→callers) graphs plus file-level
import/dependent maps.
"""

from dataclasses import dataclass, field

from src.code_index.symbol_table import SymbolTable
from src.code_index.import_resolver import resolve_imports


@dataclass
class DependencyGraph:
    """Bidirectional call graph + file-level dependency maps."""

    forward: dict[str, set[str]] = field(default_factory=dict)  # caller FQN → {callee FQNs}
    reverse: dict[str, set[str]] = field(default_factory=dict)  # callee FQN → {caller FQNs}
    file_imports: dict[str, set[str]] = field(default_factory=dict)  # file → {files it imports from}
    file_dependents: dict[str, set[str]] = field(default_factory=dict)  # file → {files that import it}

    def get_callers(self, fqn: str) -> set[str]:
        return self.reverse.get(fqn, set())

    def get_callees(self, fqn: str) -> set[str]:
        return self.forward.get(fqn, set())

    def get_file_dependents(self, file_path: str) -> set[str]:
        return self.file_dependents.get(file_path, set())

    def get_file_imports(self, file_path: str) -> set[str]:
        return self.file_imports.get(file_path, set())

    def to_dict(self) -> dict:
        """Serialize for JSON storage."""
        return {
            "forward": {k: sorted(v) for k, v in self.forward.items()},
            "reverse": {k: sorted(v) for k, v in self.reverse.items()},
            "file_imports": {k: sorted(v) for k, v in self.file_imports.items()},
            "file_dependents": {k: sorted(v) for k, v in self.file_dependents.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DependencyGraph":
        """Deserialize from JSON."""
        return cls(
            forward={k: set(v) for k, v in data.get("forward", {}).items()},
            reverse={k: set(v) for k, v in data.get("reverse", {}).items()},
            file_imports={k: set(v) for k, v in data.get("file_imports", {}).items()},
            file_dependents={k: set(v) for k, v in data.get("file_dependents", {}).items()},
        )


def build_dependency_graph(
    repo_path: str,
    symbol_table: SymbolTable,
    import_map: dict[str, dict[str, str]] | None = None,
    file_asts: "dict[str, object] | None" = None,
) -> DependencyGraph:
    """Build the enhanced dependency graph.

    1. Runs the existing ``build_call_graph()`` to get raw edges
    2. Resolves callee names through the import map
    3. Inverts to build the reverse graph
    4. Builds file-level import/dependent maps

    Args:
        repo_path: Repository root path.
        symbol_table: Built symbol table.
        import_map: Optional pre-built import map. If None, will be computed.
        file_asts: Optional pre-parsed AST trees passed through to
            ``build_call_graph``.
    """
    from src.context.call_graph import build_call_graph

    # Step 1: Get raw call graph
    raw_graph = build_call_graph(repo_path, file_asts=file_asts)

    # Step 2: Resolve imports if not provided
    if import_map is None:
        import_map = resolve_imports(repo_path, symbol_table)

    # Step 3: Build import-resolved forward graph
    forward: dict[str, set[str]] = {}
    known_fqns = symbol_table.all_fqns

    for caller_node, callees in raw_graph.items():
        # caller_node format: "path/file.py::func_name" or "path/file.py::Class.method"
        if "::" not in caller_node:
            continue
        caller_file = caller_node.split("::")[0]
        file_import_map = import_map.get(caller_file, {})

        resolved_callees: set[str] = set()
        for callee_node in callees:
            if "::" not in callee_node:
                continue
            callee_name = callee_node.split("::", 1)[1]
            # Extract the base name (before any dot for attribute calls)
            base_name = callee_name.split(".")[0] if "." in callee_name else callee_name

            # Try import resolution first
            if base_name in file_import_map:
                resolved_fqn = file_import_map[base_name]
                if resolved_fqn in known_fqns:
                    resolved_callees.add(resolved_fqn)
                    continue

            # Fall back to original callee node if it's a known FQN
            if callee_node in known_fqns:
                resolved_callees.add(callee_node)
            elif f"{caller_file}::{callee_name}" in known_fqns:
                resolved_callees.add(f"{caller_file}::{callee_name}")
            elif caller_file.endswith(".java"):
                # For Java files, try matching method name against file-local symbols
                file_symbols = symbol_table.get_by_file(caller_file)
                for sym in file_symbols:
                    if sym.name == callee_name or (
                        "." in callee_name and sym.fqn.endswith(callee_name)
                    ):
                        resolved_callees.add(sym.fqn)
                        break

        if resolved_callees:
            forward[caller_node] = resolved_callees

    # Step 4: Build reverse graph
    reverse: dict[str, set[str]] = {}
    for caller, callees in forward.items():
        for callee in callees:
            reverse.setdefault(callee, set()).add(caller)

    # Step 5: Build file-level import/dependent maps from import_map
    file_imports: dict[str, set[str]] = {}
    file_dependents: dict[str, set[str]] = {}

    for importing_file, imports in import_map.items():
        imported_files: set[str] = set()
        for local_name, target_fqn in imports.items():
            # Extract file from FQN
            if "::" in target_fqn:
                target_file = target_fqn.split("::")[0]
            else:
                target_file = target_fqn
            if target_file != importing_file:
                imported_files.add(target_file)

        if imported_files:
            file_imports[importing_file] = imported_files
            for target_file in imported_files:
                file_dependents.setdefault(target_file, set()).add(importing_file)

    return DependencyGraph(
        forward=forward,
        reverse=reverse,
        file_imports=file_imports,
        file_dependents=file_dependents,
    )
