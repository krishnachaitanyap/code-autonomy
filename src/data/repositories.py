"""
Repository pattern — CRUD operations per entity.

Each repository class provides standard query + persistence methods
using the SQLAlchemy ORM models from ``models.py``.
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from src.data.models import (
    Checkpoint,
    ConfigProfile,
    Consciousness,
    GCCState,
    JiraSession,
    Knowledge,
    Repo,
    Session as SessionModel,
    Trace,
)


# ---------------------------------------------------------------------------
# RepoRepository
# ---------------------------------------------------------------------------

class RepoRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, repo_id: str) -> Optional[Repo]:
        return self.db.get(Repo, repo_id)

    def list_all(self) -> list[Repo]:
        return self.db.query(Repo).order_by(Repo.created_at.desc()).all()

    def create(self, repo_id: str, url: str = "", local_path: str = "", platform: str = "local") -> Repo:
        repo = Repo(id=repo_id, url=url, local_path=local_path, platform=platform)
        self.db.add(repo)
        self.db.flush()
        return repo

    def get_or_create(self, repo_id: str, url: str = "", local_path: str = "", platform: str = "local") -> Repo:
        repo = self.get_by_id(repo_id)
        if repo is None:
            repo = self.create(repo_id, url, local_path, platform)
        return repo

    def update(self, repo_id: str, **kwargs) -> Optional[Repo]:
        repo = self.get_by_id(repo_id)
        if repo is None:
            return None
        for key, value in kwargs.items():
            if hasattr(repo, key):
                setattr(repo, key, value)
        repo.updated_at = datetime.now(timezone.utc)
        self.db.flush()
        return repo

    def delete(self, repo_id: str) -> bool:
        repo = self.get_by_id(repo_id)
        if repo is None:
            return False
        self.db.delete(repo)
        self.db.flush()
        return True


# ---------------------------------------------------------------------------
# SessionRepository
# ---------------------------------------------------------------------------

class SessionRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, session_id: str) -> Optional[SessionModel]:
        return self.db.get(SessionModel, session_id)

    def list_by_repo(self, repo_id: str, limit: int = 50) -> list[SessionModel]:
        return (
            self.db.query(SessionModel)
            .filter(SessionModel.repo_id == repo_id)
            .order_by(SessionModel.created_at.desc())
            .limit(limit)
            .all()
        )

    def list_recent(self, limit: int = 50, status: Optional[str] = None) -> list[SessionModel]:
        q = self.db.query(SessionModel)
        if status:
            q = q.filter(SessionModel.status == status)
        return q.order_by(SessionModel.created_at.desc()).limit(limit).all()

    def create(
        self,
        repo_id: str,
        mode: str = "agent",
        requirements: str = "",
        session_id: Optional[str] = None,
    ) -> SessionModel:
        session = SessionModel(
            repo_id=repo_id,
            mode=mode,
            requirements=requirements,
            status="running",
        )
        if session_id:
            session.id = session_id
        self.db.add(session)
        self.db.flush()
        return session

    def update_status(
        self,
        session_id: str,
        status: str,
        result_summary: str = "",
        turns_used: int = 0,
        trace_id: str = "",
    ) -> Optional[SessionModel]:
        session = self.get_by_id(session_id)
        if session is None:
            return None
        session.status = status
        if result_summary:
            session.result_summary = result_summary
        if turns_used:
            session.turns_used = turns_used
        if trace_id:
            session.trace_id = trace_id
        if status in ("completed", "failed"):
            session.completed_at = datetime.now(timezone.utc)
        self.db.flush()
        return session


# ---------------------------------------------------------------------------
# CheckpointRepository
# ---------------------------------------------------------------------------

class CheckpointRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_latest_by_session(self, session_id: str) -> Optional[Checkpoint]:
        return (
            self.db.query(Checkpoint)
            .filter(Checkpoint.session_id == session_id)
            .order_by(Checkpoint.created_at.desc())
            .first()
        )

    def get_latest_by_repo(self, repo_id: str) -> Optional[Checkpoint]:
        return (
            self.db.query(Checkpoint)
            .filter(Checkpoint.repo_id == repo_id)
            .order_by(Checkpoint.created_at.desc())
            .first()
        )

    def save(self, checkpoint: Checkpoint) -> Checkpoint:
        self.db.add(checkpoint)
        self.db.flush()
        return checkpoint

    def clear_by_repo(self, repo_id: str) -> int:
        count = self.db.query(Checkpoint).filter(Checkpoint.repo_id == repo_id).delete()
        self.db.flush()
        return count


# ---------------------------------------------------------------------------
# TraceRepository
# ---------------------------------------------------------------------------

class TraceRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, trace_id: str) -> Optional[Trace]:
        return self.db.get(Trace, trace_id)

    def list_by_repo(self, repo_id: str, limit: int = 50) -> list[Trace]:
        return (
            self.db.query(Trace)
            .filter(Trace.repo_id == repo_id)
            .order_by(Trace.created_at.desc())
            .limit(limit)
            .all()
        )

    def list_recent(self, limit: int = 50) -> list[Trace]:
        return (
            self.db.query(Trace)
            .order_by(Trace.created_at.desc())
            .limit(limit)
            .all()
        )

    def save(self, trace: Trace) -> Trace:
        merged = self.db.merge(trace)
        self.db.flush()
        return merged


# ---------------------------------------------------------------------------
# KnowledgeRepository
# ---------------------------------------------------------------------------

class KnowledgeRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_repo(self, repo_id: str) -> list[Knowledge]:
        return (
            self.db.query(Knowledge)
            .filter(Knowledge.repo_id == repo_id)
            .order_by(Knowledge.updated_at.desc())
            .all()
        )

    def get_by_key(self, repo_id: str, key: str) -> Optional[Knowledge]:
        return (
            self.db.query(Knowledge)
            .filter(Knowledge.repo_id == repo_id, Knowledge.key == key)
            .first()
        )

    def save(self, knowledge: Knowledge) -> Knowledge:
        existing = self.get_by_key(knowledge.repo_id, knowledge.key)
        if existing:
            existing.content = knowledge.content
            if knowledge.source is not None:
                existing.source = knowledge.source
            existing.updated_at = datetime.now(timezone.utc)
            self.db.flush()
            return existing
        self.db.add(knowledge)
        self.db.flush()
        return knowledge

    def search(self, repo_id: str, query: str, limit: int = 10) -> list[Knowledge]:
        return (
            self.db.query(Knowledge)
            .filter(Knowledge.repo_id == repo_id, Knowledge.content.contains(query))
            .limit(limit)
            .all()
        )


# ---------------------------------------------------------------------------
# GCCRepository
# ---------------------------------------------------------------------------

class GCCRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_repo(self, repo_id: str) -> Optional[GCCState]:
        return self.db.get(GCCState, repo_id)

    def save(self, gcc_state: GCCState) -> GCCState:
        merged = self.db.merge(gcc_state)
        self.db.flush()
        return merged


# ---------------------------------------------------------------------------
# ConsciousnessRepository
# ---------------------------------------------------------------------------

class ConsciousnessRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_repo(self, repo_id: str) -> Optional[Consciousness]:
        return self.db.get(Consciousness, repo_id)

    def save(self, consciousness: Consciousness) -> Consciousness:
        merged = self.db.merge(consciousness)
        self.db.flush()
        return merged


# ---------------------------------------------------------------------------
# JiraSessionRepository
# ---------------------------------------------------------------------------

class JiraSessionRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_active_by_repo(self, repo_id: str) -> Optional[JiraSession]:
        return (
            self.db.query(JiraSession)
            .filter(JiraSession.repo_id == repo_id, JiraSession.status == "active")
            .order_by(JiraSession.created_at.desc())
            .first()
        )

    def get_by_id(self, session_id: str) -> Optional[JiraSession]:
        return self.db.get(JiraSession, session_id)

    def list_by_repo(self, repo_id: str, limit: int = 20) -> list[JiraSession]:
        return (
            self.db.query(JiraSession)
            .filter(JiraSession.repo_id == repo_id)
            .order_by(JiraSession.created_at.desc())
            .limit(limit)
            .all()
        )

    def save(self, jira_session: JiraSession) -> JiraSession:
        merged = self.db.merge(jira_session)
        self.db.flush()
        return merged

    def clear(self, repo_id: str) -> int:
        count = (
            self.db.query(JiraSession)
            .filter(JiraSession.repo_id == repo_id, JiraSession.status == "active")
            .delete()
        )
        self.db.flush()
        return count


# ---------------------------------------------------------------------------
# ConfigRepository
# ---------------------------------------------------------------------------

class ConfigRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_active(self) -> Optional[ConfigProfile]:
        return (
            self.db.query(ConfigProfile)
            .filter(ConfigProfile.is_active == True)  # noqa: E712
            .first()
        )

    def get_by_name(self, name: str) -> Optional[ConfigProfile]:
        return (
            self.db.query(ConfigProfile)
            .filter(ConfigProfile.name == name)
            .first()
        )

    def list_profiles(self) -> list[ConfigProfile]:
        return self.db.query(ConfigProfile).order_by(ConfigProfile.name).all()

    def save(self, profile: ConfigProfile) -> ConfigProfile:
        # Deactivate other profiles if this one is active
        if profile.is_active:
            self.db.query(ConfigProfile).filter(
                ConfigProfile.id != profile.id,
                ConfigProfile.is_active == True,  # noqa: E712
            ).update({"is_active": False})
        merged = self.db.merge(profile)
        self.db.flush()
        return merged
