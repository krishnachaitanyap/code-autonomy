"""Tests for src/code_index/graph_builder.py"""

import pytest

from src.code_index.graph_builder import DependencyGraph, build_dependency_graph
from src.code_index.symbol_table import SymbolTable, SymbolEntry, build_symbol_table
from src.code_index.import_resolver import resolve_imports


# ---------------------------------------------------------------------------
# DependencyGraph unit tests
# ---------------------------------------------------------------------------

class TestDependencyGraph:
    @pytest.fixture
    def graph(self):
        return DependencyGraph(
            forward={
                "a.py::foo": {"b.py::bar", "b.py::baz"},
                "c.py::main": {"a.py::foo"},
            },
            reverse={
                "b.py::bar": {"a.py::foo"},
                "b.py::baz": {"a.py::foo"},
                "a.py::foo": {"c.py::main"},
            },
            file_imports={
                "a.py": {"b.py"},
                "c.py": {"a.py"},
            },
            file_dependents={
                "b.py": {"a.py"},
                "a.py": {"c.py"},
            },
        )

    def test_get_callers(self, graph):
        callers = graph.get_callers("a.py::foo")
        assert "c.py::main" in callers

    def test_get_callers_empty(self, graph):
        assert graph.get_callers("nonexistent") == set()

    def test_get_callees(self, graph):
        callees = graph.get_callees("a.py::foo")
        assert "b.py::bar" in callees
        assert "b.py::baz" in callees

    def test_get_file_dependents(self, graph):
        deps = graph.get_file_dependents("b.py")
        assert "a.py" in deps

    def test_get_file_imports(self, graph):
        imports = graph.get_file_imports("a.py")
        assert "b.py" in imports

    def test_serialization_roundtrip(self, graph):
        data = graph.to_dict()
        restored = DependencyGraph.from_dict(data)
        assert restored.get_callers("a.py::foo") == {"c.py::main"}
        assert restored.get_file_dependents("b.py") == {"a.py"}


# ---------------------------------------------------------------------------
# Integration: build_dependency_graph
# ---------------------------------------------------------------------------

class TestBuildDependencyGraph:
    def test_builds_file_dependency_maps(self, tmp_path):
        # Create files with imports
        (tmp_path / "lib.py").write_text("def helper():\n    pass\n")
        (tmp_path / "app.py").write_text(
            "from lib import helper\n\n"
            "def main():\n    helper()\n"
        )

        st = build_symbol_table(str(tmp_path))
        import_map = resolve_imports(str(tmp_path), st)
        graph = build_dependency_graph(str(tmp_path), st, import_map)

        # File-level dependency maps should be populated
        assert "lib.py" in graph.file_dependents
        assert "app.py" in graph.file_dependents.get("lib.py", set())

        assert "app.py" in graph.file_imports
        assert "lib.py" in graph.file_imports.get("app.py", set())

    def test_empty_repo(self, tmp_path):
        st = build_symbol_table(str(tmp_path))
        graph = build_dependency_graph(str(tmp_path), st)
        assert graph.forward == {}
        assert graph.reverse == {}

    def test_reverse_graph_inversion(self, tmp_path):
        """Verify that the reverse graph is the correct inversion of forward."""
        (tmp_path / "a.py").write_text("def foo():\n    pass\n")
        (tmp_path / "b.py").write_text(
            "from a import foo\n\ndef bar():\n    foo()\n"
        )

        st = build_symbol_table(str(tmp_path))
        import_map = resolve_imports(str(tmp_path), st)
        graph = build_dependency_graph(str(tmp_path), st, import_map)

        # Check that every forward edge has a matching reverse edge
        for caller, callees in graph.forward.items():
            for callee in callees:
                assert caller in graph.reverse.get(callee, set()), \
                    f"Missing reverse edge: {callee} -> {caller}"
