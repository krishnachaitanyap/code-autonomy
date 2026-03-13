"""API route for quick ask (no session tracking overhead)."""

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException

from src.api.schemas import AskRequest, AskResponse
from src.services.agent_service import AgentService
from src.services.repo_service import RepoService

router = APIRouter(tags=["ask"])
agent_service = AgentService()
repo_service = RepoService()
logger = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=4)


@router.post("", response_model=AskResponse)
async def ask_question(body: AskRequest):
    """Quick ask — answer a question about a repository's codebase.

    This creates a lightweight ask session and returns the answer directly.
    For tracked sessions with streaming, use POST /api/sessions instead.
    """
    from src.data.database import get_session, init_db
    from src.data.repositories import RepoRepository

    init_db()
    with get_session() as db:
        repo = RepoRepository(db).get_by_id(body.repo_id)
        if repo is None:
            raise HTTPException(status_code=404, detail="Repository not found")
        repo_path = repo.local_path
        repo_url = repo.url

    try:
        from src.services.config_service import ConfigService
        config = ConfigService().load_config()
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="Config file (config.ini) not found")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not load config: {exc}")

    # Validate that an LLM API key is available
    ai_key = config.get("ai", {}).get("api_key", "")
    if not ai_key:
        raise HTTPException(
            status_code=400,
            detail="No LLM API key configured. Set OPENAI_API_KEY (or ANTHROPIC_API_KEY) in your environment, or configure it in config.ini under [ai] api_key.",
        )

    # Auto-clone if local_path is missing or doesn't exist
    if not repo_path or not os.path.isdir(repo_path):
        try:
            repo_path = repo_service.ensure_local_clone(body.repo_id, config=config)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))

    def _run():
        return agent_service.run_ask(
            repo_path=repo_path,
            question=body.question,
            config=config,
            repo_url=repo_url,
        )

    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(_executor, _run)
    except Exception as exc:
        logger.exception("Ask failed for repo %s", body.repo_id)
        raise HTTPException(status_code=500, detail=f"Agent error: {exc}")

    return AskResponse(
        success=result.success,
        answer=result.answer if result.answer else result.summary,
        sources=result.sources,
        turns_used=result.turns_used,
    )
