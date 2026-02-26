"""
SessionService — session lifecycle, querying, and resume.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


class SessionService:
    """Service for session management."""

    def get_session(self, session_id: str) -> Optional[dict]:
        """Get session details by ID.

        Returns:
            Dict with session data or None.
        """
        from src.data.database import get_session
        from src.data.repositories import SessionRepository

        with get_session() as db:
            session = SessionRepository(db).get_by_id(session_id)
            if session is None:
                return None
            return {
                "id": session.id,
                "repo_id": session.repo_id,
                "mode": session.mode,
                "status": session.status,
                "requirements": session.requirements,
                "result_summary": session.result_summary,
                "turns_used": session.turns_used,
                "trace_id": session.trace_id,
                "created_at": session.created_at.isoformat() if session.created_at else "",
                "completed_at": session.completed_at.isoformat() if session.completed_at else "",
            }

    def list_sessions(
        self,
        repo_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """List sessions with optional filters.

        Args:
            repo_id: Filter by repository.
            status: Filter by status (running, completed, failed, paused).
            limit: Max results.

        Returns:
            List of session summary dicts.
        """
        from src.data.database import get_session
        from src.data.repositories import SessionRepository

        with get_session() as db:
            repo = SessionRepository(db)
            if repo_id:
                sessions = repo.list_by_repo(repo_id, limit)
            else:
                sessions = repo.list_recent(limit, status=status)

            return [
                {
                    "id": s.id,
                    "repo_id": s.repo_id,
                    "mode": s.mode,
                    "status": s.status,
                    "turns_used": s.turns_used,
                    "result_summary": (s.result_summary or "")[:200],
                    "created_at": s.created_at.isoformat() if s.created_at else "",
                    "completed_at": s.completed_at.isoformat() if s.completed_at else "",
                }
                for s in sessions
            ]

    def cancel_session(self, session_id: str) -> bool:
        """Cancel a running session.

        Returns:
            True if session was found and cancelled.
        """
        from src.data.database import get_session
        from src.data.repositories import SessionRepository

        with get_session() as db:
            result = SessionRepository(db).update_status(session_id, "failed", "Cancelled by user")
            return result is not None

    def resume_session(self, session_id: str, config: dict) -> Optional["AgentResult"]:
        """Resume a paused/failed session from its checkpoint.

        Args:
            session_id: Session to resume.
            config: Full config dict.

        Returns:
            AgentResult or None if session not found or not resumable.
        """
        from src.data.database import get_session as get_db_session
        from src.data.repositories import CheckpointRepository, SessionRepository
        from src.services.agent_service import AgentService

        with get_db_session() as db:
            session = SessionRepository(db).get_by_id(session_id)
            if session is None:
                logger.warning("Session %s not found", session_id)
                return None

            if session.status not in ("paused", "failed"):
                logger.warning("Session %s is not resumable (status=%s)", session_id, session.status)
                return None

            checkpoint = CheckpointRepository(db).get_latest_by_session(session_id)
            repo_id = session.repo_id

        # Get repo path from database
        from src.data.database import get_session as get_db_session2
        from src.data.repositories import RepoRepository

        with get_db_session2() as db:
            repo = RepoRepository(db).get_by_id(repo_id)
            if repo is None:
                logger.warning("Repo %s not found", repo_id)
                return None
            repo_path = repo.local_path
            repo_url = repo.url

        agent_service = AgentService()
        return agent_service.run_agent(
            repo_path=repo_path,
            requirements=session.requirements,
            config=config,
            repo_url=repo_url,
            resume=True,
        )
