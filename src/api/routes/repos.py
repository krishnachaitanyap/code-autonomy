"""API routes for repository management."""

import logging
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.api.schemas import RepoCreate, RepoResponse, SymbolResponse
from src.services.repo_service import RepoService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["repos"])
repo_service = RepoService()


class SkillsBody(BaseModel):
    content: str


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

    # Auto-generate SKILLS.md if local path exists and file doesn't already exist
    if repo.local_path and os.path.isdir(repo.local_path):
        skills_path = Path(repo.local_path) / "SKILLS.md"
        if not skills_path.is_file():
            try:
                from src.agent.knowledge_generator import generate_skills_markdown
                from src.services.config_service import ConfigService

                config = ConfigService().load_config()
                consciousness = repo_service.build_consciousness(
                    repo.local_path, config, repo.url,
                )
                content = generate_skills_markdown(consciousness)
                skills_path.write_text(content, encoding="utf-8")
                logger.info("Auto-generated SKILLS.md for repo %s", repo.id)
            except Exception as exc:
                logger.warning("Failed to auto-generate SKILLS.md for repo %s: %s", repo.id, exc)

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
    repo = repo_service.get_repo(repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")

    try:
        from src.platform.platform_client import get_platform_client
        from src.services.config_service import ConfigService

        config = ConfigService().load_config()
        client = get_platform_client(repo.platform, repo.url, config=config)
        branches = client.list_branches(repo.url)

        # Fallback to local git if REST returns empty and local path exists
        if not branches and repo.local_path:
            from src.platform.git_ops import list_branches

            branches = list_branches(repo.local_path)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not list branches: {exc}")

    return {"branches": branches}


@router.delete("/{repo_id}", status_code=204)
async def delete_repo(repo_id: str):
    """Delete a repository and all related data."""
    repo = repo_service.get_repo(repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    deleted = repo_service.delete_repo(repo_id)
    if not deleted:
        raise HTTPException(status_code=500, detail="Failed to delete repository")


@router.get("/{repo_id}/skills")
async def get_skills(repo_id: str):
    """Read SKILLS.md from the repository root."""
    repo = repo_service.get_repo(repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    if not repo.local_path or not os.path.isdir(repo.local_path):
        return {"content": ""}
    skills_path = Path(repo.local_path) / "SKILLS.md"
    if skills_path.is_file():
        try:
            return {"content": skills_path.read_text(encoding="utf-8")}
        except Exception:
            return {"content": ""}
    return {"content": ""}


@router.put("/{repo_id}/skills")
async def update_skills(repo_id: str, body: SkillsBody):
    """Write SKILLS.md to the repository root."""
    repo = repo_service.get_repo(repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    if not repo.local_path or not os.path.isdir(repo.local_path):
        raise HTTPException(status_code=400, detail="Repository has no local path")
    skills_path = Path(repo.local_path) / "SKILLS.md"
    skills_path.write_text(body.content, encoding="utf-8")
    # Invalidate cached repo_knowledge so the next agent run picks up changes
    try:
        from src.services.cache import repo_cache
        repo_cache.invalidate(repo_id, "repo_knowledge")
    except Exception:
        pass
    return {"content": body.content}


@router.post("/{repo_id}/skills/generate")
async def generate_skills(repo_id: str):
    """Auto-generate SKILLS.md from project consciousness."""
    repo = repo_service.get_repo(repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    if not repo.local_path or not os.path.isdir(repo.local_path):
        raise HTTPException(status_code=400, detail="Repository has no local path")

    try:
        from src.agent.knowledge_generator import generate_skills_markdown
        from src.services.config_service import ConfigService

        config = ConfigService().load_config()
        consciousness = repo_service.build_consciousness(
            repo.local_path, config, repo.url,
        )
        content = generate_skills_markdown(consciousness)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to generate SKILLS.md: {exc}")

    # Write to repo root
    skills_path = Path(repo.local_path) / "SKILLS.md"
    skills_path.write_text(content, encoding="utf-8")

    # Invalidate cached repo_knowledge
    try:
        from src.services.cache import repo_cache
        repo_cache.invalidate(repo_id, "repo_knowledge")
    except Exception:
        pass

    return {"content": content}


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
