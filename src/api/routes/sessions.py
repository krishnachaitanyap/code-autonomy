"""API routes for session management including WebSocket streaming."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from src.api.schemas import SessionCreate, SessionListResponse, SessionResponse
from src.api.websocket import session_manager
from src.services.agent_service import AgentService
from src.services.session_service import SessionService

router = APIRouter(tags=["sessions"])
session_service = SessionService()
agent_service = AgentService()

# Thread pool for running synchronous agent code
_executor = ThreadPoolExecutor(max_workers=4)


@router.get("", response_model=SessionListResponse)
async def list_sessions(repo_id: Optional[str] = None, status: Optional[str] = None, limit: int = 50):
    """List sessions with optional filters."""
    sessions = session_service.list_sessions(repo_id=repo_id, status=status, limit=limit)
    return SessionListResponse(
        sessions=[SessionResponse(**s) for s in sessions],
        total=len(sessions),
    )


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str):
    """Get session details."""
    session = session_service.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionResponse(**session)


@router.post("", response_model=SessionResponse)
async def create_session(body: SessionCreate):
    """Start a new agent/plan/ask session.

    Runs the agent in a background thread and returns the session immediately.
    Connect to the WebSocket endpoint to receive live progress.
    """
    from src.data.database import get_session, init_db
    from src.data.repositories import RepoRepository

    init_db()

    # Verify repo exists
    with get_session() as db:
        repo = RepoRepository(db).get_by_id(body.repo_id)
        if repo is None:
            raise HTTPException(status_code=404, detail="Repository not found")
        repo_path = repo.local_path
        repo_url = repo.url

    # Load config
    try:
        from src.services.config_service import ConfigService
        config = ConfigService().load_config()
        # Apply any overrides
        for section, values in body.config_overrides.items():
            if section in config and isinstance(config[section], dict):
                config[section].update(values)
    except Exception:
        raise HTTPException(status_code=500, detail="Could not load config")

    # Validate that an LLM API key is available
    ai_key = config.get("ai", {}).get("api_key", "")
    if not ai_key:
        raise HTTPException(
            status_code=400,
            detail="No LLM API key configured. Set OPENAI_API_KEY (or ANTHROPIC_API_KEY) in your environment.",
        )

    # Create session record immediately
    session_id = agent_service._create_session(body.repo_id, body.mode, body.requirements)
    if session_id is None:
        raise HTTPException(status_code=500, detail="Could not create session")

    # Run agent in background thread
    def _run():
        try:
            if body.mode == "agent":
                agent_service.run_agent(
                    repo_path=repo_path, requirements=body.requirements,
                    config=config, repo_url=repo_url,
                    progress_callback=session_manager.get_callback(session_id) if session_manager.has_clients(session_id) else None,
                )
            elif body.mode == "plan":
                agent_service.run_plan(
                    repo_path=repo_path, requirements=body.requirements,
                    config=config, repo_url=repo_url,
                    progress_callback=session_manager.get_callback(session_id) if session_manager.has_clients(session_id) else None,
                )
            elif body.mode == "ask":
                agent_service.run_ask(
                    repo_path=repo_path, question=body.requirements,
                    config=config, repo_url=repo_url,
                    progress_callback=session_manager.get_callback(session_id) if session_manager.has_clients(session_id) else None,
                )
        except Exception as exc:
            agent_service._update_session(session_id, "failed", str(exc))

    loop = asyncio.get_event_loop()
    loop.run_in_executor(_executor, _run)

    return SessionResponse(
        id=session_id,
        repo_id=body.repo_id,
        mode=body.mode,
        status="running",
        requirements=body.requirements[:200],
    )


@router.post("/{session_id}/cancel")
async def cancel_session(session_id: str):
    """Cancel a running session."""
    success = session_service.cancel_session(session_id)
    if not success:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "cancelled"}


@router.post("/{session_id}/resume", response_model=SessionResponse)
async def resume_session(session_id: str):
    """Resume a paused/failed session from checkpoint."""
    try:
        from src.services.config_service import ConfigService
        config = ConfigService().load_config()
    except Exception:
        raise HTTPException(status_code=500, detail="Could not load config")

    result = session_service.resume_session(session_id, config)
    if result is None:
        raise HTTPException(status_code=404, detail="Session not found or not resumable")

    session = session_service.get_session(session_id)
    return SessionResponse(**(session or {"id": session_id, "repo_id": "", "mode": "", "status": "running"}))


@router.websocket("/{session_id}/stream")
async def session_stream(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for live session streaming.

    Clients receive JSON messages:
    - {"type": "turn", "data": {"turn": 5, "tool": "read_file", "args": {...}}}
    - {"type": "llm_response", "data": {"content": "..."}}
    - {"type": "file_changed", "data": {"path": "src/foo.py", "action": "edit"}}
    - {"type": "complete", "data": {"result": {...}}}
    """
    await session_manager.connect(session_id, websocket)
    try:
        while True:
            # Keep connection alive, wait for client messages (e.g., ping)
            await websocket.receive_text()
    except WebSocketDisconnect:
        await session_manager.disconnect(session_id, websocket)
