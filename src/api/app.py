"""
FastAPI application — Code Autonomy REST API + WebSocket.

Run with:
    uvicorn src.api.app:app --reload --port 8000
"""

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.api.routes import ask, config, jira, repos, sessions, testing, traces
from src.data.database import init_db

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: initialize database and recover queued runs on startup."""
    init_db()
    logger.info("Database initialized")

    # Recover stale queued test runs from previous sessions
    _recover_queued_runs()

    yield


def _recover_queued_runs():
    """Pick up any test runs stuck in 'queued' status and re-launch them."""
    import asyncio
    from src.api.routes.testing import _execute_run_background, _executor
    from src.services.testing_service import TestingService

    try:
        from src.services.config_service import ConfigService
        config = ConfigService().load_config()
    except Exception:
        config = {}

    service = TestingService()
    queued = service.get_queued_runs()

    if not queued:
        return

    logger.info("Recovering %d queued test run(s)", len(queued))
    loop = asyncio.get_event_loop()
    for run in queued:
        logger.info("  Re-launching queued run %s (project=%s)", run.id, run.project_id)
        loop.run_in_executor(
            _executor, lambda rid=run.id: _execute_run_background(rid, config)
        )


app = FastAPI(
    title="Code Autonomy API",
    description="REST API for autonomous code generation — manage repos, sessions, traces, and config.",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow all origins for development, restrict in production
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Optional API key auth
# ---------------------------------------------------------------------------

API_KEY = os.environ.get("CODE_AUTONOMY_API_KEY", "")


@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    """Simple API key authentication (disabled when CODE_AUTONOMY_API_KEY is not set)."""
    if API_KEY and not request.url.path.startswith("/docs") and not request.url.path.startswith("/openapi"):
        key = request.headers.get("X-API-Key", "")
        if key != API_KEY:
            return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key"})
    return await call_next(request)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

app.include_router(repos.router, prefix="/api/repos")
app.include_router(sessions.router, prefix="/api/sessions")
app.include_router(config.router, prefix="/api/config")
app.include_router(traces.router, prefix="/api/traces")
app.include_router(ask.router, prefix="/api/ask")
app.include_router(jira.router, prefix="/api/jira")
app.include_router(testing.router, prefix="/api/testing")


@app.get("/api/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "version": "1.0.0"}
