"""Tests for src.agent.knowledge_generator — auto-generation of .code-autonomy.md."""

import tempfile
from pathlib import Path

import pytest

from src.agent.knowledge_generator import (
    _section_project_overview,
    _section_repository_layout,
    _section_coding_conventions,
    _section_testing,
    _section_important_files,
    _section_architecture_notes,
    _section_domain_context,
    _section_things_to_watch,
    _trim_to_budget,
    detect_existing_knowledge_file,
    write_knowledge_file,
    generate_knowledge_markdown,
    _BUDGET,
)
from src.consciousness.core import ProjectConsciousness


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_consciousness(
    structure=None,
    conventions=None,
    signatures=None,
    samples=None,
) -> ProjectConsciousness:
    """Create a ProjectConsciousness with test data."""
    return ProjectConsciousness(
        repo_id="test123",
        indexed_at=0.0,
        structure=structure or {},
        conventions=conventions or {},
        implementation_samples=samples or [],
        signatures=signatures or [],
    )


def _make_repo(tmp: Path, files: dict) -> Path:
    """Create a temp repo with given file layout."""
    for rel, content in files.items():
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp


# ---------------------------------------------------------------------------
# TestSectionProjectOverview
# ---------------------------------------------------------------------------

class TestSectionProjectOverview:
    """Tests for _section_project_overview."""

    def test_known_language_and_build(self):
        result = _section_project_overview({"language": "python", "build_tool": "pip"})
        assert "**Language:** python" in result
        assert "**Build tool:** pip" in result
        assert "<!-- TODO" not in result.split("Description")[0]

    def test_unknown_language(self):
        result = _section_project_overview({"language": "unknown", "build_tool": "maven"})
        assert "<!-- TODO" in result.split("Build tool")[0]
        assert "**Build tool:** maven" in result

    def test_unknown_build_tool(self):
        result = _section_project_overview({"language": "java", "build_tool": "unknown"})
        assert "**Language:** java" in result
        assert "<!-- TODO" in result.split("Description")[0].split("Build tool")[1]

    def test_both_unknown(self):
        result = _section_project_overview({"language": "unknown", "build_tool": "unknown"})
        assert result.count("<!-- TODO") >= 2  # language + build + description

    def test_empty_conventions(self):
        result = _section_project_overview({})
        assert "<!-- TODO" in result

    def test_description_always_has_todo(self):
        result = _section_project_overview({"language": "python", "build_tool": "pip"})
        assert "**Description:** <!-- TODO" in result


# ---------------------------------------------------------------------------
# TestSectionRepositoryLayout
# ---------------------------------------------------------------------------

class TestSectionRepositoryLayout:
    """Tests for _section_repository_layout."""

    def test_structure_rendered(self):
        structure = {
            "subdirs": {
                "src": {"subdirs": {}, "files": ["main.py"]},
                "tests": {"subdirs": {}, "files": ["test_main.py"]},
            },
            "files": ["README.md"],
        }
        result = _section_repository_layout(structure)
        assert "src/" in result
        assert "tests/" in result
        assert "main.py" in result
        assert "```" in result

    def test_empty_structure_shows_todo(self):
        result = _section_repository_layout({})
        assert "<!-- TODO" in result

    def test_none_structure_shows_todo(self):
        result = _section_repository_layout({"subdirs": {}, "files": []})
        assert "<!-- TODO" in result

    def test_large_tree_trimmed(self):
        # Create a structure that would exceed 1500 chars
        subdirs = {}
        for i in range(50):
            subdirs[f"very_long_directory_name_{i:03d}"] = {
                "subdirs": {},
                "files": [f"file_{j}.py" for j in range(10)],
            }
        structure = {"subdirs": subdirs, "files": []}
        result = _section_repository_layout(structure)
        # The tree portion (between ```) should be capped
        assert "trimmed" in result or len(result) < 2500


# ---------------------------------------------------------------------------
# TestSectionCodingConventions
# ---------------------------------------------------------------------------

class TestSectionCodingConventions:
    """Tests for _section_coding_conventions."""

    def test_naming_populated(self):
        result = _section_coding_conventions({"naming_style": "snake_case"})
        assert "**Naming style:** snake_case" in result

    def test_unknown_naming(self):
        result = _section_coding_conventions({"naming_style": "unknown"})
        assert "<!-- TODO" in result

    def test_formatting_always_todo(self):
        result = _section_coding_conventions({"naming_style": "camelCase"})
        assert "Formatting/linting" in result
        assert "<!-- TODO" in result

    def test_import_ordering_always_todo(self):
        result = _section_coding_conventions({})
        assert "Import ordering" in result
        assert "<!-- TODO" in result


# ---------------------------------------------------------------------------
# TestSectionTesting
# ---------------------------------------------------------------------------

class TestSectionTesting:
    """Tests for _section_testing."""

    def test_known_framework(self):
        result = _section_testing({"test_framework": "pytest"})
        assert "**Framework:** pytest" in result

    def test_unknown_framework(self):
        result = _section_testing({"test_framework": "unknown"})
        assert "<!-- TODO" in result

    def test_run_tests_always_todo(self):
        result = _section_testing({"test_framework": "junit5"})
        assert "**Run tests:** <!-- TODO" in result

    def test_coverage_always_todo(self):
        result = _section_testing({})
        assert "**Coverage:** <!-- TODO" in result


# ---------------------------------------------------------------------------
# TestSectionImportantFiles
# ---------------------------------------------------------------------------

class TestSectionImportantFiles:
    """Tests for _section_important_files."""

    def test_populated_from_samples_and_signatures(self):
        sigs = [
            {"path": "src/main.py", "type": "function", "name": "main"},
            {"path": "src/main.py", "type": "function", "name": "run"},
            {"path": "src/utils.py", "type": "class", "name": "Helper"},
        ]
        samples = [
            {"path": "src/main.py", "excerpt": "..."},
            {"path": "src/utils.py", "excerpt": "..."},
        ]
        result = _section_important_files(sigs, samples)
        assert "src/main.py" in result
        assert "main, run" in result
        assert "src/utils.py" in result
        assert "Helper" in result

    def test_empty_shows_todo_row(self):
        result = _section_important_files([], [])
        assert "<!-- TODO -->" in result

    def test_max_8_entries(self):
        samples = [{"path": f"file{i}.py", "excerpt": "..."} for i in range(15)]
        result = _section_important_files([], samples)
        # Should have header row + separator + at most 8 data rows
        table_lines = [l for l in result.split("\n") if l.startswith("|")]
        assert len(table_lines) <= 10  # header + separator + 8 rows

    def test_no_signatures_for_path_shows_todo(self):
        samples = [{"path": "src/app.py", "excerpt": "..."}]
        result = _section_important_files([], samples)
        assert "src/app.py" in result
        assert "<!-- TODO: describe -->" in result


# ---------------------------------------------------------------------------
# TestGenerateKnowledgeMarkdown
# ---------------------------------------------------------------------------

class TestGenerateKnowledgeMarkdown:
    """End-to-end tests for generate_knowledge_markdown."""

    def test_all_sections_present(self):
        c = _make_consciousness(
            conventions={"language": "python", "build_tool": "pip",
                         "test_framework": "pytest", "naming_style": "snake_case"},
            structure={"subdirs": {"src": {"subdirs": {}, "files": ["app.py"]}}, "files": []},
            signatures=[{"path": "src/app.py", "type": "function", "name": "main"}],
            samples=[{"path": "src/app.py", "excerpt": "def main(): pass"}],
        )
        result = generate_knowledge_markdown(c)
        assert "# Repo Knowledge" in result
        assert "## Project Overview" in result
        assert "## Repository Layout" in result
        assert "## Coding Conventions" in result
        assert "## Testing" in result
        assert "## Important Files" in result

    def test_within_char_budget(self):
        c = _make_consciousness(
            conventions={"language": "python", "build_tool": "pip",
                         "test_framework": "pytest", "naming_style": "snake_case"},
            structure={"subdirs": {"src": {"subdirs": {}, "files": ["app.py"]}}, "files": []},
        )
        result = generate_knowledge_markdown(c)
        assert len(result) <= _BUDGET

    def test_empty_consciousness(self):
        c = _make_consciousness()
        result = generate_knowledge_markdown(c)
        assert "# Repo Knowledge" in result
        assert "<!-- TODO" in result

    def test_auto_filled_data_present(self):
        c = _make_consciousness(
            conventions={"language": "java", "build_tool": "maven",
                         "test_framework": "junit5", "naming_style": "camelCase"},
        )
        result = generate_knowledge_markdown(c)
        assert "java" in result
        assert "maven" in result
        assert "junit5" in result
        assert "camelCase" in result

    def test_todo_markers_present(self):
        c = _make_consciousness(
            conventions={"language": "python", "build_tool": "pip",
                         "test_framework": "pytest", "naming_style": "snake_case"},
        )
        result = generate_knowledge_markdown(c)
        assert "<!-- TODO" in result


# ---------------------------------------------------------------------------
# TestTrimToBudget
# ---------------------------------------------------------------------------

class TestTrimToBudget:
    """Tests for _trim_to_budget."""

    def test_under_budget_unchanged(self):
        content = "Short content"
        assert _trim_to_budget(content, 1000) == content

    def test_removes_todo_sections_first(self):
        content = "\n\n".join([
            "# Header",
            "## Real Section\n\nSome actual data here.",
            "## Todo Section\n\n<!-- TODO: fill this in -->",
            "## Another Todo\n\n<!-- TODO: more stuff -->",
        ])
        result = _trim_to_budget(content, len(content) - 10)
        assert "Real Section" in result
        # At least one TODO section should be removed
        assert result.count("<!-- TODO") < content.count("<!-- TODO")

    def test_hard_truncate_when_no_todo_sections(self):
        content = "\n\n".join([
            "## Section 1\n\nData " * 200,
            "## Section 2\n\nMore data " * 200,
        ])
        result = _trim_to_budget(content, 500)
        assert len(result) <= 600  # 500 + truncation marker
        assert "trimmed to fit budget" in result

    def test_exactly_at_budget(self):
        content = "x" * 100
        assert _trim_to_budget(content, 100) == content

    def test_preserves_non_todo_sections(self):
        content = "\n\n".join([
            "# Header",
            "## Important\n\nKeep this data.",
            "## Placeholder\n\n<!-- TODO: optional -->",
        ])
        # Budget tight enough to need trimming
        budget = len("# Header") + len("\n\n") + len("## Important\n\nKeep this data.") + 20
        result = _trim_to_budget(content, budget)
        assert "Keep this data" in result


# ---------------------------------------------------------------------------
# TestDetectExistingKnowledgeFile
# ---------------------------------------------------------------------------

class TestDetectExistingKnowledgeFile:
    """Tests for detect_existing_knowledge_file."""

    def test_detects_code_autonomy_dir(self, tmp_path):
        _make_repo(tmp_path, {
            ".code-autonomy/overview.md": "content",
        })
        result = detect_existing_knowledge_file(str(tmp_path))
        assert result is not None
        assert ".code-autonomy" in result

    def test_detects_code_autonomy_md(self, tmp_path):
        _make_repo(tmp_path, {
            ".code-autonomy.md": "content",
        })
        result = detect_existing_knowledge_file(str(tmp_path))
        assert result is not None
        assert ".code-autonomy.md" in result

    def test_detects_agent_md(self, tmp_path):
        _make_repo(tmp_path, {
            "AGENT.md": "content",
        })
        result = detect_existing_knowledge_file(str(tmp_path))
        assert result is not None
        assert "AGENT.md" in result

    def test_returns_none_when_absent(self, tmp_path):
        _make_repo(tmp_path, {
            "src/main.py": "print('hello')",
        })
        assert detect_existing_knowledge_file(str(tmp_path)) is None

    def test_nonexistent_path(self):
        assert detect_existing_knowledge_file("/nonexistent/path/xyz") is None

    def test_empty_dir_no_md_files(self, tmp_path):
        (tmp_path / ".code-autonomy").mkdir()
        assert detect_existing_knowledge_file(str(tmp_path)) is None

    def test_priority_dir_over_file(self, tmp_path):
        _make_repo(tmp_path, {
            ".code-autonomy/overview.md": "from dir",
            ".code-autonomy.md": "from file",
        })
        result = detect_existing_knowledge_file(str(tmp_path))
        assert result is not None
        # Directory should win — result should end with the directory path
        assert result.endswith(".code-autonomy")

    def test_priority_file_over_agent_md(self, tmp_path):
        _make_repo(tmp_path, {
            ".code-autonomy.md": "from file",
            "AGENT.md": "from agent",
        })
        result = detect_existing_knowledge_file(str(tmp_path))
        assert result is not None
        assert ".code-autonomy.md" in result


# ---------------------------------------------------------------------------
# TestWriteKnowledgeFile
# ---------------------------------------------------------------------------

class TestWriteKnowledgeFile:
    """Tests for write_knowledge_file."""

    def test_writes_correct_content(self, tmp_path):
        content = "# Test Knowledge\n\nHello world."
        path = write_knowledge_file(str(tmp_path), content)
        written = Path(path).read_text(encoding="utf-8")
        assert written == content

    def test_returns_absolute_path(self, tmp_path):
        path = write_knowledge_file(str(tmp_path), "test")
        assert Path(path).is_absolute()
        assert ".code-autonomy.md" in path

    def test_utf8_encoded(self, tmp_path):
        content = "Héllo wörld café"
        path = write_knowledge_file(str(tmp_path), content)
        written = Path(path).read_bytes()
        assert content.encode("utf-8") == written

    def test_overwrites_existing(self, tmp_path):
        _make_repo(tmp_path, {".code-autonomy.md": "old content"})
        path = write_knowledge_file(str(tmp_path), "new content")
        assert Path(path).read_text(encoding="utf-8") == "new content"
