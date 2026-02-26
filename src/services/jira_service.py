"""
JiraService — JIRA session management wrapping existing JIRA mode.
"""

import logging
from typing import Optional

from src.agent.knowledge import compute_repo_id

logger = logging.getLogger(__name__)


class JiraService:
    """Service for JIRA integration."""

    def start_jira_session(
        self,
        repo_path: str,
        config: dict,
        repo_url: str = "",
    ) -> dict:
        """Start a new JIRA processing session.

        Fetches stories from JIRA and creates a session for tracking.

        Args:
            repo_path: Path to the repository.
            config: Full config dict with [jira] section.
            repo_url: Remote URL (optional).

        Returns:
            Dict with session info and story list.
        """
        from src.jira.client import fetch_agent_stories, get_jira_token
        from src.jira.session import create_jira_session, save_jira_session

        repo_id = compute_repo_id(repo_path, repo_url)

        # Authenticate
        token = get_jira_token(config)

        # Fetch stories
        stories = fetch_agent_stories(config, token=token)
        if not stories:
            return {"repo_id": repo_id, "stories": [], "message": "No stories found"}

        # Create and persist session
        session = create_jira_session(repo_id, stories)
        save_jira_session(session)

        # Also persist to database if available
        try:
            from src.data.database import get_session, init_db
            from src.data.models import JiraSession as JiraSessionModel
            from src.data.repositories import JiraSessionRepository, RepoRepository

            init_db()
            with get_session() as db:
                RepoRepository(db).get_or_create(repo_id, url=repo_url, local_path=repo_path)
                model = JiraSessionModel(
                    repo_id=repo_id,
                    status="active",
                    stories=session.to_dict()["stories"],
                    config=config.get("jira", {}),
                )
                JiraSessionRepository(db).save(model)
        except Exception as exc:
            logger.debug("Could not persist JIRA session to database: %s", exc)

        return {
            "repo_id": repo_id,
            "stories": [{"key": s["key"], "summary": s.get("summary", "")} for s in stories],
            "message": f"Created session with {len(stories)} stories",
        }

    def get_jira_session(self, repo_id: str) -> Optional[dict]:
        """Get the active JIRA session for a repo.

        Returns:
            Dict with session data or None.
        """
        from src.jira.session import load_jira_session

        session = load_jira_session(repo_id)
        if session is None:
            return None

        return {
            "repo_id": session.repo_id,
            "created_at": session.created_at,
            "stories": [
                {
                    "key": s.key,
                    "summary": s.summary,
                    "status": s.status,
                    "files_changed": s.files_changed,
                    "error": s.error,
                }
                for s in session.stories
            ],
            "total": len(session.stories),
            "completed": len(session.completed_stories()),
            "succeeded": len(session.succeeded_stories()),
            "pending": len(session.pending_stories()),
        }

    def resume_jira_session(
        self,
        repo_path: str,
        config: dict,
        repo_url: str = "",
    ) -> Optional[dict]:
        """Resume a previously started JIRA session.

        Returns:
            Dict with session status or None if no session to resume.
        """
        from src.jira.session import load_jira_session

        repo_id = compute_repo_id(repo_path, repo_url)
        session = load_jira_session(repo_id)

        if session is None or not session.resumable_stories():
            return None

        return {
            "repo_id": repo_id,
            "resumable_stories": len(session.resumable_stories()),
            "completed_stories": len(session.completed_stories()),
            "message": f"{len(session.resumable_stories())} stories remaining",
        }
