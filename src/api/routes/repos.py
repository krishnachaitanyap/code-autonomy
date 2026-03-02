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


@router.get("/{repo_id}/branches")
async def list_repo_branches(repo_id: str):
    """List available branches for a repository."""
    import os
    repo = repo_service.get_repo(repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")

    # Resolve auth token for remote git operations
    auth_token = (
        os.environ.get("BITBUCKET_HTTP_ACCESS_TOKEN", "")
        or os.environ.get("BITBUCKET_APP_PASSWORD", "")
        or os.environ.get("BITBUCKET_SERVER_TOKEN", "")
        or os.environ.get("GITHUB_TOKEN", "")
    )

    try:
        from src.platform.git_ops import list_branches, list_remote_branches
        import subprocess

        branches: list[str] = []

        # If repo has a remote URL, check whether the local path actually
        # belongs to that URL.  If it doesn't (e.g. local_path is the
        # code-autonomy dir, not the cloned target repo), fetch branches
        # directly from the remote instead.
        if repo.url and repo.local_path:
            try:
                r = subprocess.run(
                    ["git", "-C", repo.local_path, "remote", "get-url", "origin"],
                    capture_output=True, text=True, timeout=5,
                )
                local_remote = r.stdout.strip() if r.returncode == 0 else ""
            except Exception:
                local_remote = ""

            # Normalize for comparison (strip trailing .git and slashes)
            def _norm(u: str) -> str:
                return u.rstrip("/").removesuffix(".git").lower()

            if _norm(local_remote) != _norm(repo.url):
                # Local path doesn't match repo URL — use remote listing
                branches = list_remote_branches(repo.url, auth_token=auth_token or None)
                if branches:
                    return {"branches": branches}

        # Default: list from local path
        if repo.local_path:
            branches = list_branches(repo.local_path)
        elif repo.url:
            branches = list_remote_branches(repo.url, auth_token=auth_token or None)
        else:
            raise HTTPException(status_code=400, detail="Repository has no local path or URL")

    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not list branches: {exc}")

    return {"branches": branches}


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
