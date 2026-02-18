"""Tests for src/code_index/property_index.py and the find_all_usages tool."""

import ast
import textwrap
from unittest.mock import patch, MagicMock

import pytest

from src.code_index.property_index import (
    PropertyIndex,
    build_property_index,
    _extract_python_properties,
)
from src.code_index.storage import CodeIndex
from src.code_index.symbol_table import SymbolTable, SymbolEntry
from src.code_index.graph_builder import DependencyGraph
from src.code_index.hierarchy import ClassHierarchy
from src.code_index.entity_embeddings import EntityEmbeddings
from src.code_index.tools import (
    CODE_INDEX_TOOLS,
    CODE_INDEX_TOOL_NAMES,
    execute_code_index_tool,
)


# ---------------------------------------------------------------------------
# Python extraction
# ---------------------------------------------------------------------------

class TestPythonExtraction:
    def test_attribute_access(self):
        source = "self.timeout = 30"
        tree = ast.parse(source)
        results = _extract_python_properties("a.py", source, tree)
        names = [r[0] for r in results]
        assert "timeout" in names

    def test_subscript_access(self):
        source = 'config["timeout"]'
        tree = ast.parse(source)
        results = _extract_python_properties("a.py", source, tree)
        names = [r[0] for r in results]
        assert "timeout" in names

    def test_call_args(self):
        source = 'cfg.get("timeout")'
        tree = ast.parse(source)
        results = _extract_python_properties("a.py", source, tree)
        names = [r[0] for r in results]
        assert "timeout" in names

    def test_call_multiple_args(self):
        source = 'get_int("jira", "timeout")'
        tree = ast.parse(source)
        results = _extract_python_properties("a.py", source, tree)
        names = [r[0] for r in results]
        assert "jira" in names
        assert "timeout" in names

    def test_constant_assignment(self):
        source = "TIMEOUT_MS = 30000"
        tree = ast.parse(source)
        results = _extract_python_properties("a.py", source, tree)
        names = [r[0] for r in results]
        assert "TIMEOUT_MS" in names

    def test_annotated_assignment(self):
        source = "timeout: int = 30"
        tree = ast.parse(source)
        results = _extract_python_properties("a.py", source, tree)
        names = [r[0] for r in results]
        assert "timeout" in names

    def test_line_numbers(self):
        source = textwrap.dedent("""\
            x = 1
            self.timeout = 30
            config["retries"] = 3
        """)
        tree = ast.parse(source)
        results = _extract_python_properties("a.py", source, tree)
        # timeout attribute on line 2
        timeout_results = [(n, l) for n, l, s in results if n == "timeout"]
        assert any(l == 2 for _, l in timeout_results)

    def test_snippet_content(self):
        source = "self.timeout = 30"
        tree = ast.parse(source)
        results = _extract_python_properties("a.py", source, tree)
        snippets = [r[2] for r in results if r[0] == "timeout"]
        assert any("self.timeout = 30" in s for s in snippets)


# ---------------------------------------------------------------------------
# Java extraction (mocked javalang)
# ---------------------------------------------------------------------------

class TestJavaExtraction:
    def test_java_import_guard(self):
        """If javalang is not installed, extraction returns empty."""
        from src.code_index.property_index import _extract_java_properties
        # Even if javalang IS installed, passing bad source should not crash
        results = _extract_java_properties("App.java", "not valid java {{{")
        assert isinstance(results, list)

    def test_java_field_declaration(self):
        """Test Java field extraction if javalang is available."""
        try:
            import javalang
        except ImportError:
            pytest.skip("javalang not installed")

        from src.code_index.property_index import _extract_java_properties

        source = textwrap.dedent("""\
            public class Config {
                private int timeout = 30;
                private String host = "localhost";
            }
        """)
        results = _extract_java_properties("Config.java", source)
        names = [r[0] for r in results]
        assert "timeout" in names
        assert "host" in names

    def test_java_method_invocation_string_arg(self):
        """Test Java method invocation with string literal argument."""
        try:
            import javalang
        except ImportError:
            pytest.skip("javalang not installed")

        from src.code_index.property_index import _extract_java_properties

        source = textwrap.dedent("""\
            public class Config {
                public String get() {
                    return props.getProperty("timeout");
                }
            }
        """)
        results = _extract_java_properties("Config.java", source)
        names = [r[0] for r in results]
        assert "timeout" in names

    def test_java_member_reference(self):
        """Test Java member reference extraction."""
        try:
            import javalang
        except ImportError:
            pytest.skip("javalang not installed")

        from src.code_index.property_index import _extract_java_properties

        source = textwrap.dedent("""\
            public class App {
                private int timeout;
                public void run() {
                    System.out.println(this.timeout);
                }
            }
        """)
        results = _extract_java_properties("App.java", source)
        names = [r[0] for r in results]
        assert "timeout" in names

    def test_java_annotation(self):
        """Test Java @Value annotation extraction."""
        try:
            import javalang
        except ImportError:
            pytest.skip("javalang not installed")

        from src.code_index.property_index import _extract_java_properties

        source = textwrap.dedent("""\
            import org.springframework.beans.factory.annotation.Value;

            public class Config {
                @Value("${app.timeout}")
                private int timeout;
            }
        """)
        results = _extract_java_properties("Config.java", source)
        names = [r[0] for r in results]
        assert "app.timeout" in names


# ---------------------------------------------------------------------------
# PropertyIndex lookup
# ---------------------------------------------------------------------------

class TestPropertyIndexLookup:
    def test_exact_lookup(self):
        pi = PropertyIndex()
        pi.add("timeout", "a.py", 10, "self.timeout = 30")
        pi.add("timeout", "b.py", 5, 'config["timeout"]')
        results = pi.lookup("timeout")
        assert len(results) == 2
        files = [r[0] for r in results]
        assert "a.py" in files
        assert "b.py" in files

    def test_lookup_missing(self):
        pi = PropertyIndex()
        assert pi.lookup("nonexistent") == []

    def test_lookup_fuzzy_substring(self):
        pi = PropertyIndex()
        pi.add("timeout", "a.py", 1, "x")
        pi.add("timeout_ms", "b.py", 2, "y")
        pi.add("max_retries", "c.py", 3, "z")
        results = pi.lookup_fuzzy("timeout")
        assert "timeout" in results
        assert "timeout_ms" in results
        assert "max_retries" not in results

    def test_lookup_fuzzy_regex(self):
        pi = PropertyIndex()
        pi.add("timeout", "a.py", 1, "x")
        pi.add("TIMEOUT_MS", "b.py", 2, "y")
        results = pi.lookup_fuzzy(r"^timeout", )
        assert "timeout" in results
        # Case-insensitive
        assert "TIMEOUT_MS" in results

    def test_lookup_fuzzy_invalid_regex(self):
        """Invalid regex should fall back to escaped literal."""
        pi = PropertyIndex()
        pi.add("config(x", "a.py", 1, "x")
        # "config(x" is invalid regex (unmatched paren) → falls back to literal
        results = pi.lookup_fuzzy("config(x")
        assert "config(x" in results


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

class TestSerialization:
    def test_round_trip(self):
        pi = PropertyIndex()
        pi.add("timeout", "a.py", 10, "self.timeout = 30")
        pi.add("timeout", "b.py", 5, 'cfg["timeout"]')
        pi.add("retries", "c.py", 1, "RETRIES = 3")

        data = pi.to_dict()
        restored = PropertyIndex.from_dict(data)

        assert restored.lookup("timeout") == pi.lookup("timeout")
        assert restored.lookup("retries") == pi.lookup("retries")
        assert len(restored.index) == len(pi.index)

    def test_empty_round_trip(self):
        pi = PropertyIndex()
        data = pi.to_dict()
        restored = PropertyIndex.from_dict(data)
        assert restored.index == {}


# ---------------------------------------------------------------------------
# build_property_index
# ---------------------------------------------------------------------------

class TestBuildPropertyIndex:
    def test_builds_from_file_asts(self, tmp_path):
        source = textwrap.dedent("""\
            class Config:
                def __init__(self):
                    self.timeout = 30
                    self.retries = 3
        """)
        tree = ast.parse(source)
        file_contents = {"config.py": source}
        file_asts = {"config.py": tree}

        pi = build_property_index(str(tmp_path), file_contents, file_asts)
        assert len(pi.lookup("timeout")) > 0
        assert len(pi.lookup("retries")) > 0


# ---------------------------------------------------------------------------
# find_all_usages tool integration
# ---------------------------------------------------------------------------

@pytest.fixture
def code_index_with_properties():
    """Build a CodeIndex with a PropertyIndex for testing find_all_usages."""
    st = SymbolTable()
    st.add(SymbolEntry(
        fqn="config.py::Config", file_path="config.py", name="Config",
        symbol_type="class", line_start=1, line_end=10,
        signature="class Config",
    ))
    st.add(SymbolEntry(
        fqn="app.py::main", file_path="app.py", name="main",
        symbol_type="function", line_start=1, line_end=5,
        signature="def main()",
    ))
    st.add(SymbolEntry(
        fqn="lib.py::timeout", file_path="lib.py", name="timeout",
        symbol_type="function", line_start=1, line_end=3,
        signature="def timeout()",
    ))

    graph = DependencyGraph(
        forward={"app.py::main": {"lib.py::timeout"}},
        reverse={"lib.py::timeout": {"app.py::main"}},
        file_imports={"app.py": {"lib.py"}},
        file_dependents={"lib.py": {"app.py"}},
    )

    hierarchy = ClassHierarchy()
    embeddings = EntityEmbeddings()

    pi = PropertyIndex()
    pi.add("timeout", "config.py", 3, "self.timeout = 30")
    pi.add("timeout", "app.py", 7, 'config["timeout"]')

    return CodeIndex(
        repo_id="test",
        indexed_at=0.0,
        symbol_table=st,
        dependency_graph=graph,
        class_hierarchy=hierarchy,
        embeddings=embeddings,
        property_index=pi,
        total_symbols=3,
        total_files=3,
        repo_path="",  # empty = skip grep
    )


class TestFindAllUsagesTool:
    def test_tool_registered(self):
        assert "find_all_usages" in CODE_INDEX_TOOL_NAMES

    def test_tool_in_schemas(self):
        names = {t["function"]["name"] for t in CODE_INDEX_TOOLS}
        assert "find_all_usages" in names

    def test_high_confidence_from_property_index(self, code_index_with_properties):
        result = execute_code_index_tool(
            code_index_with_properties, "find_all_usages", {"name": "timeout"}
        )
        assert "HIGH" in result
        assert "config.py:3" in result
        assert "app.py:7" in result

    def test_high_confidence_from_callers(self, code_index_with_properties):
        """Callers of symbol named 'timeout' should appear as HIGH."""
        result = execute_code_index_tool(
            code_index_with_properties, "find_all_usages",
            {"name": "timeout", "include_grep": False},
        )
        assert "HIGH" in result
        # app.py::main calls lib.py::timeout
        assert "app.py" in result

    def test_no_usages(self, code_index_with_properties):
        result = execute_code_index_tool(
            code_index_with_properties, "find_all_usages", {"name": "nonexistent"}
        )
        assert "No usages found" in result

    def test_empty_name(self, code_index_with_properties):
        result = execute_code_index_tool(
            code_index_with_properties, "find_all_usages", {"name": ""}
        )
        assert "Error" in result

    def test_deduplication(self, code_index_with_properties):
        """Same (file, line) should not appear twice."""
        result = execute_code_index_tool(
            code_index_with_properties, "find_all_usages", {"name": "timeout"}
        )
        lines = result.split("\n")
        entries = [l for l in lines if l.strip().startswith("- ")]
        file_lines = [l.strip().split()[1] for l in entries]
        assert len(file_lines) == len(set(file_lines))

    def test_output_format_sections(self, code_index_with_properties):
        result = execute_code_index_tool(
            code_index_with_properties, "find_all_usages", {"name": "timeout"}
        )
        assert "All usages of 'timeout'" in result
        assert "total)" in result


# ---------------------------------------------------------------------------
# Grep fallback
# ---------------------------------------------------------------------------

class TestGrepFallback:
    def test_grep_with_comment_lines(self, tmp_path):
        """Comment lines should get LOW confidence."""
        # Create a test file with a comment line
        py_file = tmp_path / "test.py"
        py_file.write_text("# timeout is important\ntimeout = 30\n")

        from src.code_index.tools import _grep_for_name
        results = _grep_for_name(str(tmp_path), "timeout")
        comments = [r for r in results if r[3] is True]
        code = [r for r in results if r[3] is False]
        assert len(comments) >= 1  # the comment line
        assert len(code) >= 1  # the assignment line

    def test_grep_returns_relative_paths(self, tmp_path):
        py_file = tmp_path / "sub" / "mod.py"
        py_file.parent.mkdir(parents=True)
        py_file.write_text("timeout = 30\n")

        from src.code_index.tools import _grep_for_name
        results = _grep_for_name(str(tmp_path), "timeout")
        assert len(results) >= 1
        rel_path = results[0][0]
        assert not rel_path.startswith("/")

    def test_grep_timeout_does_not_crash(self):
        """Grep on nonexistent path should not crash."""
        from src.code_index.tools import _grep_for_name
        results = _grep_for_name("/nonexistent/path/12345", "timeout")
        assert results == []


# ---------------------------------------------------------------------------
# CodeIndex with property_index in existing test fixture compatibility
# ---------------------------------------------------------------------------

class TestCodeIndexBackwardCompat:
    def test_schema_count(self):
        """Updated tool count should be 8."""
        assert len(CODE_INDEX_TOOLS) == 8

    def test_tool_names_match_schemas(self):
        schema_names = {t["function"]["name"] for t in CODE_INDEX_TOOLS}
        assert schema_names == CODE_INDEX_TOOL_NAMES
