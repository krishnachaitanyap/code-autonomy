"""
Workflow API routes — goal-driven orchestration (Workflow Mode).
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from src.api.schemas import (
    WorkflowCreate,
    WorkflowListResponse,
    WorkflowResponse,
    SubtaskSchema,
)
from src.services.orchestrator_service import OrchestratorService

logger = logging.getLogger(__name__)
router = APIRouter()

_service = OrchestratorService()
_executor = ThreadPoolExecutor(max_workers=2)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _workflow_to_response(wf) -> WorkflowResponse:
    subtasks = []
    for s in (wf.subtasks or []):
        subtasks.append(SubtaskSchema(
            index=s.get("index", 0),
            title=s.get("title", ""),
            description=s.get("description", ""),
            type=s.get("type", "agent"),
            status=s.get("status", "pending"),
            checkpoint=s.get("checkpoint", False),
            requirements=s.get("requirements", ""),
            result_summary=s.get("result_summary", ""),
            files_changed=s.get("files_changed", []),
            error=s.get("error"),
            started_at=s.get("started_at"),
            completed_at=s.get("completed_at"),
            attempts=s.get("attempts", 1),
            model_used=s.get("model_used", ""),
            tokens_used=s.get("tokens_used", 0),
        ))
    return WorkflowResponse(
        id=wf.id,
        repo_id=wf.repo_id,
        project_id=wf.project_id,
        goal=wf.goal,
        mode=wf.mode,
        status=wf.status,
        subtasks=subtasks,
        current_step=wf.current_step,
        progress_pct=wf.progress_pct,
        result_summary=wf.result_summary,
        artifacts=wf.artifacts or {},
        log=wf.log or [],
        token_budget=wf.token_budget or 0,
        total_tokens_used=wf.total_tokens_used or 0,
        created_at=str(wf.created_at) if wf.created_at else None,
        started_at=str(wf.started_at) if wf.started_at else None,
        completed_at=str(wf.completed_at) if wf.completed_at else None,
    )


def _execute_workflow_background(workflow_id: str, config: dict) -> None:
    """Background thread: decompose goal then execute workflow."""
    try:
        _service.execute_workflow(workflow_id, config)
    except Exception as exc:
        logger.error("Workflow %s background execution failed: %s", workflow_id, exc)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("", response_model=WorkflowResponse, status_code=201)
async def create_workflow(data: WorkflowCreate):
    """Create a new workflow: decompose goal into subtasks and start execution."""

    # Load config
    try:
        from src.services.config_service import ConfigService
        config = ConfigService().load_config()
    except Exception:
        config = {}

    # Create workflow record
    wf_config: dict = {}
    if data.branch:
        wf_config["branch"] = data.branch
    wf = _service.create_workflow(
        goal=data.goal,
        mode=data.mode,
        repo_id=data.repo_id,
        project_id=data.project_id,
        config=wf_config,
        token_budget=data.token_budget,
    )

    # Build repo context for decomposition
    repo_context: dict = {}
    if data.project_id:
        try:
            from src.services.testing_service import TestingService
            project = TestingService().get_project(data.project_id)
            if project:
                repo_context["language"] = project.language
                repo_context["framework"] = project.framework
                discovery = project.discovery_result or {}
                repo_context["endpoints"] = discovery.get("endpoints", [])
                repo_context["services"] = discovery.get("services", [])
        except Exception:
            pass

    # Decompose goal into subtasks
    subtasks = _service.decompose_goal(data.goal, data.mode, repo_context, config)

    # Save subtasks to workflow
    from src.data.database import get_session
    from src.data.models import Workflow
    with get_session() as db:
        workflow = db.get(Workflow, wf.id)
        if workflow:
            workflow.subtasks = subtasks
            workflow.status = "running"
            db.flush()
            db.expunge(workflow)
            wf = workflow

    # Launch background execution
    loop = asyncio.get_event_loop()
    loop.run_in_executor(
        _executor, lambda: _execute_workflow_background(wf.id, config)
    )

    return _workflow_to_response(wf)


@router.get("", response_model=WorkflowListResponse)
async def list_workflows(
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """List all workflows."""
    workflows = _service.list_workflows(status=status, limit=limit)
    return WorkflowListResponse(
        workflows=[_workflow_to_response(w) for w in workflows],
        total=len(workflows),
    )


@router.get("/{workflow_id}", response_model=WorkflowResponse)
async def get_workflow(workflow_id: str):
    """Get a workflow by ID with full details."""
    wf = _service.get_workflow(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return _workflow_to_response(wf)


@router.post("/{workflow_id}/resume", response_model=WorkflowResponse)
async def resume_workflow(workflow_id: str):
    """Resume a paused workflow from the next checkpoint."""
    wf = _service.get_workflow(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if wf.status != "paused":
        raise HTTPException(status_code=400, detail=f"Workflow is not paused (status={wf.status})")

    try:
        from src.services.config_service import ConfigService
        config = ConfigService().load_config()
    except Exception:
        config = {}

    # Launch resume in background
    loop = asyncio.get_event_loop()
    loop.run_in_executor(
        _executor,
        lambda: _service.resume_workflow(workflow_id, config),
    )

    # Return current state (will be "running" after resume starts)
    from src.data.database import get_session
    from src.data.models import Workflow
    with get_session() as db:
        workflow = db.get(Workflow, workflow_id)
        if workflow:
            workflow.status = "running"
            db.flush()
            db.expunge(workflow)
            return _workflow_to_response(workflow)

    return _workflow_to_response(wf)


@router.post("/{workflow_id}/cancel")
async def cancel_workflow(workflow_id: str):
    """Cancel a running or paused workflow."""
    wf = _service.cancel_workflow(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return {"status": "cancelled", "workflow_id": workflow_id}
