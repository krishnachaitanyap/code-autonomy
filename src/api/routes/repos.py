"""API routes for repository management."""

from fastapi import APIRouter, HTTPException

from src.api.schemas import RepoCreate, RepoResponse, SymbolResponse
from src.services.repo_service import RepoService

router = APIRouter(tags=["repos"])
repo_service = RepoService()


@router.get("", response_model=list[RepoResponse])
async def list_repos():
    """List all registered repositories."""
    repos = repo_service.list_repos()
    return [
        RepoResponse(
            id=r.id, url=r.url, local_path=r.local_path,
            platform=r.platform, created_at=r.created_at, updated_at=r.updated_at,
        )
        for r in repos
    ]


@router.post("", response_model=RepoResponse)
async def register_repo(body: RepoCreate):
    """Register a new repository."""
    if not body.local_path and not body.url:
        raise HTTPException(status_code=400, detail="Either local_path or url is required")

    repo = repo_service.register_repo(
        repo_path=body.local_path or "",
        platform=body.platform,
        repo_url=body.url,
    )
    return RepoResponse(
        id=repo.id, url=repo.url, local_path=repo.local_path,
        platform=repo.platform, created_at=repo.created_at, updated_at=repo.updated_at,
    )


@router.get("/{repo_id}", response_model=RepoResponse)
async def get_repo(repo_id: str):
    """Get repository details."""
    repo = repo_service.get_repo(repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    return RepoResponse(
        id=repo.id, url=repo.url, local_path=repo.local_path,
        platform=repo.platform, created_at=repo.created_at, updated_at=repo.updated_at,
    )


@router.get("/{repo_id}/symbols", response_model=list[SymbolResponse])
async def get_repo_symbols(repo_id: str, file_path: str = ""):
    """Get symbol table for a repository."""
    repo = repo_service.get_repo(repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")

    # Symbols require config — try to load default
    try:
        from src.services.config_service import ConfigService
        config = ConfigService().load_config()
    except Exception:
        raise HTTPException(status_code=500, detail="Could not load config for code index")

    symbols = repo_service.get_symbols(
        repo.local_path, config, repo_url=repo.url,
        file_path=file_path or None,
    )
    return [SymbolResponse(**s) for s in symbols]
