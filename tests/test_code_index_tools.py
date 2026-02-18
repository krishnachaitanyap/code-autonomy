"""Tests for src/code_index/tools.py"""

import pytest

from src.code_index.storage import CodeIndex
from src.code_index.symbol_table import SymbolTable, SymbolEntry
from src.code_index.graph_builder import DependencyGraph
from src.code_index.hierarchy import ClassHierarchy
from src.code_index.entity_embeddings import EntityEmbeddings
from src.code_index.property_index import PropertyIndex
from src.code_index.tools import (
    CODE_INDEX_TOOLS,
    CODE_INDEX_TOOL_NAMES,
    execute_code_index_tool,
)


@pytest.fixture
def code_index():
    """Build a minimal CodeIndex for testing."""
    st = SymbolTable()
    st.add(SymbolEntry(
        fqn="lib.py::helper", file_path="lib.py", name="helper",
        symbol_type="function", line_start=1, line_end=5,
        signature="def helper(x: int) -> str",
        docstring_summary="A helper function.",
        params=["x: int"], return_type="str",
    ))
    st.add(SymbolEntry(
        fqn="app.py::main", file_path="app.py", name="main",
        symbol_type="function", line_start=1, line_end=10,
        signature="def main()",
        docstring_summary="Main entry point.",
    ))
    st.add(SymbolEntry(
        fqn="lib.py::Base", file_path="lib.py", name="Base",
        symbol_type="class", line_start=7, line_end=20,
        signature="class Base",
        docstring_summary="Base class.",
    ))
    st.add(SymbolEntry(
        fqn="app.py::App", file_path="app.py", name="App",
        symbol_type="class", line_start=12, line_end=30,
        signature="class App(Base)", bases=["Base"],
    ))

    graph = DependencyGraph(
        forward={"app.py::main": {"lib.py::helper"}},
        reverse={"lib.py::helper": {"app.py::main"}},
        file_imports={"app.py": {"lib.py"}},
        file_dependents={"lib.py": {"app.py"}},
    )

    hierarchy = ClassHierarchy(
        parents={"app.py::App": ["lib.py::Base"]},
        children={"lib.py::Base": ["app.py::App"]},
    )

    embeddings = EntityEmbeddings()  # empty, no sentence-transformers needed

    return CodeIndex(
        repo_id="test_repo",
        indexed_at=0.0,
        symbol_table=st,
        dependency_graph=graph,
        class_hierarchy=hierarchy,
        embeddings=embeddings,
        property_index=PropertyIndex(),
        total_symbols=4,
        total_files=2,
    )


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

class TestToolSchemas:
    def test_all_tools_present(self):
        assert len(CODE_INDEX_TOOLS) == 8

    def test_tool_names_match(self):
        schema_names = {t["function"]["name"] for t in CODE_INDEX_TOOLS}
        assert schema_names == CODE_INDEX_TOOL_NAMES

    def test_each_tool_has_required_fields(self):
        for tool in CODE_INDEX_TOOLS:
            assert tool["type"] == "function"
            func = tool["function"]
            assert "name" in func
            assert "description" in func
            assert "parameters" in func


# ---------------------------------------------------------------------------
# find_callers
# ---------------------------------------------------------------------------

class TestFindCallers:
    def test_by_name(self, code_index):
        result = execute_code_index_tool(code_index, "find_callers", {"symbol_name": "helper"})
        assert "app.py::main" in result

    def test_by_fqn(self, code_index):
        result = execute_code_index_tool(code_index, "find_callers", {"symbol_name": "lib.py::helper"})
        assert "app.py::main" in result

    def test_no_callers(self, code_index):
        result = execute_code_index_tool(code_index, "find_callers", {"symbol_name": "main"})
        assert "No callers" in result

    def test_not_found(self, code_index):
        result = execute_code_index_tool(code_index, "find_callers", {"symbol_name": "nonexistent"})
        assert "not found" in result.lower()


# ---------------------------------------------------------------------------
# find_dependents
# ---------------------------------------------------------------------------

class TestFindDependents:
    def test_has_dependents(self, code_index):
        result = execute_code_index_tool(code_index, "find_dependents", {"file_path": "lib.py"})
        assert "app.py" in result

    def test_no_dependents(self, code_index):
        result = execute_code_index_tool(code_index, "find_dependents", {"file_path": "app.py"})
        assert "No files depend" in result


# ---------------------------------------------------------------------------
# impact_analysis
# ---------------------------------------------------------------------------

class TestImpactAnalysis:
    def test_comprehensive_output(self, code_index):
        result = execute_code_index_tool(code_index, "impact_analysis", {"file_path": "lib.py"})
        assert "Impact Analysis" in result
        assert "helper" in result
        assert "Base" in result
        assert "app.py" in result  # dependent file

    def test_nonexistent_file(self, code_index):
        result = execute_code_index_tool(code_index, "impact_analysis", {"file_path": "nope.py"})
        assert "Impact Analysis" in result  # Still returns header


# ---------------------------------------------------------------------------
# describe_entity
# ---------------------------------------------------------------------------

class TestDescribeEntity:
    def test_describe_function(self, code_index):
        result = execute_code_index_tool(code_index, "describe_entity", {"symbol_name": "helper"})
        assert "lib.py::helper" in result
        assert "function" in result
        assert "A helper function." in result

    def test_describe_class_with_hierarchy(self, code_index):
        result = execute_code_index_tool(code_index, "describe_entity", {"symbol_name": "Base"})
        assert "lib.py::Base" in result
        assert "class" in result
        assert "app.py::App" in result  # child class

    def test_not_found(self, code_index):
        result = execute_code_index_tool(code_index, "describe_entity", {"symbol_name": "xxx"})
        assert "not found" in result.lower()


# ---------------------------------------------------------------------------
# find_similar (graceful degradation without embeddings)
# ---------------------------------------------------------------------------

class TestFindSimilar:
    def test_no_embeddings(self, code_index):
        result = execute_code_index_tool(code_index, "find_similar", {"query": "helper function"})
        # Should return graceful message since embeddings weren't built
        assert "not available" in result.lower() or "no similar" in result.lower()


# ---------------------------------------------------------------------------
# Unknown tool
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# context_for_edit
# ---------------------------------------------------------------------------

class TestContextForEdit:
    def test_basic_file_context(self, code_index):
        result = execute_code_index_tool(code_index, "context_for_edit", {"file_path": "lib.py"})
        assert "Pre-edit Context" in result
        assert "helper" in result
        assert "Base" in result

    def test_focused_on_symbol(self, code_index):
        result = execute_code_index_tool(code_index, "context_for_edit", {
            "file_path": "lib.py", "symbol_name": "helper",
        })
        assert "helper" in result
        # Callers section should show app.py::main
        assert "app.py::main" in result

    def test_shows_callers_and_callees(self, code_index):
        result = execute_code_index_tool(code_index, "context_for_edit", {
            "file_path": "app.py", "symbol_name": "main",
        })
        # main calls helper → callees section
        assert "Callees" in result
        assert "lib.py::helper" in result

    def test_shows_dependents(self, code_index):
        result = execute_code_index_tool(code_index, "context_for_edit", {"file_path": "lib.py"})
        assert "Dependents" in result
        assert "app.py" in result

    def test_shows_hierarchy(self, code_index):
        result = execute_code_index_tool(code_index, "context_for_edit", {
            "file_path": "lib.py", "symbol_name": "Base",
        })
        assert "Hierarchy" in result
        assert "app.py::App" in result  # child

    def test_nonexistent_file(self, code_index):
        result = execute_code_index_tool(code_index, "context_for_edit", {"file_path": "nope.py"})
        assert "No symbols found" in result


# ---------------------------------------------------------------------------
# predict_breakage
# ---------------------------------------------------------------------------

@pytest.fixture
def high_risk_code_index():
    """Build a CodeIndex with high-risk symbols (many callers, class children)."""
    st = SymbolTable()
    st.add(SymbolEntry(
        fqn="core.py::process", file_path="core.py", name="process",
        symbol_type="function", line_start=1, line_end=10,
        signature="def process(data: dict) -> dict",
    ))
    st.add(SymbolEntry(
        fqn="core.py::BaseHandler", file_path="core.py", name="BaseHandler",
        symbol_type="class", line_start=12, line_end=30,
        signature="class BaseHandler",
    ))
    # Create 6 callers for process (HIGH risk)
    callers = {}
    for i in range(6):
        fqn = f"mod{i}.py::use_process"
        st.add(SymbolEntry(
            fqn=fqn, file_path=f"mod{i}.py", name="use_process",
            symbol_type="function", line_start=1, line_end=3,
            signature=f"def use_process()",
        ))
        callers[fqn] = {"core.py::process"}

    forward = callers
    reverse = {"core.py::process": {f"mod{i}.py::use_process" for i in range(6)}}

    graph = DependencyGraph(
        forward=forward,
        reverse=reverse,
        file_imports={f"mod{i}.py": {"core.py"} for i in range(6)},
        file_dependents={"core.py": {f"mod{i}.py" for i in range(6)}},
    )

    hierarchy = ClassHierarchy(
        parents={"ext.py::SubHandler": ["core.py::BaseHandler"]},
        children={"core.py::BaseHandler": ["ext.py::SubHandler"]},
    )

    return CodeIndex(
        repo_id="test_risk",
        indexed_at=0.0,
        symbol_table=st,
        dependency_graph=graph,
        class_hierarchy=hierarchy,
        embeddings=EntityEmbeddings(),
        property_index=PropertyIndex(),
        total_symbols=st.__len__(),
        total_files=len(st.all_files),
    )


class TestPredictBreakage:
    def test_high_risk_many_callers(self, high_risk_code_index):
        result = execute_code_index_tool(high_risk_code_index, "predict_breakage", {"file_path": "core.py"})
        assert "HIGH" in result
        assert "process" in result

    def test_high_risk_class_children(self, high_risk_code_index):
        result = execute_code_index_tool(high_risk_code_index, "predict_breakage", {"file_path": "core.py"})
        assert "BaseHandler" in result
        assert "SubHandler" in result

    def test_overall_risk_shown(self, high_risk_code_index):
        result = execute_code_index_tool(high_risk_code_index, "predict_breakage", {"file_path": "core.py"})
        assert "Overall risk" in result

    def test_dependents_listed(self, high_risk_code_index):
        result = execute_code_index_tool(high_risk_code_index, "predict_breakage", {"file_path": "core.py"})
        assert "Dependent files" in result

    def test_low_risk_no_callers(self, code_index):
        result = execute_code_index_tool(code_index, "predict_breakage", {"file_path": "app.py"})
        # main has no callers → should not be HIGH
        assert "Per-symbol risk" in result

    def test_medium_risk(self, code_index):
        result = execute_code_index_tool(code_index, "predict_breakage", {"file_path": "lib.py"})
        # helper has 1 caller → MEDIUM
        assert "MEDIUM" in result

    def test_no_test_warning(self, high_risk_code_index):
        result = execute_code_index_tool(high_risk_code_index, "predict_breakage", {"file_path": "core.py"})
        assert "WARNING" in result or "No test" in result

    def test_nonexistent_file(self, code_index):
        result = execute_code_index_tool(code_index, "predict_breakage", {"file_path": "nope.py"})
        assert "No symbols found" in result


# ---------------------------------------------------------------------------
# Unknown tool
# ---------------------------------------------------------------------------

class TestUnknownTool:
    def test_unknown_tool(self, code_index):
        result = execute_code_index_tool(code_index, "not_a_tool", {})
        assert "Unknown" in result
