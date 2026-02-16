"""
Class hierarchy: parent/child relationships resolved through import map.

Uses base class names from SymbolTable entries and resolves them to FQNs
via the import map, then inverts to build child→parent mappings.
"""

from dataclasses import dataclass, field

from src.code_index.symbol_table import SymbolTable


@dataclass
class ClassHierarchy:
    """Bidirectional class inheritance graph."""

    parents: dict[str, list[str]] = field(default_factory=dict)  # class FQN → [parent FQNs]
    children: dict[str, list[str]] = field(default_factory=dict)  # class FQN → [child FQNs]

    def get_parents(self, fqn: str) -> list[str]:
        return self.parents.get(fqn, [])

    def get_children(self, fqn: str) -> list[str]:
        return self.children.get(fqn, [])

    def get_ancestors(self, fqn: str, max_depth: int = 10) -> list[str]:
        """BFS up the hierarchy."""
        result: list[str] = []
        visited: set[str] = {fqn}
        queue = list(self.parents.get(fqn, []))
        depth = 0
        while queue and depth < max_depth:
            next_queue: list[str] = []
            for parent in queue:
                if parent not in visited:
                    visited.add(parent)
                    result.append(parent)
                    next_queue.extend(self.parents.get(parent, []))
            queue = next_queue
            depth += 1
        return result

    def get_descendants(self, fqn: str, max_depth: int = 10) -> list[str]:
        """BFS down the hierarchy."""
        result: list[str] = []
        visited: set[str] = {fqn}
        queue = list(self.children.get(fqn, []))
        depth = 0
        while queue and depth < max_depth:
            next_queue: list[str] = []
            for child in queue:
                if child not in visited:
                    visited.add(child)
                    result.append(child)
                    next_queue.extend(self.children.get(child, []))
            queue = next_queue
            depth += 1
        return result

    def to_dict(self) -> dict:
        return {
            "parents": self.parents,
            "children": self.children,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ClassHierarchy":
        return cls(
            parents=data.get("parents", {}),
            children=data.get("children", {}),
        )


def build_class_hierarchy(
    symbol_table: SymbolTable,
    import_map: dict[str, dict[str, str]],
) -> ClassHierarchy:
    """Build class hierarchy by resolving base class names to FQNs.

    For each class in the symbol table with bases, resolve each base name:
    1. Check the import map for the class's file
    2. Check if the base is defined in the same file
    3. Check globally by name
    """
    parents: dict[str, list[str]] = {}
    children: dict[str, list[str]] = {}

    # Direct lookup by type — avoids iterating all 50K+ entries
    class_entries = symbol_table.get_by_type("class")

    for entry in class_entries:
        if not entry.bases:
            continue

        resolved_parents: list[str] = []
        file_imports = import_map.get(entry.file_path, {})

        for base_name in entry.bases:
            resolved = _resolve_base_class(
                base_name, entry.file_path, file_imports, symbol_table
            )
            if resolved:
                resolved_parents.append(resolved)

        if resolved_parents:
            parents[entry.fqn] = resolved_parents
            for parent_fqn in resolved_parents:
                children.setdefault(parent_fqn, []).append(entry.fqn)

    return ClassHierarchy(parents=parents, children=children)


def _resolve_base_class(
    base_name: str,
    file_path: str,
    file_imports: dict[str, str],
    symbol_table: SymbolTable,
) -> str | None:
    """Resolve a base class name to its FQN."""
    # Strip any dotted access (e.g., "abc.ABC" → "ABC" is the import name,
    # but "abc.ABC" as a whole might be in imports)
    if base_name in file_imports:
        return file_imports[base_name]

    # Check if base is defined in the same file
    same_file_fqn = f"{file_path}::{base_name}"
    if symbol_table.get_by_fqn(same_file_fqn):
        return same_file_fqn

    # Check globally by name (might match multiple — take first)
    matches = symbol_table.get_by_name(base_name)
    class_matches = [m for m in matches if m.symbol_type == "class"]
    if len(class_matches) == 1:
        return class_matches[0].fqn

    return None
