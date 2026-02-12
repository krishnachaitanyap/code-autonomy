"""Tests for src.agent.gcc — Git Context Controller."""

import json
from pathlib import Path

import pytest

from src.agent.gcc import GCCController, GCCState
from src.agent.tools import _gcc_enabled


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def gcc(tmp_path):
    """Create a GCCController with a temp storage dir."""
    return GCCController(repo_id="test-repo-abc", storage_dir=str(tmp_path / "gcc"))


@pytest.fixture
def gcc_with_commits(gcc):
    """GCCController with a few commits already made."""
    gcc.commit("Initial exploration", {"project_overview": "Python project"}, milestone="explored")
    gcc.commit("Implemented feature A")
    gcc.commit("Tests passing", milestone="tests-pass")
    return gcc


# ---------------------------------------------------------------------------
# TestGCCCommit
# ---------------------------------------------------------------------------

class TestGCCCommit:
    def test_first_commit(self, gcc):
        result = gcc.commit("Initial exploration done")
        assert "c0001" in result
        assert "Initial exploration done" in result
        assert gcc._state.commit_counter == 1
        assert len(gcc._state.commits) == 1
        assert gcc._state.commits[0]["branch"] == "main"

    def test_commit_with_milestone(self, gcc):
        result = gcc.commit("Tests passing", milestone="all-green")
        assert "milestone: all-green" in result
        assert gcc._state.commits[0]["milestone"] == "all-green"

    def test_commit_captures_working_memory_snapshot(self, gcc):
        wm = {"project_overview": "Python Flask app", "key_patterns": "MVC"}
        gcc.commit("Explored project", wm)
        assert gcc._state.commits[0]["working_memory_snapshot"] == wm

    def test_commit_cap(self, gcc):
        """Commits are capped at _MAX_COMMITS."""
        for i in range(60):
            gcc.commit(f"commit {i}")
        assert len(gcc._state.commits) == GCCController._MAX_COMMITS
        # Oldest commits should be trimmed
        assert gcc._state.commits[0]["summary"] == "commit 10"
        assert gcc._state.commit_counter == 60


# ---------------------------------------------------------------------------
# TestGCCBranch
# ---------------------------------------------------------------------------

class TestGCCBranch:
    def test_create_branch(self, gcc):
        result = gcc.branch("alt-approach", "Try a different algorithm")
        assert "alt-approach" in result
        assert gcc._state.current_branch == "alt-approach"
        assert "alt-approach" in gcc._state.branches

    def test_duplicate_branch_rejected(self, gcc):
        gcc.branch("feature-x", "First try")
        result = gcc.branch("feature-x", "Second try")
        assert "Error" in result
        assert "already exists" in result

    def test_max_branches_cap(self, gcc):
        for i in range(GCCController._MAX_BRANCHES):
            gcc.branch(f"branch-{i}", f"purpose {i}")
        result = gcc.branch("one-too-many", "should fail")
        assert "Error" in result
        assert "Maximum" in result

    def test_branch_context_snapshot(self, gcc):
        gcc.commit("initial work", milestone="setup")
        gcc.branch("experiment", "try something new")
        branch_data = gcc._state.branches["experiment"]
        assert branch_data["parent_branch"] == "main"
        assert branch_data["context_snapshot"] != ""


# ---------------------------------------------------------------------------
# TestGCCMerge
# ---------------------------------------------------------------------------

class TestGCCMerge:
    def test_merge_normal(self, gcc):
        gcc.branch("feature", "add feature")
        gcc.commit("work on feature")
        result = gcc.merge("feature")
        assert "Merged" in result
        assert gcc._state.current_branch == "main"
        assert gcc._state.branches["feature"]["merged"] is True

    def test_merge_nonexistent(self, gcc):
        result = gcc.merge("ghost-branch")
        assert "Error" in result
        assert "does not exist" in result

    def test_double_merge_rejected(self, gcc):
        gcc.branch("feat", "test")
        gcc.merge("feat")
        result = gcc.merge("feat")
        assert "Error" in result
        assert "already been merged" in result

    def test_merge_creates_commit(self, gcc):
        gcc.branch("side", "experiment")
        count_before = gcc._state.commit_counter
        gcc.merge("side")
        assert gcc._state.commit_counter == count_before + 1
        last_commit = gcc._state.commits[-1]
        assert "Merge branch 'side'" in last_commit["summary"]
        assert last_commit["milestone"] == "merged:side"


# ---------------------------------------------------------------------------
# TestGCCContext
# ---------------------------------------------------------------------------

class TestGCCContext:
    def test_context_status(self, gcc_with_commits):
        result = gcc_with_commits.context("status")
        assert "Branch: main" in result
        assert "Commits: 3" in result

    def test_context_main(self, gcc_with_commits):
        result = gcc_with_commits.context("main")
        assert "explored" in result or "tests-pass" in result

    def test_context_commits(self, gcc_with_commits):
        result = gcc_with_commits.context("commits")
        assert "c0001" in result
        assert "c0002" in result
        assert "c0003" in result
        assert "Initial exploration" in result

    def test_context_branch(self, gcc):
        gcc.branch("exp", "experiment")
        result = gcc.context("branch", "exp")
        assert "experiment" in result
        assert "Parent: main" in result

    def test_context_branch_missing_param(self, gcc):
        result = gcc.context("branch", "")
        assert "Error" in result
        assert "required" in result

    def test_context_all(self, gcc_with_commits):
        result = gcc_with_commits.context("all")
        assert "Branch: main" in result
        assert "Main Context" in result
        assert "Commit Log" in result

    def test_context_invalid_scope(self, gcc):
        result = gcc.context("invalid_scope")
        assert "Error" in result
        assert "Unknown scope" in result


# ---------------------------------------------------------------------------
# TestGCCPersistence
# ---------------------------------------------------------------------------

class TestGCCPersistence:
    def test_save_and_reload(self, tmp_path):
        gcc1 = GCCController(repo_id="persist-test", storage_dir=str(tmp_path / "gcc"))
        gcc1.commit("first commit", {"note": "hello"}, milestone="m1")
        gcc1.branch("side-branch", "testing")
        gcc1.save()

        # Reload from same storage
        gcc2 = GCCController(repo_id="persist-test", storage_dir=str(tmp_path / "gcc"))
        assert gcc2._state.commit_counter == 1
        assert len(gcc2._state.commits) == 1
        assert gcc2._state.commits[0]["summary"] == "first commit"
        assert "side-branch" in gcc2._state.branches
        assert gcc2._state.current_branch == "side-branch"

    def test_corrupt_file_recovery(self, tmp_path):
        storage = tmp_path / "gcc" / "corrupt-repo"
        storage.mkdir(parents=True)
        (storage / "state.json").write_text("NOT JSON {{{", encoding="utf-8")

        gcc = GCCController(repo_id="corrupt-repo", storage_dir=str(tmp_path / "gcc"))
        # Should recover gracefully with fresh state
        assert gcc._state.commit_counter == 0
        assert gcc._state.current_branch == "main"
        assert len(gcc._state.commits) == 0


# ---------------------------------------------------------------------------
# TestGCCPromptInjection
# ---------------------------------------------------------------------------

class TestGCCPromptInjection:
    def test_empty_state_returns_empty(self, gcc):
        assert gcc.to_message_block() == ""

    def test_after_commits(self, gcc_with_commits):
        block = gcc_with_commits.to_message_block()
        assert "<gcc_context>" in block
        assert "</gcc_context>" in block
        assert "Branch: main" in block
        assert "Commits: 3" in block
        assert "c0003" in block

    def test_size_cap(self, gcc):
        # Make many commits with long summaries to test truncation
        for i in range(50):
            gcc.commit("x" * 200, milestone=f"milestone-{i}-" + "y" * 100)
        block = gcc.to_message_block()
        assert len(block) <= GCCController._MAX_CONTEXT_CHARS + 200  # some slack for tags


# ---------------------------------------------------------------------------
# TestGCCEnabled
# ---------------------------------------------------------------------------

class TestGCCEnabled:
    def test_default_off(self):
        assert _gcc_enabled(None) is False
        assert _gcc_enabled({}) is False

    def test_string_parsing(self):
        assert _gcc_enabled({"gcc_enabled": "true"}) is True
        assert _gcc_enabled({"gcc_enabled": "True"}) is True
        assert _gcc_enabled({"gcc_enabled": "1"}) is True
        assert _gcc_enabled({"gcc_enabled": "yes"}) is True
        assert _gcc_enabled({"gcc_enabled": "false"}) is False
        assert _gcc_enabled({"gcc_enabled": "0"}) is False
        assert _gcc_enabled({"gcc_enabled": "no"}) is False

    def test_bool_parsing(self):
        assert _gcc_enabled({"gcc_enabled": True}) is True
        assert _gcc_enabled({"gcc_enabled": False}) is False
