"""API route for quick ask (no session tracking overhead)."""

import logging
import os

from fastapi import APIRouter, HTTPException

from src.api.schemas import AskRequest, AskResponse
from src.services.agent_service import AgentService

router = APIRouter(tags=["ask"])
agent_service = AgentService()
logger = logging.getLogger(__name__)


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

    # Validate repo path exists
    if not repo_path or not os.path.isdir(repo_path):
        raise HTTPException(
            status_code=400,
            detail=f"Repository path does not exist: {repo_path}. Register the repo with a valid local_path first.",
        )

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

    try:
        result = agent_service.run_ask(
            repo_path=repo_path,
            question=body.question,
            config=config,
            repo_url=repo_url,
        )
    except Exception as exc:
        logger.exception("Ask failed for repo %s", body.repo_id)
        raise HTTPException(status_code=500, detail=f"Agent error: {exc}")

    return AskResponse(
        success=result.success,
        answer=result.answer if result.success else result.summary,
        sources=result.sources if result.success else [],
        turns_used=result.turns_used,
    )
