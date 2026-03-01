"""API routes for JIRA session and run management."""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from src.api.schemas import (
    JiraRunCreate,
    JiraRunListResponse,
    JiraRunResponse,
    JiraSessionCreate,
    JiraSessionResponse,
)
from src.services.jira_run_service import JiraRunService
from src.services.jira_service import JiraService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["jira"])
jira_service = JiraService()
_jira_run_service = JiraRunService()
_jira_executor = ThreadPoolExecutor(max_workers=1)


# ---------------------------------------------------------------------------
# JIRA Sessions (legacy)
# ---------------------------------------------------------------------------

@router.post("/sessions", response_model=JiraSessionResponse)
async def start_jira_session(body: JiraSessionCreate):
    """Start a new JIRA processing session."""
    from src.data.database import get_session, init_db
    from src.data.repositories import RepoRepository

    init_db()
    with get_session() as db:
        repo = RepoRepository(db).get_by_id(body.repo_id)
        if repo is None:
            raise HTTPException(status_code=404, detail="Repository not found")
        repo_path = body.repo_path or repo.local_path
        repo_url = repo.url

    try:
        from src.services.config_service import ConfigService
        config = ConfigService().load_config()
    except Exception:
        raise HTTPException(status_code=500, detail="Could not load config")

    result = jira_service.start_jira_session(
        repo_path=repo_path, config=config, repo_url=repo_url,
    )

    return JiraSessionResponse(**result)


@router.get("/sessions/{repo_id}", response_model=JiraSessionResponse)
async def get_jira_session(repo_id: str):
    """Get JIRA session status for a repository."""
    result = jira_service.get_jira_session(repo_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No active JIRA session found")
    return JiraSessionResponse(**result)


# ---------------------------------------------------------------------------
# JIRA Runs — tracked JIRA-to-PR generation runs
# ---------------------------------------------------------------------------

def _jira_run_to_response(run) -> JiraRunResponse:
    return JiraRunResponse(
        id=run.id,
        repo_id=run.repo_id,
        status=run.status,
        agent_id=run.agent_id,
        jira_project=run.jira_project or "",
        total_stories=run.total_stories or 0,
        completed_stories=run.completed_stories or 0,
        succeeded_stories=run.succeeded_stories or 0,
        failed_stories=run.failed_stories or 0,
        progress_pct=run.progress_pct or 0.0,
        result_summary=run.result_summary or "",
        artifacts=run.artifacts or {},
        log=run.log or [],
        created_at=run.created_at.isoformat() if run.created_at else None,
        started_at=run.started_at.isoformat() if run.started_at else None,
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
    )


@router.get("/runs", response_model=JiraRunListResponse)
async def list_jira_runs(
    repo_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """List JIRA runs, optionally filtered by repo or status."""
    runs = _jira_run_service.list_runs(repo_id=repo_id, status=status, limit=limit)
    return JiraRunListResponse(
        runs=[_jira_run_to_response(r) for r in runs],
        total=len(runs),
    )


@router.post("/runs", response_model=JiraRunResponse, status_code=201)
async def create_jira_run(data: JiraRunCreate):
    """Start a new JIRA-to-PR run. Creates the record and launches background execution."""
    # Validate repo exists
    from src.data.database import get_session as get_db_session
    from src.data.models import Repo
    with get_db_session() as db:
        repo = db.get(Repo, data.repo_id)
        if not repo:
            raise HTTPException(status_code=404, detail="Repository not found")

    run = _jira_run_service.create_run(
        repo_id=data.repo_id,
        jira_project=data.jira_project,
    )

    # Load config and launch background execution
    try:
        from src.services.config_service import ConfigService
        config = ConfigService().load_config()
    except Exception:
        config = {}

    loop = asyncio.get_event_loop()
    loop.run_in_executor(
        _jira_executor, lambda: _execute_jira_run_background(run.id, config)
    )

    return _jira_run_to_response(run)


def _execute_jira_run_background(run_id: str, config: dict) -> None:
    """Background thread: execute the JIRA run pipeline."""
    try:
        _jira_run_service.execute_run(run_id, config)
    except Exception as exc:
        logger.error("JIRA run %s background execution failed: %s", run_id, exc)


@router.get("/runs/{run_id}", response_model=JiraRunResponse)
async def get_jira_run(run_id: str):
    """Get a JIRA run by ID with full details."""
    run = _jira_run_service.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="JIRA run not found")
    return _jira_run_to_response(run)


@router.post("/runs/{run_id}/cancel")
async def cancel_jira_run(run_id: str):
    """Cancel a running JIRA run."""
    run = _jira_run_service.cancel_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="JIRA run not found")
    return {"status": "cancelled", "run_id": run_id}


@router.post("/runs/{run_id}/retry", response_model=JiraRunResponse)
async def retry_jira_run(run_id: str):
    """Retry a failed JIRA run."""
    run = _jira_run_service.retry_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="JIRA run not found")

    try:
        from src.services.config_service import ConfigService
        config = ConfigService().load_config()
    except Exception:
        config = {}

    loop = asyncio.get_event_loop()
    loop.run_in_executor(
        _jira_executor, lambda: _execute_jira_run_background(run.id, config)
    )

    return _jira_run_to_response(run)
