"""API routes for JIRA session management."""

from fastapi import APIRouter, HTTPException

from src.api.schemas import JiraSessionCreate, JiraSessionResponse
from src.services.jira_service import JiraService

router = APIRouter(tags=["jira"])
jira_service = JiraService()


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
