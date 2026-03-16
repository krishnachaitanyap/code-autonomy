"""
Migration platform API routes — project CRUD, analysis, recipes,
capacity modeling, roadmap generation, and execution.
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect

from src.api.schemas import (
    CapacityTargetUpdate,
    CustomRecipeCreate,
    CustomRecipeResponse,
    CustomRecipeUpdate,
    MigrationProjectCreate,
    MigrationProjectListResponse,
    MigrationProjectResponse,
    MigrationRecipeResponse,
    MigrationRunListResponse,
    MigrationRunResponse,
    RecipeSelectionRequest,
)
from src.services.migration_service import MigrationService

logger = logging.getLogger(__name__)
router = APIRouter()

_service = MigrationService()
_executor = ThreadPoolExecutor(max_workers=2)


# ---------------------------------------------------------------------------
# Migration Projects
# ---------------------------------------------------------------------------

@router.get("/projects", response_model=MigrationProjectListResponse)
async def list_projects(
    status: Optional[str] = Query(None),
    repo_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """List all migration projects."""
    projects = _service.list_projects(status=status, repo_id=repo_id, limit=limit)
    return MigrationProjectListResponse(
        projects=[_project_to_response(p) for p in projects],
        total=len(projects),
    )


@router.post("/projects", response_model=MigrationProjectResponse, status_code=201)
async def create_project(data: MigrationProjectCreate):
    """Create a new migration project."""
    try:
        project = _service.create_project(
            name=data.name,
            migration_mode=data.migration_mode,
            source_repo_url=data.source_repo_url,
            source_local_path=data.source_local_path,
            source_branch=data.source_branch,
            reference_repo_url=data.reference_repo_url,
            reference_local_path=data.reference_local_path,
            reference_branch=data.reference_branch,
            reference_folders=data.reference_folders,
            config=data.config,
            source_db=data.source_db,
            destination_db=data.destination_db,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _project_to_response(project)


@router.get("/projects/{project_id}", response_model=MigrationProjectResponse)
async def get_project(project_id: str):
    """Get a migration project by ID."""
    project = _service.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Migration project not found")
    return _project_to_response(project)


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(project_id: str):
    """Delete a migration project."""
    deleted = _service.delete_project(project_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Migration project not found")


@router.post("/projects/{project_id}/analyze", response_model=MigrationProjectResponse)
async def analyze_project(project_id: str):
    """Trigger async stack analysis for both source and reference repos."""
    project = _service.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Migration project not found")

    try:
        from src.services.config_service import ConfigService
        config = ConfigService().load_config()
    except Exception:
        config = {}

    loop = asyncio.get_running_loop()
    loop.run_in_executor(
        _executor, lambda: _analyze_background(project_id, config)
    )

    # Return immediately with current state (status will be "analyzing")
    project = _service.get_project(project_id)
    return _project_to_response(project)


def _analyze_background(project_id: str, config: dict) -> None:
    """Background thread: run migration analysis."""
    try:
        _service.analyze_project(project_id, config)
    except Exception as exc:
        logger.error("Migration analysis %s failed: %s", project_id, exc)


# ---------------------------------------------------------------------------
# Database Connection Test
# ---------------------------------------------------------------------------

@router.post("/projects/{project_id}/test-connection")
async def test_connection(project_id: str, target: str = Query("source")):
    """Test database connectivity for source or destination."""
    project = _service.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Migration project not found")

    config = project.config or {}
    db_key = "source_db" if target == "source" else "destination_db"
    db_config = config.get(db_key)
    if not db_config:
        raise HTTPException(status_code=400, detail=f"No {target} database configured")

    try:
        url = _service._build_connection_url(db_config)
        from sqlalchemy import create_engine, text
        engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 10})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return {"status": "ok", "target": target, "message": "Connection successful"}
    except Exception as exc:
        return {"status": "error", "target": target, "message": str(exc)}


# ---------------------------------------------------------------------------
# Capacity
# ---------------------------------------------------------------------------

@router.put("/projects/{project_id}/capacity", response_model=MigrationProjectResponse)
async def update_capacity_target(project_id: str, data: CapacityTargetUpdate):
    """Update the target capacity model for a project."""
    project = _service.update_capacity_target(project_id, data.capacity_target)
    if not project:
        raise HTTPException(status_code=404, detail="Migration project not found")
    return _project_to_response(project)


# ---------------------------------------------------------------------------
# Recipes
# ---------------------------------------------------------------------------

@router.get("/recipes", response_model=list[MigrationRecipeResponse])
async def list_recipes():
    """List all available migration recipes (built-in + custom)."""
    from src.services.migration_recipes import get_all_recipes
    from src.data.models import CustomMigrationRecipe
    from src.data.db import get_session

    # Built-in recipes
    builtin = get_all_recipes()
    results = [
        MigrationRecipeResponse(
            id=r.id,
            name=r.name,
            category=r.category,
            description=r.description,
            priority=r.priority,
            tags=r.tags,
            prerequisites=r.prerequisites,
            agent_instructions=r.agent_instructions,
        )
        for r in builtin
    ]

    # Custom recipes from DB
    with get_session() as db:
        customs = db.query(CustomMigrationRecipe).all()
        for c in customs:
            results.append(MigrationRecipeResponse(
                id=c.id,
                name=c.name,
                category=c.category,
                description=c.description,
                priority=c.priority,
                tags=c.tags or [],
                prerequisites=c.prerequisites or [],
                agent_instructions=c.agent_instructions or "",
            ))

    return results


@router.post("/recipes/custom", response_model=CustomRecipeResponse)
async def create_custom_recipe(data: CustomRecipeCreate):
    """Create a custom migration recipe."""
    from src.data.models import CustomMigrationRecipe
    from src.data.db import get_session

    recipe = CustomMigrationRecipe(
        name=data.name,
        category=data.category,
        description=data.description,
        priority=data.priority,
        tags=data.tags,
        prerequisites=data.prerequisites,
        agent_instructions=data.agent_instructions,
        source_framework=data.source_framework,
        target_framework=data.target_framework,
    )
    with get_session() as db:
        db.add(recipe)
        db.flush()
        db.refresh(recipe)
        return CustomRecipeResponse(
            id=recipe.id,
            name=recipe.name,
            category=recipe.category,
            description=recipe.description,
            priority=recipe.priority,
            tags=recipe.tags or [],
            prerequisites=recipe.prerequisites or [],
            agent_instructions=recipe.agent_instructions or "",
            source_framework=recipe.source_framework or "",
            target_framework=recipe.target_framework or "",
        )


@router.put("/recipes/custom/{recipe_id}", response_model=CustomRecipeResponse)
async def update_custom_recipe(recipe_id: str, data: CustomRecipeUpdate):
    """Update a custom migration recipe."""
    from src.data.models import CustomMigrationRecipe
    from src.data.db import get_session

    with get_session() as db:
        recipe = db.get(CustomMigrationRecipe, recipe_id)
        if not recipe:
            raise HTTPException(status_code=404, detail="Custom recipe not found")
        for field, value in data.model_dump(exclude_none=True).items():
            setattr(recipe, field, value)
        db.flush()
        db.refresh(recipe)
        return CustomRecipeResponse(
            id=recipe.id,
            name=recipe.name,
            category=recipe.category,
            description=recipe.description,
            priority=recipe.priority,
            tags=recipe.tags or [],
            prerequisites=recipe.prerequisites or [],
            agent_instructions=recipe.agent_instructions or "",
            source_framework=recipe.source_framework or "",
            target_framework=recipe.target_framework or "",
        )


@router.delete("/recipes/custom/{recipe_id}", status_code=204)
async def delete_custom_recipe(recipe_id: str):
    """Delete a custom migration recipe."""
    from src.data.models import CustomMigrationRecipe
    from src.data.db import get_session

    with get_session() as db:
        recipe = db.get(CustomMigrationRecipe, recipe_id)
        if not recipe:
            raise HTTPException(status_code=404, detail="Custom recipe not found")
        db.delete(recipe)


@router.get("/projects/{project_id}/recipes", response_model=list[MigrationRecipeResponse])
async def get_recommended_recipes(project_id: str):
    """Get recommended recipes for a project based on gap analysis."""
    recipes = _service.get_recommended_recipes(project_id)
    if not recipes and not _service.get_project(project_id):
        raise HTTPException(status_code=404, detail="Migration project not found")
    return [MigrationRecipeResponse(**r) for r in recipes]


@router.put("/projects/{project_id}/recipes", response_model=MigrationProjectResponse)
async def set_selected_recipes(project_id: str, data: RecipeSelectionRequest):
    """Set the selected recipes for a project."""
    project = _service.select_recipes(project_id, data.recipe_ids)
    if not project:
        raise HTTPException(status_code=404, detail="Migration project not found")
    return _project_to_response(project)


# ---------------------------------------------------------------------------
# Roadmap
# ---------------------------------------------------------------------------

@router.post("/projects/{project_id}/roadmap", response_model=MigrationRunResponse)
async def generate_roadmap(project_id: str):
    """Generate a migration roadmap and create a MigrationRun."""
    run = _service.generate_roadmap(project_id)
    if not run:
        raise HTTPException(status_code=404, detail="Migration project not found")
    return _run_to_response(run)


# ---------------------------------------------------------------------------
# Migration Runs
# ---------------------------------------------------------------------------

@router.get("/runs", response_model=MigrationRunListResponse)
async def list_runs(
    project_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
):
    """List migration runs."""
    runs = _service.list_runs(project_id=project_id, status=status, limit=limit)
    return MigrationRunListResponse(
        runs=[_run_to_response(r) for r in runs],
        total=len(runs),
    )


@router.get("/runs/{run_id}", response_model=MigrationRunResponse)
async def get_run(run_id: str):
    """Get a migration run by ID."""
    run = _service.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Migration run not found")
    return _run_to_response(run)


@router.post("/runs/{run_id}/execute", response_model=MigrationRunResponse)
async def execute_run(
    run_id: str,
    target_branch: str = Query(""),
    target_repo_url: str = Query(""),
):
    """Execute all migration steps (Phase 3)."""
    run = _service.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Migration run not found")
    if run.status not in ("queued", "paused"):
        raise HTTPException(status_code=400, detail=f"Run is not executable (status={run.status})")

    # Store target info in run artifacts before executing
    if target_branch or target_repo_url:
        _service.update_run_target(run_id, target_repo_url, target_branch)

    try:
        from src.services.config_service import ConfigService
        config = ConfigService().load_config()
    except Exception:
        config = {}

    loop = asyncio.get_running_loop()
    loop.run_in_executor(
        _executor, lambda: _execute_run_background(run_id, config)
    )

    return _run_to_response(run)


@router.post("/runs/{run_id}/execute-step", response_model=MigrationRunResponse)
async def execute_single_step(
    run_id: str,
    step_index: int = Query(...),
    target_branch: str = Query(""),
    target_repo_url: str = Query(""),
):
    """Execute a single migration step (Phase 3)."""
    run = _service.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Migration run not found")

    # Store target info in run artifacts before executing
    if target_branch or target_repo_url:
        _service.update_run_target(run_id, target_repo_url, target_branch)

    try:
        from src.services.config_service import ConfigService
        config = ConfigService().load_config()
    except Exception:
        config = {}

    loop = asyncio.get_running_loop()
    loop.run_in_executor(
        _executor, lambda: _execute_step_background(run_id, step_index, config)
    )

    return _run_to_response(run)


def _execute_run_background(run_id: str, config: dict) -> None:
    """Background thread: execute migration run."""
    try:
        _service.execute_run(run_id, config)
    except Exception as exc:
        logger.error("Migration run %s execution failed: %s", run_id, exc)


def _execute_step_background(run_id: str, step_index: int, config: dict) -> None:
    """Background thread: execute single migration step."""
    try:
        _service.execute_single_step(run_id, step_index, config)
    except Exception as exc:
        logger.error("Migration step %d in run %s failed: %s", step_index, run_id, exc)


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str):
    """Cancel a running migration."""
    run = _service.cancel_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Migration run not found or not cancellable")
    return {"status": "cancelled", "run_id": run_id}


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@router.get("/stats")
async def migration_stats():
    """Get aggregate migration statistics."""
    return _service.get_stats()


# ---------------------------------------------------------------------------
# WebSocket — live progress streaming
# ---------------------------------------------------------------------------

@router.websocket("/runs/{run_id}/stream")
async def run_stream(websocket: WebSocket, run_id: str):
    """WebSocket endpoint for live migration run progress streaming."""
    await websocket.accept()
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def _project_to_response(p) -> MigrationProjectResponse:
    return MigrationProjectResponse(
        id=p.id,
        repo_id=p.repo_id,
        name=p.name,
        migration_mode=p.migration_mode or "migration",
        source_repo_url=p.source_repo_url or "",
        source_local_path=p.source_local_path or "",
        source_branch=p.source_branch or "main",
        reference_repo_url=p.reference_repo_url or "",
        reference_local_path=p.reference_local_path or "",
        reference_branch=p.reference_branch or "main",
        reference_folders=p.reference_folders or [],
        status=p.status,
        source_profile=p.source_profile or {},
        reference_profile=p.reference_profile or {},
        gap_analysis=p.gap_analysis or {},
        improvement_analysis=p.improvement_analysis or {},
        capacity_current=p.capacity_current or {},
        capacity_target=p.capacity_target or {},
        selected_recipes=p.selected_recipes or [],
        config=p.config or {},
        created_at=str(p.created_at) if p.created_at else None,
        updated_at=str(p.updated_at) if p.updated_at else None,
    )


def _run_to_response(r) -> MigrationRunResponse:
    return MigrationRunResponse(
        id=r.id,
        project_id=r.project_id,
        status=r.status,
        roadmap_steps=r.roadmap_steps or [],
        current_step=r.current_step,
        progress_pct=r.progress_pct,
        log=r.log or [],
        result_summary=r.result_summary or "",
        artifacts=r.artifacts or {},
        total_tokens_used=r.total_tokens_used,
        created_at=str(r.created_at) if r.created_at else None,
        started_at=str(r.started_at) if r.started_at else None,
        completed_at=str(r.completed_at) if r.completed_at else None,
    )
