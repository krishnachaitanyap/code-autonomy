"""
TraceService — trace querying, aggregation, and export.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class TraceService:
    """Service for trace management and analysis."""

    def get_trace(self, trace_id: str) -> Optional[dict]:
        """Get full trace details by ID.

        Returns:
            Trace dict with spans and metrics, or None.
        """
        from src.data.database import get_session
        from src.data.repositories import TraceRepository

        with get_session() as db:
            trace = TraceRepository(db).get_by_id(trace_id)
            if trace is None:
                return None
            return {
                "id": trace.id,
                "session_id": trace.session_id,
                "repo_id": trace.repo_id,
                "model": trace.model,
                "success": trace.success,
                "turns_used": trace.turns_used,
                "duration_s": trace.duration_s,
                "total_tokens": trace.total_tokens,
                "total_cost": trace.total_cost,
                "files_changed": trace.files_changed or [],
                "summary": trace.summary,
                "spans": trace.spans or [],
                "metrics": trace.metrics or {},
                "created_at": trace.created_at.isoformat() if trace.created_at else "",
            }

    def list_traces(
        self,
        repo_id: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict]:
        """List traces with optional repo filter.

        Returns:
            List of trace summary dicts (without full span data).
        """
        from src.data.database import get_session
        from src.data.repositories import TraceRepository

        with get_session() as db:
            repo = TraceRepository(db)
            if repo_id:
                traces = repo.list_by_repo(repo_id, limit)
            else:
                traces = repo.list_recent(limit)

            return [
                {
                    "id": t.id,
                    "repo_id": t.repo_id,
                    "model": t.model,
                    "success": t.success,
                    "turns_used": t.turns_used,
                    "duration_s": t.duration_s,
                    "total_tokens": t.total_tokens,
                    "summary": (t.summary or "")[:200],
                    "created_at": t.created_at.isoformat() if t.created_at else "",
                }
                for t in traces
            ]

    def get_usage_stats(self, repo_id: Optional[str] = None) -> dict:
        """Compute aggregated usage stats.

        Returns:
            Dict with total_sessions, total_tokens, total_cost, etc.
        """
        from src.data.database import get_session
        from src.data.repositories import TraceRepository

        with get_session() as db:
            repo = TraceRepository(db)
            if repo_id:
                traces = repo.list_by_repo(repo_id, limit=1000)
            else:
                traces = repo.list_recent(limit=1000)

            total_tokens = sum(t.total_tokens or 0 for t in traces)
            total_cost = sum(t.total_cost or 0 for t in traces)
            total_duration = sum(t.duration_s or 0 for t in traces)
            success_count = sum(1 for t in traces if t.success)

            return {
                "total_sessions": len(traces),
                "successful_sessions": success_count,
                "failed_sessions": len(traces) - success_count,
                "total_tokens": total_tokens,
                "total_cost": total_cost,
                "total_duration_s": total_duration,
                "success_rate": success_count / len(traces) if traces else 0.0,
            }
