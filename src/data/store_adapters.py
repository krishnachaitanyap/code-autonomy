"""
DB-backed store adapters — same interface as existing file stores but using
the SQLAlchemy repository layer.

Factory functions select between file and database backends based on config.
"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.data.database import get_session
from src.data.models import (
    Checkpoint as CheckpointModel,
    Consciousness as ConsciousnessModel,
    Knowledge as KnowledgeModel,
    Repo as RepoModel,
    Trace as TraceModel,
)
from src.data.repositories import (
    CheckpointRepository,
    ConsciousnessRepository,
    KnowledgeRepository,
    RepoRepository,
    TraceRepository,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# DBTraceStore — matches FileTraceStore interface
# ---------------------------------------------------------------------------

class DBTraceStore:
    """Database-backed trace store. Same interface as FileTraceStore."""

    def save(self, trace: "AgentTrace") -> Path:
        """Save trace to database. Returns a synthetic path for compatibility."""
        from src.agent.tracing import AgentTrace

        with get_session() as db:
            # Ensure repo exists
            repo_repo = RepoRepository(db)
            repo_repo.get_or_create(trace.repo_id, url=trace.repo_url)

            trace_model = TraceModel(
                id=trace.trace_id,
                repo_id=trace.repo_id,
                spans=trace.spans,
                total_tokens=trace.metrics.get("total_tokens_est", 0),
                total_cost=0.0,
                duration_s=trace.total_duration_ms / 1000.0,
                model=trace.model,
                success=trace.success,
                turns_used=trace.turns_used,
                files_changed=trace.files_changed,
                summary=trace.summary,
                metrics=trace.metrics,
            )
            TraceRepository(db).save(trace_model)

        logger.info("Trace saved to database: %s", trace.trace_id)
        return Path(f"db://traces/{trace.trace_id}")

    def load(self, trace_id: str) -> Optional["AgentTrace"]:
        """Load a trace by ID from database."""
        from src.agent.tracing import AgentTrace

        with get_session() as db:
            model = TraceRepository(db).get_by_id(trace_id)
            if model is None:
                return None
            return AgentTrace(
                trace_id=model.id,
                repo_id=model.repo_id,
                started_at=model.created_at.isoformat() if model.created_at else "",
                ended_at="",
                total_duration_ms=model.duration_s * 1000.0,
                model=model.model,
                success=model.success,
                turns_used=model.turns_used,
                files_changed=model.files_changed or [],
                summary=model.summary,
                spans=model.spans or [],
                metrics=model.metrics or {},
            )

    def list_traces(self, repo_id: str = "", limit: int = 50) -> list[dict]:
        """List recent traces as summary dicts."""
        with get_session() as db:
            repo = TraceRepository(db)
            if repo_id:
                traces = repo.list_by_repo(repo_id, limit)
            else:
                traces = repo.list_recent(limit)
            return [
                {
                    "trace_id": t.id,
                    "repo_id": t.repo_id,
                    "started_at": t.created_at.isoformat() if t.created_at else "",
                    "model": t.model,
                    "success": t.success,
                    "turns_used": t.turns_used,
                    "summary": (t.summary or "")[:100],
                    "metrics": t.metrics or {},
                }
                for t in traces
            ]


# ---------------------------------------------------------------------------
# DBKnowledgeStore — matches FileKnowledgeStore interface
# ---------------------------------------------------------------------------

class DBKnowledgeStore:
    """Database-backed knowledge store. Same interface as FileKnowledgeStore."""

    def save(self, entry: "KnowledgeEntry") -> None:
        """Save a KnowledgeEntry to database (one row per structured field)."""
        from src.agent.knowledge import KnowledgeEntry

        with get_session() as db:
            repo_repo = RepoRepository(db)
            repo_repo.get_or_create(entry.repo_id, url=entry.repo_url)

            knowledge_repo = KnowledgeRepository(db)

            # Store structured fields as separate keyed entries
            fields = {
                "project_overview": entry.project_overview,
                "key_patterns": entry.key_patterns,
                "file_notes": entry.file_notes,
                "change_history": json.dumps(entry.change_history),
            }
            # Add custom notes
            for k, v in entry.notes.items():
                fields[k] = v

            for key, content in fields.items():
                if not content:
                    continue
                model = KnowledgeModel(
                    repo_id=entry.repo_id,
                    key=key,
                    content=content,
                    source="agent",
                )
                knowledge_repo.save(model)

        logger.info("Knowledge saved to database: %s", entry.repo_id)

    def load(self, repo_id: str) -> Optional["KnowledgeEntry"]:
        """Load a KnowledgeEntry from database."""
        from src.agent.knowledge import KnowledgeEntry

        with get_session() as db:
            entries = KnowledgeRepository(db).get_by_repo(repo_id)
            if not entries:
                return None

            result = KnowledgeEntry(repo_id=repo_id)
            for e in entries:
                if e.key == "project_overview":
                    result.project_overview = e.content
                elif e.key == "key_patterns":
                    result.key_patterns = e.content
                elif e.key == "file_notes":
                    result.file_notes = e.content
                elif e.key == "change_history":
                    try:
                        result.change_history = json.loads(e.content)
                    except (json.JSONDecodeError, TypeError):
                        pass
                else:
                    result.notes[e.key] = e.content
                if e.updated_at:
                    result.updated_at = e.updated_at.isoformat()

            return result


# ---------------------------------------------------------------------------
# DBCheckpointStore — matches FileCheckpointStore interface
# ---------------------------------------------------------------------------

class DBCheckpointStore:
    """Database-backed checkpoint store. Same interface as FileCheckpointStore."""

    def save(self, checkpoint: "CheckpointDataclass") -> None:
        """Save a checkpoint to database."""
        from src.agent.knowledge import Checkpoint as CheckpointDC

        with get_session() as db:
            repo_repo = RepoRepository(db)
            repo_repo.get_or_create(checkpoint.repo_id, url=checkpoint.repo_url)

            model = CheckpointModel(
                repo_id=checkpoint.repo_id,
                session_id=checkpoint.repo_id,  # Use repo_id as session proxy for legacy
                turns_used=checkpoint.turns_used,
                working_memory=checkpoint.working_memory,
                files_changed=checkpoint.files_changed,
                summary=checkpoint.summary,
                pending_work=checkpoint.pending_work,
                requirement_hash=checkpoint.requirement_hash,
            )
            CheckpointRepository(db).save(model)

        logger.info("Checkpoint saved to database: %s", checkpoint.repo_id)

    def load(self, repo_id: str) -> Optional["CheckpointDataclass"]:
        """Load the latest checkpoint for a repo from database."""
        from src.agent.knowledge import Checkpoint as CheckpointDC

        with get_session() as db:
            model = CheckpointRepository(db).get_latest_by_repo(repo_id)
            if model is None:
                return None
            return CheckpointDC(
                repo_id=model.repo_id,
                requirement_hash=model.requirement_hash,
                files_changed=model.files_changed or [],
                summary=model.summary,
                pending_work=model.pending_work,
                working_memory=model.working_memory or {},
                turns_used=model.turns_used,
                created_at=model.created_at.isoformat() if model.created_at else "",
            )

    def clear(self, repo_id: str) -> None:
        """Remove checkpoints for a repo from database."""
        with get_session() as db:
            CheckpointRepository(db).clear_by_repo(repo_id)
        logger.info("Checkpoint cleared from database: %s", repo_id)


# ---------------------------------------------------------------------------
# DBConsciousnessStore — matches ConsciousnessStore interface (ABC)
# ---------------------------------------------------------------------------

class DBConsciousnessStore:
    """Database-backed consciousness store. Same interface as FileConsciousnessStore."""

    def save(self, repo_id: str, data: "ProjectConsciousness") -> None:
        """Save a ProjectConsciousness to database."""
        with get_session() as db:
            repo_repo = RepoRepository(db)
            repo_repo.get_or_create(repo_id)

            model = ConsciousnessModel(
                repo_id=repo_id,
                structure_tree=json.dumps(data.structure) if isinstance(data.structure, dict) else str(data.structure),
                file_signatures=data.signatures,
                implementation_samples=data.implementation_samples,
                conventions=data.conventions,
                indexed_at=data.indexed_at,
            )
            ConsciousnessRepository(db).save(model)

        logger.info("Consciousness saved to database: %s", repo_id)

    def load(self, repo_id: str) -> Optional["ProjectConsciousness"]:
        """Load ProjectConsciousness from database."""
        from src.consciousness.core import ProjectConsciousness

        with get_session() as db:
            model = ConsciousnessRepository(db).get_by_repo(repo_id)
            if model is None:
                return None
            structure = model.structure_tree
            if isinstance(structure, str):
                try:
                    structure = json.loads(structure)
                except (json.JSONDecodeError, TypeError):
                    structure = {}

            return ProjectConsciousness(
                repo_id=model.repo_id,
                indexed_at=model.indexed_at,
                structure=structure,
                conventions=model.conventions or {},
                implementation_samples=model.implementation_samples or [],
                signatures=model.file_signatures or [],
            )

    def search(self, repo_id: str, query: str, top_k: int = 5) -> Optional[list[dict]]:
        """Database backend does not support semantic search."""
        return None
