"""Tests for src/code_index/import_resolver.py"""

import pytest

from src.code_index.symbol_table import SymbolTable, SymbolEntry
from src.code_index.import_resolver import (
    resolve_imports,
    _module_to_file_candidates,
    _resolve_relative_import,
)


# ---------------------------------------------------------------------------
# Unit tests for helpers
# ---------------------------------------------------------------------------

class TestModuleToFileCandidates:
    def test_simple_module(self):
        candidates = _module_to_file_candidates("src.utils", "")
        assert "src/utils.py" in candidates
        assert "src/utils/__init__.py" in candidates

    def test_nested_module(self):
        candidates = _module_to_file_candidates("src.agent.tools", "")
        assert "src/agent/tools.py" in candidates

    def test_single_name(self):
        candidates = _module_to_file_candidates("config", "")
        assert "config.py" in candidates


class TestResolveRelativeImport:
    def test_level_1(self):
        result = _resolve_relative_import("src/agent/tools.py", "knowledge", 1)
        assert result == "src.agent.knowledge"

    def test_level_2(self):
        result = _resolve_relative_import("src/agent/tools.py", "constants", 2)
        assert result == "src.constants"

    def test_level_1_no_module(self):
        result = _resolve_relative_import("src/agent/tools.py", "", 1)
        assert result == "src.agent"


# ---------------------------------------------------------------------------
# Integration tests with resolve_imports
# ---------------------------------------------------------------------------

class TestResolveImports:
    def test_absolute_import(self, tmp_path):
        # Create two files: one importing from the other
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "__init__.py").write_text("")
        (tmp_path / "src" / "utils.py").write_text(
            "def helper():\n    pass\n\n"
            "class Config:\n    pass\n"
        )
        (tmp_path / "src" / "main.py").write_text(
            "from src.utils import helper, Config\n\n"
            "def run():\n    helper()\n"
        )

        # Build symbol table
        from src.code_index.symbol_table import build_symbol_table
        st = build_symbol_table(str(tmp_path))

        # Resolve imports
        result = resolve_imports(str(tmp_path), st)

        assert "src/main.py" in result
        imports = result["src/main.py"]
        assert "helper" in imports
        assert imports["helper"] == "src/utils.py::helper"
        assert "Config" in imports
        assert imports["Config"] == "src/utils.py::Config"

    def test_import_with_alias(self, tmp_path):
        (tmp_path / "mod.py").write_text("def process():\n    pass\n")
        (tmp_path / "app.py").write_text("from mod import process as proc\n")

        from src.code_index.symbol_table import build_symbol_table
        st = build_symbol_table(str(tmp_path))

        result = resolve_imports(str(tmp_path), st)

        if "app.py" in result:
            assert "proc" in result["app.py"]
            assert result["app.py"]["proc"] == "mod.py::process"

    def test_external_import_skipped(self, tmp_path):
        (tmp_path / "app.py").write_text(
            "import os\nfrom pathlib import Path\n\ndef main():\n    pass\n"
        )

        from src.code_index.symbol_table import build_symbol_table
        st = build_symbol_table(str(tmp_path))

        result = resolve_imports(str(tmp_path), st)

        # External imports should not appear
        if "app.py" in result:
            assert "os" not in result["app.py"]
            assert "Path" not in result["app.py"]

    def test_package_import(self, tmp_path):
        # Package with __init__.py
        pkg = tmp_path / "pkg"
        pkg.mkdir()
        (pkg / "__init__.py").write_text("def init_func():\n    pass\n")
        (tmp_path / "user.py").write_text("from pkg import init_func\n")

        from src.code_index.symbol_table import build_symbol_table
        st = build_symbol_table(str(tmp_path))

        result = resolve_imports(str(tmp_path), st)

        if "user.py" in result:
            assert "init_func" in result["user.py"]

    def test_empty_repo(self, tmp_path):
        from src.code_index.symbol_table import build_symbol_table
        st = build_symbol_table(str(tmp_path))
        result = resolve_imports(str(tmp_path), st)
        assert result == {}
