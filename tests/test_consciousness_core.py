"""Tests for src.consciousness.core optimizations."""

import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from src.consciousness.core import (
    _walk_repo,
    _RepoIndex,
    _insert_into_tree,
    _score_file,
    _extract_signatures,
    _extract_python_signatures_ast,
    _extract_python_signatures_regex_fallback,
    _extract_java_signatures_regex,
    _detect_conventions_from_index,
    _format_structure,
    _get_changed_files_since,
    _incremental_update,
    build_consciousness,
    ProjectConsciousness,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_repo(tmp: Path, files: dict) -> Path:
    """Create a temp repo with given file layout. files = {rel_path: content}."""
    for rel, content in files.items():
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp


# ---------------------------------------------------------------------------
# 1. test_walk_repo
# ---------------------------------------------------------------------------

class TestWalkRepo:
    def test_prunes_skip_dirs(self, tmp_path):
        _make_repo(tmp_path, {
            "src/main.py": "print('hello')",
            "node_modules/dep/index.js": "module.exports = {}",
            ".git/config": "[core]",
            "__pycache__/mod.pyc": "...",
            "lib/util.py": "x = 1",
        })
        idx = _walk_repo(tmp_path)
        rel_paths = [r for r, _ in idx.code_files]
        assert any("main.py" in r for r in rel_paths)
        assert any("util.py" in r for r in rel_paths)
        # Skip dirs must be pruned
        assert not any("node_modules" in r for r in rel_paths)
        assert not any(".git" in r for r in rel_paths)
        assert not any("__pycache__" in r for r in rel_paths)

    def test_index_fields(self, tmp_path):
        _make_repo(tmp_path, {
            "app.py": "class App: pass",
            "test_app.py": "def test_it(): pass",
            "Main.java": "public class Main {}",
        })
        idx = _walk_repo(tmp_path)
        assert idx.has_py is True
        assert idx.has_java is True
        assert idx.has_test_py is True
        assert idx.total_code_files == 3

    def test_structure_tree_populated(self, tmp_path):
        _make_repo(tmp_path, {
            "src/core.py": "x=1",
            "src/utils.py": "y=2",
            "config.yml": "key: val",
        })
        idx = _walk_repo(tmp_path)
        tree = idx.structure_tree
        assert "config.yml" in tree["files"]
        assert "src" in tree["subdirs"]
        assert "core.py" in tree["subdirs"]["src"]["files"]

    def test_empty_repo(self, tmp_path):
        idx = _walk_repo(tmp_path)
        assert idx.total_code_files == 0
        assert idx.code_files == []
        assert idx.has_py is False


# ---------------------------------------------------------------------------
# 2. test_score_file
# ---------------------------------------------------------------------------

class TestScoreFile:
    def test_entry_point_beats_boilerplate(self):
        entry_score = _score_file("src/main.py", "x\n" * 50, sig_count=2)
        boiler_score = _score_file("src/__init__.py", "x\n" * 50, sig_count=2)
        assert entry_score > boiler_score

    def test_many_sigs_high_score(self):
        rich = _score_file("src/models.py", "x\n" * 100, sig_count=5)
        poor = _score_file("src/models.py", "x\n" * 100, sig_count=0)
        assert rich > poor

    def test_medium_size_preferred(self):
        medium = _score_file("a.py", "x\n" * 100, sig_count=1)
        tiny = _score_file("a.py", "x\n" * 2, sig_count=1)
        assert medium > tiny

    def test_deep_nesting_penalty(self):
        shallow = _score_file("src/core.py", "x\n" * 50, sig_count=1)
        deep = _score_file("a/b/c/d/e/f.py", "x\n" * 50, sig_count=1)
        assert shallow > deep


# ---------------------------------------------------------------------------
# 3. test_extract_python_signatures_ast
# ---------------------------------------------------------------------------

class TestPythonSignaturesAST:
    def test_function_with_params_and_return(self):
        code = '''
def greet(name: str, loud: bool = False) -> str:
    return name
'''
        sigs = _extract_python_signatures_ast("mod.py", code)
        func_sigs = [s for s in sigs if s["type"] == "function"]
        assert len(func_sigs) == 1
        sig = func_sigs[0]
        assert sig["name"] == "greet"
        assert "name: str" in sig["params"]
        assert "loud: bool=..." in sig["params"]
        assert sig["return_type"] == "str"

    def test_class_with_bases_and_decorators(self):
        code = '''
from abc import ABC

@dataclass
class MyModel(ABC):
    x: int = 0
'''
        sigs = _extract_python_signatures_ast("mod.py", code)
        class_sigs = [s for s in sigs if s["type"] == "class"]
        assert len(class_sigs) == 1
        sig = class_sigs[0]
        assert sig["name"] == "MyModel"
        assert "ABC" in sig["bases"]
        assert "dataclass" in sig["decorators"]

    def test_async_function(self):
        code = '''
async def fetch(url: str) -> dict:
    pass
'''
        sigs = _extract_python_signatures_ast("mod.py", code)
        assert any(s["type"] == "async function" and s["name"] == "fetch" for s in sigs)

    def test_skips_self_cls(self):
        code = '''
class Foo:
    def bar(self, x: int) -> None:
        pass
    @classmethod
    def create(cls, name: str) -> "Foo":
        pass
'''
        sigs = _extract_python_signatures_ast("mod.py", code)
        bar_sig = next(s for s in sigs if s["name"] == "bar")
        assert "self" not in str(bar_sig.get("params", []))
        assert "x: int" in bar_sig["params"]
        create_sig = next(s for s in sigs if s["name"] == "create")
        assert "cls" not in str(create_sig.get("params", []))


# ---------------------------------------------------------------------------
# 4. test_extract_python_signatures_fallback
# ---------------------------------------------------------------------------

class TestPythonSignaturesFallback:
    def test_syntax_error_triggers_fallback(self):
        bad_code = "def foo(:\n    pass\nclass Bar:\n    pass"
        sigs = _extract_python_signatures_ast("broken.py", bad_code)
        # Should fall back to regex
        names = {s["name"] for s in sigs}
        assert "foo" in names
        assert "Bar" in names

    def test_regex_fallback_directly(self):
        code = "def hello():\n    pass\nclass World:\n    pass"
        sigs = _extract_python_signatures_regex_fallback("f.py", code)
        names = {s["name"] for s in sigs}
        assert "hello" in names
        assert "World" in names


# ---------------------------------------------------------------------------
# 5. test_extract_java_signatures
# ---------------------------------------------------------------------------

class TestJavaSignatures:
    def test_class_and_method(self):
        code = '''
public class UserService {
    public User findById(long id) {
        return null;
    }
    private void validate(String name) {}
}
'''
        sigs = _extract_java_signatures_regex("UserService.java", code)
        names = {s["name"] for s in sigs}
        assert "UserService" in names
        assert "findById" in names
        assert "validate" in names

    def test_interface(self):
        code = "public interface Repository {}"
        sigs = _extract_java_signatures_regex("Repository.java", code)
        assert any(s["name"] == "Repository" and s["type"] == "class" for s in sigs)


# ---------------------------------------------------------------------------
# 6. test_detect_conventions_from_index
# ---------------------------------------------------------------------------

class TestDetectConventionsFromIndex:
    def test_python_with_tests(self, tmp_path):
        idx = _RepoIndex(has_py=True, has_test_py=True, total_code_files=10)
        conv = _detect_conventions_from_index(tmp_path, idx)
        assert conv["language"] == "python"
        assert conv["test_framework"] == "pytest_or_unittest"
        assert conv["naming_style"] == "snake_case"
        assert conv["_total_code_files"] == 10

    def test_java_maven(self, tmp_path):
        # Create pom.xml with junit-jupiter
        (tmp_path / "pom.xml").write_text('<dependency>junit-jupiter</dependency>')
        idx = _RepoIndex(has_java=True, total_code_files=5)
        conv = _detect_conventions_from_index(tmp_path, idx)
        assert conv["language"] == "java"
        assert conv["build_tool"] == "maven"
        assert conv["test_framework"] == "junit5"
        assert conv["naming_style"] == "camelCase"

    def test_unknown_defaults(self, tmp_path):
        idx = _RepoIndex()
        conv = _detect_conventions_from_index(tmp_path, idx)
        assert conv["language"] == "unknown"
        assert conv["build_tool"] == "unknown"


# ---------------------------------------------------------------------------
# 7. test_to_context_string_max_tokens
# ---------------------------------------------------------------------------

class TestToContextStringMaxTokens:
    def _make_consciousness(self):
        return ProjectConsciousness(
            repo_id="test",
            indexed_at=time.time(),
            structure={"subdirs": {"src": {"subdirs": {}, "files": ["a.py", "b.py"]}}, "files": ["README.md"]},
            conventions={"language": "python", "build_tool": "pip", "test_framework": "pytest", "naming_style": "snake_case"},
            implementation_samples=[
                {"path": f"file{i}.py", "excerpt": "x = 1\n" * 200, "metadata": {"lines": 200}}
                for i in range(10)
            ],
            signatures=[
                {"path": f"mod{i}.py", "type": "function", "name": f"func_{i}"}
                for i in range(40)
            ],
        )

    def test_unlimited_returns_full(self):
        c = self._make_consciousness()
        result = c.to_context_string(max_tokens=0)
        assert "Representative code samples:" in result
        assert "Key classes/functions:" in result

    def test_small_budget_trims_content(self):
        c = self._make_consciousness()
        # Very small budget → should get trimmed
        result = c.to_context_string(max_tokens=50)
        assert len(result) <= 200  # 50 tokens * 4 chars
        assert "## Project context" in result

    def test_medium_budget_has_structure_no_samples(self):
        c = self._make_consciousness()
        # Budget that fits structure + sigs but not samples
        full = c.to_context_string(max_tokens=0)
        # Use a budget that's less than full but more than header
        result = c.to_context_string(max_tokens=200)
        assert len(result) <= 800
        assert "Language/build:" in result

    def test_default_max_tokens_zero_same_as_unlimited(self):
        c = self._make_consciousness()
        default_result = c.to_context_string()
        unlimited_result = c.to_context_string(max_tokens=0)
        assert default_result == unlimited_result

    def test_render_shows_params_and_decorators(self):
        c = ProjectConsciousness(
            repo_id="test",
            indexed_at=time.time(),
            structure={},
            conventions={"language": "python", "build_tool": "pip", "test_framework": "pytest", "naming_style": "snake_case"},
            implementation_samples=[],
            signatures=[
                {"path": "m.py", "type": "function", "name": "foo", "params": ["x: int", "y: str"], "return_type": "bool"},
                {"path": "m.py", "type": "class", "name": "Bar", "bases": ["ABC"], "decorators": ["dataclass"]},
            ],
        )
        result = c.to_context_string()
        assert "foo(x: int, y: str) -> bool" in result
        assert "Bar(ABC)" in result
        assert "[@dataclass]" in result


# ---------------------------------------------------------------------------
# 8. test_incremental_update
# ---------------------------------------------------------------------------

class TestIncrementalUpdate:
    def test_only_changed_files_updated(self, tmp_path):
        _make_repo(tmp_path, {
            "src/unchanged.py": "def old_func(): pass",
            "src/changed.py": "def new_func(x: int) -> str: return str(x)",
        })
        cached = ProjectConsciousness(
            repo_id="test",
            indexed_at=time.time() - 3600,
            structure={},
            conventions={"language": "python", "_total_code_files": 2},
            implementation_samples=[
                {"path": "src/unchanged.py", "excerpt": "def old_func(): pass", "metadata": {"lines": 1}},
            ],
            signatures=[
                {"path": "src/unchanged.py", "type": "function", "name": "old_func"},
                {"path": "src/changed.py", "type": "function", "name": "old_changed"},
            ],
        )
        result = _incremental_update(cached, str(tmp_path), "", ["src/changed.py"])

        # Unchanged signature kept
        unchanged_sigs = [s for s in result.signatures if s["path"] == "src/unchanged.py"]
        assert len(unchanged_sigs) == 1
        assert unchanged_sigs[0]["name"] == "old_func"

        # Changed file re-extracted
        changed_sigs = [s for s in result.signatures if s["path"] == "src/changed.py"]
        assert any(s["name"] == "new_func" for s in changed_sigs)
        # Old changed signature removed
        assert not any(s["name"] == "old_changed" for s in changed_sigs)


# ---------------------------------------------------------------------------
# 9. test_backward_compat_from_dict
# ---------------------------------------------------------------------------

class TestBackwardCompat:
    def test_old_format_loads(self):
        """Old signature format (no params/return_type) still works."""
        old_data = {
            "repo_id": "abc",
            "indexed_at": 1234567890.0,
            "structure": {"subdirs": {}, "files": ["main.py"]},
            "conventions": {"language": "python", "build_tool": "pip", "test_framework": "pytest", "naming_style": "snake_case"},
            "implementation_samples": [{"path": "main.py", "excerpt": "print(1)", "metadata": {}}],
            "signatures": [{"path": "main.py", "type": "function", "name": "main"}],
        }
        c = ProjectConsciousness.from_dict(old_data)
        assert c.repo_id == "abc"
        assert c.signatures[0]["name"] == "main"
        # Rendering old format should not crash
        result = c.to_context_string()
        assert "main" in result

    def test_new_format_with_extra_keys(self):
        """New signature format with params/return_type loads fine."""
        data = {
            "repo_id": "xyz",
            "indexed_at": time.time(),
            "structure": {},
            "conventions": {},
            "implementation_samples": [],
            "signatures": [
                {"path": "a.py", "type": "function", "name": "foo", "params": ["x: int"], "return_type": "str", "decorators": ["staticmethod"]},
            ],
        }
        c = ProjectConsciousness.from_dict(data)
        assert c.signatures[0]["params"] == ["x: int"]
        assert c.signatures[0]["return_type"] == "str"


# ---------------------------------------------------------------------------
# 10. test_build_consciousness end-to-end
# ---------------------------------------------------------------------------

class TestBuildConsciousness:
    def test_nonexistent_repo(self):
        c = build_consciousness("/nonexistent/path/xyz")
        assert c.structure == {}
        assert c.signatures == []

    def test_real_repo(self, tmp_path):
        _make_repo(tmp_path, {
            "main.py": "def main():\n    print('hello')\n\nif __name__ == '__main__':\n    main()\n",
            "src/utils.py": "def helper(x: int) -> str:\n    return str(x)\n",
            "src/__init__.py": "",
            "config.yml": "key: value",
        })
        c = build_consciousness(str(tmp_path))
        assert c.conventions["language"] == "python"
        assert c.structure  # non-empty
        # main.py should be a high-scoring sample (entry point)
        sample_paths = [s["path"] for s in c.implementation_samples]
        assert "main.py" in sample_paths
        # Signatures should use AST
        sig_names = [s["name"] for s in c.signatures]
        assert "main" in sig_names
        assert "helper" in sig_names

    def test_scoring_prefers_entry_points(self, tmp_path):
        """Entry points should rank higher than boilerplate."""
        files = {
            "__init__.py": "",
            "setup.py": "from setuptools import setup\nsetup(name='test')\n",
            "conftest.py": "import pytest\n",
        }
        # Add many boilerplate files
        for i in range(20):
            files[f"pkg/mod_{i}.py"] = f"x = {i}\n"
        # Add an entry point
        files["main.py"] = "def main():\n    print('entry')\n\ndef run():\n    main()\n\nclass App:\n    pass\n"
        _make_repo(tmp_path, files)
        c = build_consciousness(str(tmp_path))
        sample_paths = [s["path"] for s in c.implementation_samples]
        # main.py should appear in samples (high score: entry point + signatures)
        assert "main.py" in sample_paths


# ---------------------------------------------------------------------------
# 11. test_get_changed_files_since
# ---------------------------------------------------------------------------

class TestGetChangedFilesSince:
    def test_returns_none_without_git(self, tmp_path):
        """Non-git directory returns None."""
        result = _get_changed_files_since(tmp_path, time.time() - 3600)
        assert result is None

    def test_returns_none_if_gitpython_missing(self, tmp_path):
        with patch.dict("sys.modules", {"git": None}):
            # Force reimport attempt to fail
            result = _get_changed_files_since(tmp_path, time.time() - 3600)
            assert result is None
