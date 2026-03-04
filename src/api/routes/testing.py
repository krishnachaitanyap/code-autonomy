"""
Testing platform API routes — project onboarding, test runs, coverage,
data injection, custom steps, and chat.
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect

from src.api.schemas import (
    ChatRequest,
    ChatResponse,
    CoverageReportResponse,
    CustomStepCreate,
    CustomStepResponse,
    DataInjectionConfigCreate,
    DataInjectionConfigResponse,
    ReferenceLearnResponse,
    ReferenceRepoLearn,
    TestEvidenceResponse,
    TestProjectCreate,
    TestProjectListResponse,
    TestProjectResponse,
    TestRunCreate,
    TestRunListResponse,
    TestRunResponse,
    ChatMessageResponse,
)
from src.services.testing_service import TestingService

logger = logging.getLogger(__name__)
router = APIRouter()

_service = TestingService()
_executor = ThreadPoolExecutor(max_workers=2)


# ---------------------------------------------------------------------------
# Test Projects (Onboarding)
# ---------------------------------------------------------------------------

@router.get("/projects", response_model=TestProjectListResponse)
async def list_projects(
    status: Optional[str] = Query(None),
    repo_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """List all onboarded testing projects."""
    projects = _service.list_projects(status=status, repo_id=repo_id, limit=limit)
    return TestProjectListResponse(
        projects=[_project_to_response(p) for p in projects],
        total=len(projects),
    )


@router.post("/projects", response_model=TestProjectResponse, status_code=201)
async def create_project(data: TestProjectCreate):
    """Onboard a new repository for testing."""
    try:
        project = _service.create_project(
            name=data.name,
            repo_id=data.repo_id,
            repo_url=data.repo_url,
            local_path=data.local_path,
            language=data.language,
            framework=data.framework,
            testing_framework=data.testing_framework,
            branch=data.branch,
            config=data.config,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _project_to_response(project)


@router.get("/projects/{project_id}", response_model=TestProjectResponse)
async def get_project(project_id: str):
    """Get a testing project by ID."""
    project = _service.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return _project_to_response(project)


@router.post("/projects/{project_id}/discover", response_model=TestProjectResponse)
async def discover_project(project_id: str):
    """Trigger auto-discovery for a project (endpoints, services, DTOs)."""
    project = _service.run_discovery(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return _project_to_response(project)


@router.post("/projects/{project_id}/learn-reference", response_model=ReferenceLearnResponse)
async def learn_from_reference(project_id: str, data: ReferenceRepoLearn):
    """Clone a reference repo and extract BDD patterns, step defs, feature files, and Maven deps."""
    try:
        result = _service.learn_from_reference_repo(
            project_id=project_id,
            reference_repo_url=data.reference_repo_url,
            reference_branch=data.reference_branch,
            maven_deps=data.maven_deps,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Reference repo learning failed: {exc}")
    if result is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return ReferenceLearnResponse(
        steps_learned=result["steps_learned"],
        features_learned=result["features_learned"],
        maven_deps_found=result["maven_deps_found"],
        patterns=result["patterns"],
    )


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(project_id: str):
    """Remove a testing project."""
    deleted = _service.delete_project(project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Project not found")


# ---------------------------------------------------------------------------
# Test Runs (Agent Monitoring)
# ---------------------------------------------------------------------------

@router.get("/runs", response_model=TestRunListResponse)
async def list_runs(
    project_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """List test runs, optionally filtered by project or status."""
    runs = _service.list_runs(project_id=project_id, status=status, limit=limit)
    return TestRunListResponse(
        runs=[_run_to_response(r) for r in runs],
        total=len(runs),
    )


@router.post("/runs", response_model=TestRunResponse, status_code=201)
async def create_run(data: TestRunCreate):
    """Start a new test run (agent job).

    Creates the run record and immediately launches background execution.
    Connect to the WebSocket /runs/{run_id}/stream for live progress.
    """
    run = _service.create_run(
        project_id=data.project_id,
        run_type=data.run_type,
        target_scope=data.target_scope,
        strategy=data.strategy,
        config=data.config,
        branch=data.branch,
    )

    # Launch background execution
    try:
        from src.services.config_service import ConfigService
        config = ConfigService().load_config()
    except Exception:
        config = {}

    # Capture WebSocket callback on the main async thread (has the event loop)
    from src.api.websocket import session_manager
    progress_callback = session_manager.get_callback(run.id)

    loop = asyncio.get_running_loop()
    loop.run_in_executor(
        _executor, lambda: _execute_run_background(run.id, config, progress_callback)
    )

    return _run_to_response(run)


def _execute_run_background(run_id: str, config: dict, progress_callback=None) -> None:
    """Background thread: execute the test run pipeline."""
    try:
        _service.execute_run(run_id, config, progress_callback=progress_callback)
    except Exception as exc:
        logger.error("Test run %s background execution failed: %s", run_id, exc)
        # Notify frontend so it doesn't stay stuck on "queued"/"running"
        if progress_callback:
            progress_callback({"type": "error", "data": {"message": str(exc)}})


@router.get("/runs/{run_id}", response_model=TestRunResponse)
async def get_run(run_id: str):
    """Get a test run by ID with full details."""
    run = _service.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Test run not found")
    return _run_to_response(run)


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str):
    """Cancel a running test run."""
    run = _service.cancel_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Test run not found")
    return {"status": "cancelled", "run_id": run_id}


@router.post("/runs/{run_id}/retry", response_model=TestRunResponse)
async def retry_run(run_id: str):
    """Retry a queued, failed, or errored test run.

    Resets the run to queued state and re-launches background execution.
    """
    run = _service.retry_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Test run not found or not retryable")

    try:
        from src.services.config_service import ConfigService
        config = ConfigService().load_config()
    except Exception:
        config = {}

    # Capture WebSocket callback on the main async thread (has the event loop)
    from src.api.websocket import session_manager
    progress_callback = session_manager.get_callback(run.id)

    loop = asyncio.get_running_loop()
    loop.run_in_executor(
        _executor, lambda: _execute_run_background(run.id, config, progress_callback)
    )

    return _run_to_response(run)


@router.get("/runs/{run_id}/evidences", response_model=list[TestEvidenceResponse])
async def list_evidences(run_id: str):
    """Get all evidences (logs, reports, files) for a test run."""
    evidences = _service.list_evidences(run_id)
    return [
        TestEvidenceResponse(
            id=e.id,
            test_run_id=e.test_run_id,
            evidence_type=e.evidence_type,
            title=e.title,
            content=e.content,
            file_path=e.file_path,
            metadata=e.extra_data or {},
            created_at=str(e.created_at) if e.created_at else None,
        )
        for e in evidences
    ]


@router.websocket("/runs/{run_id}/stream")
async def run_stream(websocket: WebSocket, run_id: str):
    """WebSocket endpoint for live test run progress streaming.

    Clients receive JSON messages:
    - {"type": "progress", "run_id": "...", "progress": 40, "stage": "generating_tests"}
    - {"type": "complete", "run_id": "...", "status": "passed", "total_tests": 10}
    - {"type": "error", "run_id": "...", "error": "..."}
    """
    from src.api.websocket import session_manager
    await session_manager.connect(run_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await session_manager.disconnect(run_id, websocket)


# ---------------------------------------------------------------------------
# Coverage Reports
# ---------------------------------------------------------------------------

@router.get("/coverage/{project_id}", response_model=list[CoverageReportResponse])
async def list_coverage_reports(project_id: str, limit: int = Query(10, ge=1, le=50)):
    """Get coverage reports for a project."""
    reports = _service.list_coverage_reports(project_id, limit=limit)
    return [
        CoverageReportResponse(
            id=r.id,
            project_id=r.project_id,
            report_type=r.report_type,
            overall_pct=r.overall_pct,
            line_coverage=r.line_coverage,
            branch_coverage=r.branch_coverage,
            function_coverage=r.function_coverage,
            uncovered_areas=r.uncovered_areas or [],
            gaps=r.gaps or [],
            details=r.details or {},
            created_at=str(r.created_at) if r.created_at else None,
        )
        for r in reports
    ]


@router.post("/coverage/{project_id}/analyze", response_model=CoverageReportResponse)
async def analyze_coverage(project_id: str, branch: str = ""):
    """Trigger a coverage analysis for a project."""
    report = _service.analyze_coverage(project_id, branch=branch)
    if not report:
        raise HTTPException(status_code=404, detail="Project not found")
    return CoverageReportResponse(
        id=report.id,
        project_id=report.project_id,
        report_type=report.report_type,
        overall_pct=report.overall_pct,
        line_coverage=report.line_coverage,
        branch_coverage=report.branch_coverage,
        function_coverage=report.function_coverage,
        uncovered_areas=report.uncovered_areas or [],
        gaps=report.gaps or [],
        details=report.details or {},
        created_at=str(report.created_at) if report.created_at else None,
    )


# ---------------------------------------------------------------------------
# Data Injection
# ---------------------------------------------------------------------------

@router.get("/data-injection/{project_id}", response_model=list[DataInjectionConfigResponse])
async def list_data_injection_configs(project_id: str):
    """List data injection configurations for a project."""
    configs = _service.list_data_injection_configs(project_id)
    return [_di_to_response(c) for c in configs]


@router.post("/data-injection", response_model=DataInjectionConfigResponse, status_code=201)
async def create_data_injection_config(data: DataInjectionConfigCreate):
    """Create a new data injection configuration."""
    config = _service.create_data_injection_config(
        project_id=data.project_id,
        name=data.name,
        strategy=data.strategy,
        target_entity=data.target_entity,
        schema_definition=data.schema_definition,
        sample_data=data.sample_data,
        environment_rules=data.environment_rules,
    )
    return _di_to_response(config)


@router.delete("/data-injection/{config_id}", status_code=204)
async def delete_data_injection_config(config_id: str):
    """Delete a data injection configuration."""
    deleted = _service.delete_data_injection_config(config_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Config not found")


@router.post("/data-injection/{config_id}/generate-sample", response_model=DataInjectionConfigResponse)
async def generate_sample_data(config_id: str, count: int = Query(5, ge=1, le=100)):
    """Generate sample data for a data injection config."""
    config = _service.generate_sample_data(config_id, count=count)
    if not config:
        raise HTTPException(status_code=404, detail="Config not found")
    return _di_to_response(config)


# ---------------------------------------------------------------------------
# Custom Steps
# ---------------------------------------------------------------------------

@router.get("/custom-steps/{project_id}", response_model=list[CustomStepResponse])
async def list_custom_steps(project_id: str):
    """List custom step definitions for a project."""
    steps = _service.list_custom_steps(project_id)
    return [_step_to_response(s) for s in steps]


@router.post("/custom-steps", response_model=CustomStepResponse, status_code=201)
async def create_custom_step(data: CustomStepCreate):
    """Create a new custom step definition."""
    step = _service.create_custom_step(
        project_id=data.project_id,
        name=data.name,
        step_type=data.step_type,
        pattern=data.pattern,
        implementation=data.implementation,
        language=data.language,
        tags=data.tags,
    )
    return _step_to_response(step)


@router.put("/custom-steps/{step_id}", response_model=CustomStepResponse)
async def update_custom_step(step_id: str, data: CustomStepCreate):
    """Update an existing custom step."""
    step = _service.update_custom_step(
        step_id=step_id,
        name=data.name,
        step_type=data.step_type,
        pattern=data.pattern,
        implementation=data.implementation,
        language=data.language,
        tags=data.tags,
    )
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")
    return _step_to_response(step)


@router.delete("/custom-steps/{step_id}", status_code=204)
async def delete_custom_step(step_id: str):
    """Delete a custom step definition."""
    deleted = _service.delete_custom_step(step_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Step not found")


@router.post("/custom-steps/{project_id}/discover", response_model=list[CustomStepResponse])
async def discover_custom_steps(project_id: str):
    """Auto-discover custom step definitions from the project's codebase."""
    steps = _service.discover_custom_steps(project_id)
    return [_step_to_response(s) for s in steps]


# ---------------------------------------------------------------------------
# Chat (Natural Language Interaction)
# ---------------------------------------------------------------------------

@router.post("/chat", response_model=ChatResponse)
async def chat(data: ChatRequest):
    """Send a message in the testing chat and get an AI response."""
    reply, context = _service.chat(
        project_id=data.project_id,
        message=data.message,
    )
    return ChatResponse(
        reply=ChatMessageResponse(
            id=reply.id,
            project_id=reply.project_id,
            role=reply.role,
            content=reply.content,
            metadata=reply.extra_data or {},
            created_at=str(reply.created_at) if reply.created_at else None,
        ),
        context=context,
    )


@router.get("/chat/{project_id}/history", response_model=list[ChatMessageResponse])
async def chat_history(project_id: str, limit: int = Query(50, ge=1, le=200)):
    """Get chat history for a project."""
    messages = _service.get_chat_history(project_id, limit=limit)
    return [
        ChatMessageResponse(
            id=m.id,
            project_id=m.project_id,
            role=m.role,
            content=m.content,
            metadata=m.extra_data or {},
            created_at=str(m.created_at) if m.created_at else None,
        )
        for m in messages
    ]


# ---------------------------------------------------------------------------
# Dashboard stats
# ---------------------------------------------------------------------------

@router.get("/stats")
async def testing_stats():
    """Get aggregate testing statistics."""
    return _service.get_stats()


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def _project_to_response(p) -> TestProjectResponse:
    return TestProjectResponse(
        id=p.id,
        repo_id=p.repo_id,
        name=p.name,
        repo_url=p.repo_url,
        local_path=p.local_path,
        language=p.language,
        framework=p.framework,
        testing_framework=p.testing_framework,
        branch=p.branch,
        status=p.status,
        discovery_result=p.discovery_result or {},
        config=p.config or {},
        created_at=str(p.created_at) if p.created_at else None,
        updated_at=str(p.updated_at) if p.updated_at else None,
    )


def _run_to_response(r) -> TestRunResponse:
    return TestRunResponse(
        id=r.id,
        project_id=r.project_id,
        run_type=r.run_type,
        status=r.status,
        agent_id=r.agent_id,
        target_scope=r.target_scope,
        strategy=r.strategy,
        total_tests=r.total_tests,
        passed_tests=r.passed_tests,
        failed_tests=r.failed_tests,
        skipped_tests=r.skipped_tests,
        progress_pct=r.progress_pct,
        result_summary=r.result_summary,
        artifacts=r.artifacts or {},
        log=r.log or [],
        created_at=str(r.created_at) if r.created_at else None,
        started_at=str(r.started_at) if r.started_at else None,
        completed_at=str(r.completed_at) if r.completed_at else None,
    )


def _di_to_response(c) -> DataInjectionConfigResponse:
    return DataInjectionConfigResponse(
        id=c.id,
        project_id=c.project_id,
        name=c.name,
        strategy=c.strategy,
        target_entity=c.target_entity,
        schema_definition=c.schema_definition or {},
        sample_data=c.sample_data or [],
        environment_rules=c.environment_rules or {},
        is_active=c.is_active,
        created_at=str(c.created_at) if c.created_at else None,
        updated_at=str(c.updated_at) if c.updated_at else None,
    )


def _step_to_response(s) -> CustomStepResponse:
    return CustomStepResponse(
        id=s.id,
        project_id=s.project_id,
        name=s.name,
        step_type=s.step_type,
        pattern=s.pattern,
        implementation=s.implementation,
        language=s.language,
        tags=s.tags or [],
        source=s.source,
        is_active=s.is_active,
        created_at=str(s.created_at) if s.created_at else None,
        updated_at=str(s.updated_at) if s.updated_at else None,
    )
