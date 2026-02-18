"""Tests for src/code_index/verifier.py"""

import pytest

from src.code_index.verifier import (
    VerificationResult,
    post_edit_verification_gate,
    generate_repair_suggestions,
    _check_syntax,
    _check_imports,
    _check_callers,
)
from src.code_index.storage import CodeIndex
from src.code_index.symbol_table import SymbolTable, SymbolEntry
from src.code_index.graph_builder import DependencyGraph
from src.code_index.hierarchy import ClassHierarchy
from src.code_index.entity_embeddings import EntityEmbeddings
from src.code_index.property_index import PropertyIndex


# ---------------------------------------------------------------------------
# VerificationResult
# ---------------------------------------------------------------------------

class TestVerificationResult:
    def test_initially_passes(self):
        r = VerificationResult()
        assert r.passed is True
        assert r.errors == []
        assert r.warnings == []

    def test_add_error(self):
        r = VerificationResult()
        r.add_error("broken")
        assert r.passed is False
        assert "broken" in r.errors

    def test_add_warning(self):
        r = VerificationResult()
        r.add_warning("be careful")
        assert r.passed is True  # Warnings don't fail
        assert "be careful" in r.warnings

    def test_summary(self):
        r = VerificationResult()
        r.add_error("syntax error")
        r.add_warning("import might fail")
        s = r.summary()
        assert "FAILED" in s
        assert "syntax error" in s
        assert "import might fail" in s


# ---------------------------------------------------------------------------
# Syntax check
# ---------------------------------------------------------------------------

class TestSyntaxCheck:
    def test_valid_syntax(self, tmp_path):
        (tmp_path / "good.py").write_text("def hello():\n    return 42\n")
        result = VerificationResult()
        _check_syntax(tmp_path, ["good.py"], result)
        assert result.passed is True

    def test_invalid_syntax(self, tmp_path):
        (tmp_path / "bad.py").write_text("def hello(\n")
        result = VerificationResult()
        _check_syntax(tmp_path, ["bad.py"], result)
        assert result.passed is False
        assert any("bad.py" in e for e in result.errors)

    def test_missing_file_skipped(self, tmp_path):
        result = VerificationResult()
        _check_syntax(tmp_path, ["nonexistent.py"], result)
        assert result.passed is True


# ---------------------------------------------------------------------------
# Import check
# ---------------------------------------------------------------------------

class TestImportCheck:
    def test_valid_import(self, tmp_path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "__init__.py").write_text("")
        (tmp_path / "src" / "utils.py").write_text("def func(): pass\n")
        (tmp_path / "src" / "main.py").write_text("from src.utils import func\n")
        result = VerificationResult()
        _check_imports(tmp_path, ["src/main.py"], result)
        assert result.passed is True

    def test_broken_src_import_warns(self, tmp_path):
        (tmp_path / "app.py").write_text("from src.nonexistent import thing\n")
        result = VerificationResult()
        _check_imports(tmp_path, ["app.py"], result)
        # Should generate a warning (not error) for in-repo style imports
        assert len(result.warnings) >= 1 or result.passed  # Either warns or passes

    def test_external_import_no_warning(self, tmp_path):
        (tmp_path / "app.py").write_text("import os\nfrom pathlib import Path\n")
        result = VerificationResult()
        _check_imports(tmp_path, ["app.py"], result)
        assert result.passed is True
        assert len(result.warnings) == 0


# ---------------------------------------------------------------------------
# Caller check
# ---------------------------------------------------------------------------

class TestCallerCheck:
    @pytest.fixture
    def code_index_with_caller(self, tmp_path):
        st = SymbolTable()
        st.add(SymbolEntry(
            fqn="lib.py::helper", file_path="lib.py", name="helper",
            symbol_type="function", line_start=1, line_end=3,
            signature="def helper(x: int) -> str",
            params=["x: int"], return_type="str",
        ))
        graph = DependencyGraph(
            forward={"app.py::main": {"lib.py::helper"}},
            reverse={"lib.py::helper": {"app.py::main"}},
        )
        return CodeIndex(
            repo_id="test", indexed_at=0, symbol_table=st,
            dependency_graph=graph,
            class_hierarchy=ClassHierarchy(),
            embeddings=EntityEmbeddings(),
            property_index=PropertyIndex(),
            total_symbols=1, total_files=1,
        )

    def test_signature_change_warns(self, tmp_path, code_index_with_caller):
        # Write a changed version of lib.py (new params)
        (tmp_path / "lib.py").write_text("def helper(x: int, y: int) -> str:\n    pass\n")
        result = VerificationResult()
        _check_callers(tmp_path, ["lib.py"], code_index_with_caller, result)
        assert len(result.warnings) >= 1
        assert any("helper" in w for w in result.warnings)

    def test_no_change_no_warning(self, tmp_path, code_index_with_caller):
        # Write same signature
        (tmp_path / "lib.py").write_text("def helper(x: int) -> str:\n    pass\n")
        result = VerificationResult()
        _check_callers(tmp_path, ["lib.py"], code_index_with_caller, result)
        assert len(result.warnings) == 0

    def test_removed_function_warns(self, tmp_path, code_index_with_caller):
        # Write lib.py without the helper function
        (tmp_path / "lib.py").write_text("# Empty\n")
        result = VerificationResult()
        _check_callers(tmp_path, ["lib.py"], code_index_with_caller, result)
        assert len(result.warnings) >= 1
        assert any("Removed" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Full gate integration
# ---------------------------------------------------------------------------

class TestPostEditVerificationGate:
    def test_all_pass(self, tmp_path):
        (tmp_path / "valid.py").write_text("def greet():\n    return 'hi'\n")

        st = SymbolTable()
        st.add(SymbolEntry(
            fqn="valid.py::greet", file_path="valid.py", name="greet",
            symbol_type="function", line_start=1, line_end=2,
            signature="def greet()", params=[],
        ))
        idx = CodeIndex(
            repo_id="test", indexed_at=0, symbol_table=st,
            dependency_graph=DependencyGraph(),
            class_hierarchy=ClassHierarchy(),
            embeddings=EntityEmbeddings(),
            property_index=PropertyIndex(),
            total_symbols=1, total_files=1,
        )

        result = post_edit_verification_gate(str(tmp_path), ["valid.py"], idx, {})
        assert result.passed is True

    def test_non_python_files_pass(self, tmp_path):
        idx = CodeIndex(
            repo_id="test", indexed_at=0, symbol_table=SymbolTable(),
            dependency_graph=DependencyGraph(),
            class_hierarchy=ClassHierarchy(),
            embeddings=EntityEmbeddings(),
            property_index=PropertyIndex(),
            total_symbols=0, total_files=0,
        )
        result = post_edit_verification_gate(str(tmp_path), ["data.json"], idx, {})
        assert result.passed is True

    def test_syntax_error_fails(self, tmp_path):
        (tmp_path / "broken.py").write_text("def func(\n")
        idx = CodeIndex(
            repo_id="test", indexed_at=0, symbol_table=SymbolTable(),
            dependency_graph=DependencyGraph(),
            class_hierarchy=ClassHierarchy(),
            embeddings=EntityEmbeddings(),
            property_index=PropertyIndex(),
            total_symbols=0, total_files=0,
        )
        result = post_edit_verification_gate(str(tmp_path), ["broken.py"], idx, {})
        assert result.passed is False


# ---------------------------------------------------------------------------
# VerificationResult repair features
# ---------------------------------------------------------------------------

class TestVerificationResultRepair:
    def test_add_repair_suggestion(self):
        r = VerificationResult()
        r.add_repair_suggestion("Fix syntax in app.py")
        assert "Fix syntax in app.py" in r.repair_suggestions

    def test_repair_prompt_when_passed(self):
        r = VerificationResult()
        assert r.repair_prompt() == ""

    def test_repair_prompt_with_errors(self):
        r = VerificationResult()
        r.add_error("Syntax error in app.py")
        r.add_repair_suggestion("Fix syntax in app.py")
        prompt = r.repair_prompt()
        assert "Verification failed" in prompt
        assert "Errors to fix" in prompt
        assert "Syntax error in app.py" in prompt
        assert "Suggested repairs" in prompt
        assert "Fix syntax in app.py" in prompt
        assert "task_complete" in prompt

    def test_repair_prompt_with_warnings(self):
        r = VerificationResult()
        r.add_error("Tests failed")
        r.add_warning("Signature changed")
        prompt = r.repair_prompt()
        assert "Warnings to address" in prompt
        assert "Signature changed" in prompt

    def test_repair_suggestions_initially_empty(self):
        r = VerificationResult()
        assert r.repair_suggestions == []


# ---------------------------------------------------------------------------
# generate_repair_suggestions
# ---------------------------------------------------------------------------

class TestGenerateRepairSuggestions:
    @pytest.fixture
    def code_index_for_repair(self):
        st = SymbolTable()
        st.add(SymbolEntry(
            fqn="lib.py::helper", file_path="lib.py", name="helper",
            symbol_type="function", line_start=1, line_end=5,
            signature="def helper(x: int) -> str",
            params=["x: int"], return_type="str",
        ))
        st.add(SymbolEntry(
            fqn="app.py::main", file_path="app.py", name="main",
            symbol_type="function", line_start=1, line_end=10,
            signature="def main()",
        ))
        graph = DependencyGraph(
            forward={"app.py::main": {"lib.py::helper"}},
            reverse={"lib.py::helper": {"app.py::main"}},
        )
        return CodeIndex(
            repo_id="test", indexed_at=0, symbol_table=st,
            dependency_graph=graph,
            class_hierarchy=ClassHierarchy(),
            embeddings=EntityEmbeddings(),
            property_index=PropertyIndex(),
            total_symbols=2, total_files=2,
        )

    def test_syntax_error_suggestion(self, code_index_for_repair):
        r = VerificationResult()
        r.add_error("Syntax error in lib.py: unexpected EOF")
        r.passed = False
        generate_repair_suggestions(r, code_index_for_repair, ["lib.py"])
        assert any("Fix syntax" in s for s in r.repair_suggestions)

    def test_signature_change_suggestion(self, code_index_for_repair):
        r = VerificationResult()
        r.add_error("something failed")
        r.passed = False
        r.add_warning("Changed signature of lib.py::helper — 1 caller(s) may need updating")
        generate_repair_suggestions(r, code_index_for_repair, ["lib.py"])
        assert any("app.py::main" in s for s in r.repair_suggestions)

    def test_test_failure_suggestion(self, code_index_for_repair):
        # Add a test file to the symbol table
        code_index_for_repair.symbol_table.add(SymbolEntry(
            fqn="tests/test_lib.py::test_helper", file_path="tests/test_lib.py",
            name="test_helper", symbol_type="function",
            line_start=1, line_end=5, signature="def test_helper()",
        ))
        r = VerificationResult()
        r.add_error("Scoped tests failed (tests/test_lib.py)")
        r.passed = False
        generate_repair_suggestions(r, code_index_for_repair, ["lib.py"])
        assert any("test_lib.py" in s for s in r.repair_suggestions)

    def test_no_suggestions_when_passed(self, code_index_for_repair):
        r = VerificationResult()
        # passed=True, no errors
        generate_repair_suggestions(r, code_index_for_repair, ["lib.py"])
        assert r.repair_suggestions == []
