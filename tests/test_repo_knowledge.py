"""Tests for repo knowledge file loading (src.agent.knowledge.load_repo_knowledge)."""

import logging
import tempfile
from pathlib import Path

import pytest

from src.agent.knowledge import (
    load_repo_knowledge,
    _load_single_file,
    _load_from_directory,
    _cap_length,
    _REPO_KNOWLEDGE_MAX_CHARS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_repo(tmp: Path, files: dict) -> Path:
    """Create a temp repo with given file layout. files = {rel_path: content}."""
    for rel, content in files.items():
        p = tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content, encoding="utf-8")
    return tmp


# ---------------------------------------------------------------------------
# TestNoKnowledgeFiles
# ---------------------------------------------------------------------------

class TestNoKnowledgeFiles:
    """Empty repo, nonexistent path, repo with only code — should return ''."""

    def test_empty_directory(self, tmp_path):
        assert load_repo_knowledge(str(tmp_path)) == ""

    def test_nonexistent_path(self):
        assert load_repo_knowledge("/nonexistent/repo/path/xyz") == ""

    def test_repo_with_only_code(self, tmp_path):
        _make_repo(tmp_path, {
            "src/main.py": "print('hello')",
            "README.md": "# My Project",
        })
        assert load_repo_knowledge(str(tmp_path)) == ""


# ---------------------------------------------------------------------------
# TestSingleFile
# ---------------------------------------------------------------------------

class TestSingleFile:
    """Tests for .code-autonomy.md and AGENT.md single-file loading."""

    def test_code_autonomy_md(self, tmp_path):
        _make_repo(tmp_path, {
            ".code-autonomy.md": "This repo is organized by app/env/region.",
        })
        result = load_repo_knowledge(str(tmp_path))
        assert "Repo Knowledge" in result
        assert ".code-autonomy.md" in result
        assert "organized by app/env/region" in result

    def test_agent_md_fallback(self, tmp_path):
        _make_repo(tmp_path, {
            "AGENT.md": "Use Kubernetes conventions here.",
        })
        result = load_repo_knowledge(str(tmp_path))
        assert "Repo Knowledge" in result
        assert "AGENT.md" in result
        assert "Kubernetes conventions" in result

    def test_code_autonomy_md_beats_agent_md(self, tmp_path):
        _make_repo(tmp_path, {
            ".code-autonomy.md": "Primary knowledge file.",
            "AGENT.md": "Fallback knowledge file.",
        })
        result = load_repo_knowledge(str(tmp_path))
        assert "Primary knowledge file" in result
        assert "Fallback knowledge file" not in result

    def test_empty_file_returns_empty(self, tmp_path):
        _make_repo(tmp_path, {
            ".code-autonomy.md": "",
        })
        assert load_repo_knowledge(str(tmp_path)) == ""

    def test_whitespace_only_file_returns_empty(self, tmp_path):
        _make_repo(tmp_path, {
            ".code-autonomy.md": "   \n\n  \t  \n",
        })
        assert load_repo_knowledge(str(tmp_path)) == ""


# ---------------------------------------------------------------------------
# TestDirectoryMode
# ---------------------------------------------------------------------------

class TestDirectoryMode:
    """Tests for .code-autonomy/ directory of .md files."""

    def test_multiple_md_files_concatenated_alphabetically(self, tmp_path):
        _make_repo(tmp_path, {
            ".code-autonomy/00-overview.md": "This is the overview.",
            ".code-autonomy/01-app-a.md": "App A details.",
            ".code-autonomy/02-app-b.md": "App B details.",
        })
        result = load_repo_knowledge(str(tmp_path))
        assert "Repo Knowledge" in result
        assert "00-overview.md" in result
        assert "01-app-a.md" in result
        assert "02-app-b.md" in result
        # Check alphabetical order
        idx_overview = result.index("00-overview.md")
        idx_a = result.index("01-app-a.md")
        idx_b = result.index("02-app-b.md")
        assert idx_overview < idx_a < idx_b

    def test_directory_beats_single_file(self, tmp_path):
        _make_repo(tmp_path, {
            ".code-autonomy/overview.md": "From directory.",
            ".code-autonomy.md": "From single file.",
        })
        result = load_repo_knowledge(str(tmp_path))
        assert "From directory" in result
        assert "From single file" not in result

    def test_empty_directory_falls_through(self, tmp_path):
        (tmp_path / ".code-autonomy").mkdir()
        _make_repo(tmp_path, {
            ".code-autonomy.md": "Fallback content.",
        })
        result = load_repo_knowledge(str(tmp_path))
        assert "Fallback content" in result

    def test_non_md_files_ignored(self, tmp_path):
        _make_repo(tmp_path, {
            ".code-autonomy/notes.md": "Valid content.",
            ".code-autonomy/data.json": '{"key": "value"}',
            ".code-autonomy/script.py": "print('hi')",
        })
        result = load_repo_knowledge(str(tmp_path))
        assert "Valid content" in result
        assert "data.json" not in result
        assert "script.py" not in result

    def test_empty_md_files_skipped(self, tmp_path):
        _make_repo(tmp_path, {
            ".code-autonomy/real.md": "Real content here.",
            ".code-autonomy/empty.md": "",
            ".code-autonomy/whitespace.md": "   \n  ",
        })
        result = load_repo_knowledge(str(tmp_path))
        assert "Real content here" in result
        assert "empty.md" not in result
        assert "whitespace.md" not in result

    def test_directory_all_empty_falls_through(self, tmp_path):
        _make_repo(tmp_path, {
            ".code-autonomy/empty.md": "",
            "AGENT.md": "Fallback via AGENT.md.",
        })
        result = load_repo_knowledge(str(tmp_path))
        assert "Fallback via AGENT.md" in result


# ---------------------------------------------------------------------------
# TestCharacterCap
# ---------------------------------------------------------------------------

class TestCharacterCap:
    """Tests for _cap_length truncation at 10k chars."""

    def test_under_cap_not_truncated(self):
        text = "x" * 5000
        assert _cap_length(text) == text

    def test_exactly_at_cap_not_truncated(self):
        text = "x" * _REPO_KNOWLEDGE_MAX_CHARS
        assert _cap_length(text) == text

    def test_over_cap_truncated(self):
        text = "x" * 15_000
        result = _cap_length(text)
        assert len(result) < 15_000
        assert "truncated" in result

    def test_truncation_warning_logged(self, caplog):
        text = "x" * 15_000
        with caplog.at_level(logging.WARNING, logger="src.agent.knowledge"):
            _cap_length(text)
        assert any("truncated" in r.message.lower() for r in caplog.records)

    def test_large_repo_knowledge_truncated(self, tmp_path):
        _make_repo(tmp_path, {
            ".code-autonomy.md": "A" * 15_000,
        })
        result = load_repo_knowledge(str(tmp_path))
        assert "truncated" in result
        # Result should be capped near the limit (plus truncation marker)
        assert len(result) < 15_000


# ---------------------------------------------------------------------------
# TestEncodingSafety
# ---------------------------------------------------------------------------

class TestEncodingSafety:
    """Non-UTF-8 bytes handled gracefully via errors='replace'."""

    def test_non_utf8_bytes_handled(self, tmp_path):
        # Write raw bytes including invalid UTF-8 sequences
        knowledge_file = tmp_path / ".code-autonomy.md"
        knowledge_file.write_bytes(b"Hello \xff\xfe world\n")
        result = load_repo_knowledge(str(tmp_path))
        assert "Repo Knowledge" in result
        # The replacement character should appear instead of crashing
        assert "Hello" in result
        assert "world" in result

    def test_latin1_encoded_file(self, tmp_path):
        knowledge_file = tmp_path / ".code-autonomy.md"
        knowledge_file.write_bytes("Héllo wörld café".encode("latin-1"))
        result = load_repo_knowledge(str(tmp_path))
        assert "Repo Knowledge" in result
        # Should not crash, content should be partially readable
        assert len(result) > 0
