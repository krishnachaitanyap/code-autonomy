"""Tests for src/code_index/hierarchy.py"""

import pytest

from src.code_index.hierarchy import ClassHierarchy, build_class_hierarchy
from src.code_index.symbol_table import SymbolTable, SymbolEntry


# ---------------------------------------------------------------------------
# ClassHierarchy unit tests
# ---------------------------------------------------------------------------

class TestClassHierarchy:
    @pytest.fixture
    def hierarchy(self):
        return ClassHierarchy(
            parents={
                "b.py::Dog": ["a.py::Animal"],
                "c.py::GoldenRetriever": ["b.py::Dog"],
            },
            children={
                "a.py::Animal": ["b.py::Dog"],
                "b.py::Dog": ["c.py::GoldenRetriever"],
            },
        )

    def test_get_parents(self, hierarchy):
        assert hierarchy.get_parents("b.py::Dog") == ["a.py::Animal"]

    def test_get_children(self, hierarchy):
        assert hierarchy.get_children("a.py::Animal") == ["b.py::Dog"]

    def test_get_parents_empty(self, hierarchy):
        assert hierarchy.get_parents("a.py::Animal") == []

    def test_get_children_empty(self, hierarchy):
        assert hierarchy.get_children("c.py::GoldenRetriever") == []

    def test_get_ancestors(self, hierarchy):
        ancestors = hierarchy.get_ancestors("c.py::GoldenRetriever")
        assert "b.py::Dog" in ancestors
        assert "a.py::Animal" in ancestors

    def test_get_descendants(self, hierarchy):
        descendants = hierarchy.get_descendants("a.py::Animal")
        assert "b.py::Dog" in descendants
        assert "c.py::GoldenRetriever" in descendants

    def test_ancestors_max_depth(self, hierarchy):
        # max_depth=1: only one BFS iteration, so only direct parents
        ancestors = hierarchy.get_ancestors("c.py::GoldenRetriever", max_depth=1)
        assert "b.py::Dog" in ancestors
        # With max_depth=1, BFS goes 1 level: GoldenRetriever→Dog only
        assert "a.py::Animal" not in ancestors

    def test_serialization_roundtrip(self, hierarchy):
        data = hierarchy.to_dict()
        restored = ClassHierarchy.from_dict(data)
        assert restored.get_parents("b.py::Dog") == ["a.py::Animal"]
        assert restored.get_children("a.py::Animal") == ["b.py::Dog"]


# ---------------------------------------------------------------------------
# build_class_hierarchy
# ---------------------------------------------------------------------------

class TestBuildClassHierarchy:
    def test_resolves_same_file_base(self):
        """Base class in the same file is resolved."""
        table = SymbolTable()
        table.add(SymbolEntry(
            fqn="zoo.py::Animal", file_path="zoo.py", name="Animal",
            symbol_type="class", line_start=1, line_end=10, signature="class Animal",
        ))
        table.add(SymbolEntry(
            fqn="zoo.py::Dog", file_path="zoo.py", name="Dog",
            symbol_type="class", line_start=12, line_end=20,
            signature="class Dog(Animal)", bases=["Animal"],
        ))

        hierarchy = build_class_hierarchy(table, import_map={})
        assert hierarchy.get_parents("zoo.py::Dog") == ["zoo.py::Animal"]
        assert hierarchy.get_children("zoo.py::Animal") == ["zoo.py::Dog"]

    def test_resolves_imported_base(self):
        """Base class from another file is resolved via import map."""
        table = SymbolTable()
        table.add(SymbolEntry(
            fqn="base.py::Base", file_path="base.py", name="Base",
            symbol_type="class", line_start=1, line_end=5, signature="class Base",
        ))
        table.add(SymbolEntry(
            fqn="child.py::Child", file_path="child.py", name="Child",
            symbol_type="class", line_start=1, line_end=10,
            signature="class Child(Base)", bases=["Base"],
        ))

        import_map = {
            "child.py": {"Base": "base.py::Base"},
        }

        hierarchy = build_class_hierarchy(table, import_map)
        assert hierarchy.get_parents("child.py::Child") == ["base.py::Base"]
        assert hierarchy.get_children("base.py::Base") == ["child.py::Child"]

    def test_unresolvable_base_skipped(self):
        """External base classes (stdlib/third-party) are silently skipped."""
        table = SymbolTable()
        table.add(SymbolEntry(
            fqn="store.py::Store", file_path="store.py", name="Store",
            symbol_type="class", line_start=1, line_end=10,
            signature="class Store(ABC)", bases=["ABC"],
        ))

        hierarchy = build_class_hierarchy(table, import_map={})
        assert hierarchy.get_parents("store.py::Store") == []

    def test_no_classes(self):
        """Hierarchy is empty when there are no classes."""
        table = SymbolTable()
        table.add(SymbolEntry(
            fqn="funcs.py::do_stuff", file_path="funcs.py", name="do_stuff",
            symbol_type="function", line_start=1, line_end=5,
            signature="def do_stuff()",
        ))

        hierarchy = build_class_hierarchy(table, import_map={})
        assert hierarchy.parents == {}
        assert hierarchy.children == {}
