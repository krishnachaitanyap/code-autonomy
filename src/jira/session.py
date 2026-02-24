"""
JiraSession: persistent state for a multi-story JIRA processing run.

Tracks which stories have been processed (success / failed / pending) so
that ``--jira --resume`` can skip completed stories and pick up where it
left off after a crash or manual interruption.

Storage: ``~/.code-autonomy/jira_sessions/{repo_id}.json``
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Per-story status values
STATUS_PENDING = "pending"
STATUS_IN_PROGRESS = "in_progress"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"


@dataclass
class StoryState:
    """Tracking state for a single JIRA story within a session."""

    key: str = ""
    summary: str = ""
    status: str = STATUS_PENDING  # pending | in_progress | success | failed
    files_changed: int = 0
    error: str = ""
    # Agent's working memory accumulated during processing (file notes, patterns, etc.)
    working_memory: dict[str, str] = field(default_factory=dict)


@dataclass
class JiraSession:
    """Persistent state for a multi-story JIRA run."""

    repo_id: str = ""
    created_at: str = ""
    stories: list[StoryState] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def pending_stories(self) -> list[StoryState]:
        """Stories not yet completed (pending or in_progress)."""
        return [s for s in self.stories if s.status in (STATUS_PENDING, STATUS_IN_PROGRESS)]

    def completed_stories(self) -> list[StoryState]:
        """Stories that finished (success or failed)."""
        return [s for s in self.stories if s.status in (STATUS_SUCCESS, STATUS_FAILED)]

    def succeeded_stories(self) -> list[StoryState]:
        """Stories that completed successfully."""
        return [s for s in self.stories if s.status == STATUS_SUCCESS]

    def resumable_stories(self) -> list[StoryState]:
        """Stories eligible for resume: pending, in_progress, or failed."""
        return [s for s in self.stories if s.status != STATUS_SUCCESS]

    def all_succeeded(self) -> bool:
        """True if every story in the session completed successfully."""
        return bool(self.stories) and all(s.status == STATUS_SUCCESS for s in self.stories)

    def get_story(self, key: str) -> Optional[StoryState]:
        for s in self.stories:
            if s.key == key:
                return s
        return None

    def mark_story(self, key: str, status: str, files_changed: int = 0, error: str = "") -> None:
        """Update the status of a story by key."""
        for s in self.stories:
            if s.key == key:
                s.status = status
                if files_changed:
                    s.files_changed = files_changed
                if error:
                    s.error = error
                return

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "repo_id": self.repo_id,
            "created_at": self.created_at,
            "stories": [
                {
                    "key": s.key,
                    "summary": s.summary,
                    "status": s.status,
                    "files_changed": s.files_changed,
                    "error": s.error,
                    "working_memory": s.working_memory,
                }
                for s in self.stories
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "JiraSession":
        return cls(
            repo_id=data.get("repo_id", ""),
            created_at=data.get("created_at", ""),
            stories=[
                StoryState(
                    key=s.get("key", ""),
                    summary=s.get("summary", ""),
                    status=s.get("status", STATUS_PENDING),
                    files_changed=s.get("files_changed", 0),
                    error=s.get("error", ""),
                    working_memory=s.get("working_memory", {}),
                )
                for s in data.get("stories", [])
            ],
        )


# ======================================================================
# Persistence
# ======================================================================

def _session_dir() -> Path:
    override = os.environ.get("CA_JIRA_SESSION_DIR", "")
    if override:
        return Path(override)
    return Path.home() / ".code-autonomy" / "jira_sessions"


def save_jira_session(session: JiraSession) -> None:
    """Persist a JiraSession to disk."""
    d = _session_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{session.repo_id}.json"
    path.write_text(json.dumps(session.to_dict(), indent=2), encoding="utf-8")
    logger.debug("Saved JIRA session to %s", path)


def load_jira_session(repo_id: str) -> Optional[JiraSession]:
    """Load a saved JiraSession from disk (returns None if not found)."""
    path = _session_dir() / f"{repo_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return JiraSession.from_dict(data)
    except Exception as exc:
        logger.warning("Failed to load JIRA session from %s: %s", path, exc)
        return None


def clear_jira_session(repo_id: str) -> None:
    """Remove a saved JiraSession from disk."""
    path = _session_dir() / f"{repo_id}.json"
    if path.exists():
        path.unlink()
        logger.debug("Cleared JIRA session: %s", path)


def create_jira_session(repo_id: str, stories: list[dict]) -> JiraSession:
    """Create a new JiraSession from a list of JIRA story dicts.

    Args:
        repo_id: Repository identifier (from compute_repo_id).
        stories: List of story dicts with 'key' and 'summary' fields
                 (as returned by fetch_agent_stories).
    """
    return JiraSession(
        repo_id=repo_id,
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        stories=[
            StoryState(key=s["key"], summary=s.get("summary", ""))
            for s in stories
        ],
    )
