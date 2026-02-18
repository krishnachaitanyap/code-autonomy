"""Tests for src/jira/session.py — JIRA session persistence for --resume."""

import json

import pytest

from src.jira.session import (
    JiraSession,
    StoryState,
    create_jira_session,
    save_jira_session,
    load_jira_session,
    clear_jira_session,
    STATUS_PENDING,
    STATUS_IN_PROGRESS,
    STATUS_SUCCESS,
    STATUS_FAILED,
)


# ---------------------------------------------------------------------------
# StoryState
# ---------------------------------------------------------------------------

class TestStoryState:
    def test_defaults(self):
        s = StoryState(key="SPS-1", summary="Do thing")
        assert s.status == STATUS_PENDING
        assert s.files_changed == 0
        assert s.error == ""
        assert s.working_memory == {}

    def test_working_memory_field(self):
        wm = {"file:src/main.py": "Entry point, handles CLI args", "pattern:logging": "Uses stdlib logging"}
        s = StoryState(key="SPS-1", summary="Do thing", working_memory=wm)
        assert s.working_memory == wm
        assert "file:src/main.py" in s.working_memory


# ---------------------------------------------------------------------------
# JiraSession — query helpers
# ---------------------------------------------------------------------------

class TestJiraSessionQueries:
    def _session(self) -> JiraSession:
        return JiraSession(
            repo_id="abc123",
            created_at="2025-01-01T00:00:00+00:00",
            stories=[
                StoryState(key="SPS-1", summary="A", status=STATUS_SUCCESS, files_changed=3),
                StoryState(key="SPS-2", summary="B", status=STATUS_FAILED, error="timeout"),
                StoryState(key="SPS-3", summary="C", status=STATUS_IN_PROGRESS),
                StoryState(key="SPS-4", summary="D", status=STATUS_PENDING),
            ],
        )

    def test_pending_stories(self):
        s = self._session()
        pending = s.pending_stories()
        assert len(pending) == 2
        keys = {p.key for p in pending}
        assert keys == {"SPS-3", "SPS-4"}

    def test_completed_stories(self):
        s = self._session()
        completed = s.completed_stories()
        assert len(completed) == 2
        keys = {c.key for c in completed}
        assert keys == {"SPS-1", "SPS-2"}

    def test_get_story_found(self):
        s = self._session()
        story = s.get_story("SPS-2")
        assert story is not None
        assert story.status == STATUS_FAILED

    def test_get_story_not_found(self):
        s = self._session()
        assert s.get_story("SPS-99") is None

    def test_mark_story(self):
        s = self._session()
        s.mark_story("SPS-4", STATUS_SUCCESS, files_changed=5)
        story = s.get_story("SPS-4")
        assert story.status == STATUS_SUCCESS
        assert story.files_changed == 5

    def test_mark_story_with_error(self):
        s = self._session()
        s.mark_story("SPS-3", STATUS_FAILED, error="out of turns")
        story = s.get_story("SPS-3")
        assert story.status == STATUS_FAILED
        assert story.error == "out of turns"

    def test_succeeded_stories(self):
        s = self._session()
        succeeded = s.succeeded_stories()
        assert len(succeeded) == 1
        assert succeeded[0].key == "SPS-1"

    def test_resumable_stories(self):
        s = self._session()
        resumable = s.resumable_stories()
        assert len(resumable) == 3  # failed + in_progress + pending
        keys = {r.key for r in resumable}
        assert keys == {"SPS-2", "SPS-3", "SPS-4"}

    def test_resumable_includes_failed(self):
        s = self._session()
        resumable = s.resumable_stories()
        failed = [r for r in resumable if r.status == STATUS_FAILED]
        assert len(failed) == 1
        assert failed[0].key == "SPS-2"

    def test_all_succeeded_true(self):
        s = JiraSession(stories=[
            StoryState(key="A", status=STATUS_SUCCESS),
            StoryState(key="B", status=STATUS_SUCCESS),
        ])
        assert s.all_succeeded() is True

    def test_all_succeeded_false_with_failure(self):
        s = self._session()
        assert s.all_succeeded() is False

    def test_all_succeeded_false_empty(self):
        s = JiraSession(stories=[])
        assert s.all_succeeded() is False


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

class TestSerialization:
    def test_round_trip(self):
        original = JiraSession(
            repo_id="abc123",
            created_at="2025-01-01T00:00:00+00:00",
            stories=[
                StoryState(key="SPS-1", summary="Story 1", status=STATUS_SUCCESS, files_changed=3),
                StoryState(key="SPS-2", summary="Story 2", status=STATUS_PENDING),
            ],
        )
        data = original.to_dict()
        restored = JiraSession.from_dict(data)

        assert restored.repo_id == original.repo_id
        assert restored.created_at == original.created_at
        assert len(restored.stories) == 2
        assert restored.stories[0].key == "SPS-1"
        assert restored.stories[0].status == STATUS_SUCCESS
        assert restored.stories[0].files_changed == 3
        assert restored.stories[1].status == STATUS_PENDING

    def test_round_trip_with_working_memory(self):
        wm = {"file:src/app.py": "Main app controller", "pattern:di": "Uses constructor injection"}
        original = JiraSession(
            repo_id="abc123",
            created_at="2025-01-01T00:00:00+00:00",
            stories=[
                StoryState(key="SPS-1", summary="Story 1", status=STATUS_SUCCESS,
                           files_changed=3, working_memory=wm),
                StoryState(key="SPS-2", summary="Story 2", status=STATUS_PENDING),
            ],
        )
        data = original.to_dict()
        restored = JiraSession.from_dict(data)

        assert restored.stories[0].working_memory == wm
        assert restored.stories[1].working_memory == {}

    def test_backward_compat_missing_working_memory(self):
        """Old session files without working_memory field should still load."""
        data = {
            "repo_id": "old",
            "created_at": "2025-01-01T00:00:00+00:00",
            "stories": [
                {"key": "S-1", "summary": "Old story", "status": "success",
                 "files_changed": 1, "error": ""},
            ],
        }
        restored = JiraSession.from_dict(data)
        assert restored.stories[0].working_memory == {}

    def test_empty_round_trip(self):
        original = JiraSession(repo_id="x", stories=[])
        data = original.to_dict()
        restored = JiraSession.from_dict(data)
        assert restored.stories == []

    def test_json_serializable(self):
        s = JiraSession(
            repo_id="test",
            stories=[StoryState(key="K-1", summary="S")],
        )
        text = json.dumps(s.to_dict())
        assert "K-1" in text


# ---------------------------------------------------------------------------
# create_jira_session
# ---------------------------------------------------------------------------

class TestCreateJiraSession:
    def test_creates_from_story_dicts(self):
        stories = [
            {"key": "SPS-1", "summary": "First", "description": "...", "acceptance_criteria": "..."},
            {"key": "SPS-2", "summary": "Second"},
        ]
        session = create_jira_session("repo123", stories)
        assert session.repo_id == "repo123"
        assert len(session.stories) == 2
        assert session.stories[0].key == "SPS-1"
        assert session.stories[0].summary == "First"
        assert all(s.status == STATUS_PENDING for s in session.stories)
        assert session.created_at  # should be set


# ---------------------------------------------------------------------------
# File persistence: save / load / clear
# ---------------------------------------------------------------------------

class TestFilePersistence:
    def test_save_and_load(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.jira.session._session_dir", lambda: tmp_path)

        session = JiraSession(
            repo_id="testrepo",
            created_at="2025-06-01T00:00:00+00:00",
            stories=[
                StoryState(key="K-1", summary="S1", status=STATUS_SUCCESS, files_changed=2),
                StoryState(key="K-2", summary="S2", status=STATUS_PENDING),
            ],
        )
        save_jira_session(session)

        # File should exist
        path = tmp_path / "testrepo.json"
        assert path.exists()

        # Load should return equivalent session
        loaded = load_jira_session("testrepo")
        assert loaded is not None
        assert loaded.repo_id == "testrepo"
        assert len(loaded.stories) == 2
        assert loaded.stories[0].status == STATUS_SUCCESS

    def test_load_missing_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.jira.session._session_dir", lambda: tmp_path)
        assert load_jira_session("nonexistent") is None

    def test_clear(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.jira.session._session_dir", lambda: tmp_path)

        session = JiraSession(repo_id="testrepo", stories=[])
        save_jira_session(session)
        assert (tmp_path / "testrepo.json").exists()

        clear_jira_session("testrepo")
        assert not (tmp_path / "testrepo.json").exists()

    def test_clear_nonexistent_no_error(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.jira.session._session_dir", lambda: tmp_path)
        clear_jira_session("nope")  # should not raise

    def test_load_corrupt_file_returns_none(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.jira.session._session_dir", lambda: tmp_path)
        (tmp_path / "bad.json").write_text("not json{{{")
        assert load_jira_session("bad") is None


# ---------------------------------------------------------------------------
# Integration: resume workflow
# ---------------------------------------------------------------------------

class TestResumeWorkflow:
    """Simulate the save-after-each-story / load-on-resume pattern."""

    def test_partial_completion_and_resume(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.jira.session._session_dir", lambda: tmp_path)

        # Create session with 3 stories
        stories = [
            {"key": "SPS-1", "summary": "S1"},
            {"key": "SPS-2", "summary": "S2"},
            {"key": "SPS-3", "summary": "S3"},
        ]
        session = create_jira_session("repo1", stories)
        save_jira_session(session)

        # Process story 1: mark in_progress then success
        session.mark_story("SPS-1", STATUS_IN_PROGRESS)
        save_jira_session(session)
        session.mark_story("SPS-1", STATUS_SUCCESS, files_changed=5)
        save_jira_session(session)

        # Process story 2: mark in_progress (simulating crash here)
        session.mark_story("SPS-2", STATUS_IN_PROGRESS)
        save_jira_session(session)

        # --- CRASH / RESTART ---

        # Load session on resume
        loaded = load_jira_session("repo1")
        assert loaded is not None

        # Should have 1 completed and 2 pending
        completed = loaded.completed_stories()
        pending = loaded.pending_stories()
        assert len(completed) == 1
        assert completed[0].key == "SPS-1"
        assert len(pending) == 2

        # SPS-2 should be in_progress (was interrupted)
        sps2 = loaded.get_story("SPS-2")
        assert sps2.status == STATUS_IN_PROGRESS

        # Pending keys for re-fetch
        pending_keys = {s.key for s in pending}
        assert pending_keys == {"SPS-2", "SPS-3"}

    def test_failed_stories_retried_on_resume(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.jira.session._session_dir", lambda: tmp_path)

        # Create session with 3 stories
        stories = [
            {"key": "SPS-1", "summary": "S1"},
            {"key": "SPS-2", "summary": "S2"},
            {"key": "SPS-3", "summary": "S3"},
        ]
        session = create_jira_session("repo2", stories)

        # SPS-1 succeeded, SPS-2 failed, SPS-3 never started
        session.mark_story("SPS-1", STATUS_SUCCESS, files_changed=3)
        session.mark_story("SPS-2", STATUS_FAILED, error="timeout")
        save_jira_session(session)

        # --- RESUME ---
        loaded = load_jira_session("repo2")
        assert loaded is not None

        # resumable_stories includes failed + pending (not succeeded)
        resumable = loaded.resumable_stories()
        assert len(resumable) == 2
        keys = {s.key for s in resumable}
        assert keys == {"SPS-2", "SPS-3"}

        # Session should NOT be cleared (not all succeeded)
        assert not loaded.all_succeeded()

        # Simulate: reset failed to pending for retry
        for s in resumable:
            if s.status == STATUS_FAILED:
                s.status = STATUS_PENDING
                s.error = ""
        save_jira_session(loaded)

        # Verify SPS-2 is now pending
        reloaded = load_jira_session("repo2")
        sps2 = reloaded.get_story("SPS-2")
        assert sps2.status == STATUS_PENDING
        assert sps2.error == ""

    def test_session_cleared_only_when_all_succeed(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.jira.session._session_dir", lambda: tmp_path)

        stories = [{"key": "SPS-1", "summary": "S1"}, {"key": "SPS-2", "summary": "S2"}]
        session = create_jira_session("repo3", stories)

        # Both succeed
        session.mark_story("SPS-1", STATUS_SUCCESS, files_changed=1)
        session.mark_story("SPS-2", STATUS_SUCCESS, files_changed=2)
        save_jira_session(session)

        assert session.all_succeeded()

        # Clear session
        clear_jira_session("repo3")
        assert load_jira_session("repo3") is None

    def test_session_persists_when_some_fail(self, tmp_path, monkeypatch):
        monkeypatch.setattr("src.jira.session._session_dir", lambda: tmp_path)

        stories = [{"key": "SPS-1", "summary": "S1"}, {"key": "SPS-2", "summary": "S2"}]
        session = create_jira_session("repo4", stories)

        session.mark_story("SPS-1", STATUS_SUCCESS, files_changed=1)
        session.mark_story("SPS-2", STATUS_FAILED, error="broke")
        save_jira_session(session)

        assert not session.all_succeeded()

        # Session file should still exist
        loaded = load_jira_session("repo4")
        assert loaded is not None
        assert len(loaded.resumable_stories()) == 1

    def test_working_memory_persists_across_stories(self, tmp_path, monkeypatch):
        """Working memory from completed stories should be available on resume."""
        monkeypatch.setattr("src.jira.session._session_dir", lambda: tmp_path)

        stories = [
            {"key": "SPS-1", "summary": "S1"},
            {"key": "SPS-2", "summary": "S2"},
            {"key": "SPS-3", "summary": "S3"},
        ]
        session = create_jira_session("repo5", stories)

        # Story 1 succeeds with working memory
        wm1 = {"file:src/auth.py": "Auth module, uses JWT", "pattern:config": "ConfigParser-based"}
        session.mark_story("SPS-1", STATUS_SUCCESS, files_changed=2)
        s1 = session.get_story("SPS-1")
        s1.working_memory = wm1

        # Story 2 fails but also has working memory
        wm2 = {"file:src/db.py": "SQLAlchemy ORM layer"}
        session.mark_story("SPS-2", STATUS_FAILED, error="timeout")
        s2 = session.get_story("SPS-2")
        s2.working_memory = wm2

        save_jira_session(session)

        # --- RESUME ---
        loaded = load_jira_session("repo5")
        assert loaded is not None

        # Accumulate working memory from ALL stories
        accumulated = {}
        for s in loaded.stories:
            if s.working_memory:
                accumulated.update(s.working_memory)

        # Should have WM from both succeeded and failed stories
        assert accumulated["file:src/auth.py"] == "Auth module, uses JWT"
        assert accumulated["file:src/db.py"] == "SQLAlchemy ORM layer"
        assert accumulated["pattern:config"] == "ConfigParser-based"
        assert len(accumulated) == 3

    def test_working_memory_preserved_on_failed_story_reset(self, tmp_path, monkeypatch):
        """Resetting a failed story to pending should preserve its working memory."""
        monkeypatch.setattr("src.jira.session._session_dir", lambda: tmp_path)

        stories = [{"key": "SPS-1", "summary": "S1"}]
        session = create_jira_session("repo6", stories)

        wm = {"file:src/main.py": "Entry point"}
        session.mark_story("SPS-1", STATUS_FAILED, error="timeout")
        s1 = session.get_story("SPS-1")
        s1.working_memory = wm
        save_jira_session(session)

        # Reset failed to pending (simulating resume logic)
        loaded = load_jira_session("repo6")
        for s in loaded.resumable_stories():
            if s.status == STATUS_FAILED:
                s.status = STATUS_PENDING
                s.error = ""
                # working_memory should NOT be cleared
        save_jira_session(loaded)

        reloaded = load_jira_session("repo6")
        s1 = reloaded.get_story("SPS-1")
        assert s1.status == STATUS_PENDING
        assert s1.error == ""
        assert s1.working_memory == wm  # preserved!
