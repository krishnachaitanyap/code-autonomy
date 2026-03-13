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


class ClaudeMdBody(BaseModel):
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

    # Auto-generate SKILLS.md and CLAUDE.md if local path exists
    if repo.local_path and os.path.isdir(repo.local_path):
        skills_path = Path(repo.local_path) / "SKILLS.md"
        claude_path = Path(repo.local_path) / "CLAUDE.md"
        needs_skills = not skills_path.is_file()
        needs_claude = not claude_path.is_file()

        if needs_skills or needs_claude:
            try:
                from src.agent.knowledge_generator import generate_skills_markdown, generate_claude_md
                from src.services.config_service import ConfigService

                config = ConfigService().load_config()
                consciousness = repo_service.build_consciousness(
                    repo.local_path, config, repo.url,
                )

                if needs_skills:
                    content = generate_skills_markdown(consciousness, repo_path=repo.local_path)
                    skills_path.write_text(content, encoding="utf-8")
                    logger.info("Auto-generated SKILLS.md for repo %s", repo.id)

                if needs_claude:
                    content = generate_claude_md(consciousness, repo_path=repo.local_path)
                    claude_path.write_text(content, encoding="utf-8")
                    logger.info("Auto-generated CLAUDE.md for repo %s", repo.id)
            except Exception as exc:
                logger.warning("Failed to auto-generate knowledge files for repo %s: %s", repo.id, exc)

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
        content = generate_skills_markdown(consciousness, repo_path=repo.local_path)
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


@router.get("/{repo_id}/claude-md")
async def get_claude_md(repo_id: str):
    """Read CLAUDE.md from the repository root."""
    repo = repo_service.get_repo(repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    if not repo.local_path or not os.path.isdir(repo.local_path):
        return {"content": ""}
    claude_path = Path(repo.local_path) / "CLAUDE.md"
    if claude_path.is_file():
        try:
            return {"content": claude_path.read_text(encoding="utf-8")}
        except Exception:
            return {"content": ""}
    return {"content": ""}


@router.put("/{repo_id}/claude-md")
async def update_claude_md(repo_id: str, body: ClaudeMdBody):
    """Write CLAUDE.md to the repository root."""
    repo = repo_service.get_repo(repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    if not repo.local_path or not os.path.isdir(repo.local_path):
        raise HTTPException(status_code=400, detail="Repository has no local path")
    claude_path = Path(repo.local_path) / "CLAUDE.md"
    claude_path.write_text(body.content, encoding="utf-8")
    # Invalidate cached repo_knowledge so the next agent run picks up changes
    try:
        from src.services.cache import repo_cache
        repo_cache.invalidate(repo_id, "repo_knowledge")
    except Exception:
        pass
    return {"content": body.content}


@router.post("/{repo_id}/claude-md/generate")
async def generate_claude_md_endpoint(repo_id: str):
    """Auto-generate CLAUDE.md from project consciousness and stack analysis."""
    repo = repo_service.get_repo(repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    if not repo.local_path or not os.path.isdir(repo.local_path):
        raise HTTPException(status_code=400, detail="Repository has no local path")

    try:
        from src.agent.knowledge_generator import generate_claude_md
        from src.services.config_service import ConfigService

        config = ConfigService().load_config()
        consciousness = repo_service.build_consciousness(
            repo.local_path, config, repo.url,
        )
        content = generate_claude_md(consciousness, repo_path=repo.local_path)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to generate CLAUDE.md: {exc}")

    # Write to repo root
    claude_path = Path(repo.local_path) / "CLAUDE.md"
    claude_path.write_text(content, encoding="utf-8")

    # Invalidate cached repo_knowledge
    try:
        from src.services.cache import repo_cache
        repo_cache.invalidate(repo_id, "repo_knowledge")
    except Exception:
        pass

    return {"content": content}


class IdentifyDepsBody(BaseModel):
    prompt: str


@router.get("/{repo_id}/dependencies")
async def get_repo_dependencies(repo_id: str):
    """Get downstream dependencies (services, data stores, messaging, APIs) for a repo.

    Auto-clones the repo if it has a URL but no local path yet.
    """
    repo = repo_service.get_repo(repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")

    local_path = repo.local_path if (repo.local_path and os.path.isdir(repo.local_path)) else ""

    # Auto-clone if we have a URL but no local path
    if not local_path and repo.url:
        try:
            from src.services.config_service import ConfigService
            config = ConfigService().load_config()
            local_path = repo_service.ensure_local_clone(repo_id, config=config)
        except Exception as exc:
            logger.warning("Auto-clone failed for %s: %s", repo_id, exc)

    if not local_path:
        return {
            "downstream_services": [],
            "data_stores": [],
            "messaging": [],
            "api_endpoints": [],
        }

    try:
        from src.consciousness.stack_analyzer import analyze_stack
        from src.services.config_service import ConfigService

        config = ConfigService().load_config()
        profile = analyze_stack(local_path, config=config)

        # Cross-reference: enrich each downstream service with invoking API endpoints
        class_to_endpoints: dict[str, list[dict]] = {}
        for ep in profile.api_endpoints:
            class_to_endpoints.setdefault(ep["class"], []).append(ep)

        for svc in profile.downstream_services:
            invoking_endpoints = []
            for cls in svc.get("source_classes", []):
                invoking_endpoints.extend(class_to_endpoints.get(cls, []))
            svc["invoking_endpoints"] = invoking_endpoints

        # Cross-reference: enrich messaging entries with invoking API endpoints
        for msg in profile.messaging:
            invoking_endpoints = []
            for cls in msg.get("source_classes", []):
                invoking_endpoints.extend(class_to_endpoints.get(cls, []))
            msg["invoking_endpoints"] = invoking_endpoints

        # Cross-reference: enrich data stores with invoking API endpoints
        for ds in profile.data_stores:
            invoking_endpoints = []
            for cls in ds.get("source_classes", []):
                invoking_endpoints.extend(class_to_endpoints.get(cls, []))
            ds["invoking_endpoints"] = invoking_endpoints

        # Reverse map: enrich API endpoints with their downstream impact
        endpoint_impact: dict[tuple, dict] = {}
        for ep in profile.api_endpoints:
            ep_key = (ep["class"], ep["path"], ep["http_method"])
            endpoint_impact[ep_key] = {"services": [], "datastores": [], "messaging": []}

        for svc in profile.downstream_services:
            for cls in svc.get("source_classes", []):
                for ep in class_to_endpoints.get(cls, []):
                    ep_key = (ep["class"], ep["path"], ep["http_method"])
                    if ep_key in endpoint_impact:
                        endpoint_impact[ep_key]["services"].append(svc["name"])

        for ds in profile.data_stores:
            for cls in ds.get("source_classes", []):
                for ep in class_to_endpoints.get(cls, []):
                    ep_key = (ep["class"], ep["path"], ep["http_method"])
                    if ep_key in endpoint_impact:
                        entities_label = ", ".join(ds.get("entities", []))
                        endpoint_impact[ep_key]["datastores"].append(entities_label)

        for msg in profile.messaging:
            for cls in msg.get("source_classes", []):
                for ep in class_to_endpoints.get(cls, []):
                    ep_key = (ep["class"], ep["path"], ep["http_method"])
                    if ep_key in endpoint_impact:
                        label = msg.get("topic") or msg.get("type", "")
                        endpoint_impact[ep_key]["messaging"].append(f"{label} ({msg.get('direction', '')})")

        # Attach impact data to each endpoint
        for ep in profile.api_endpoints:
            ep_key = (ep["class"], ep["path"], ep["http_method"])
            impact = endpoint_impact.get(ep_key, {})
            ep["impacted_services"] = list(set(impact.get("services", [])))
            ep["impacted_datastores"] = list(set(impact.get("datastores", [])))
            ep["impacted_messaging"] = list(set(impact.get("messaging", [])))

        return {
            "downstream_services": profile.downstream_services,
            "data_stores": profile.data_stores,
            "messaging": profile.messaging,
            "api_endpoints": profile.api_endpoints[:20],  # limit to 20
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Dependency analysis failed: {exc}")


@router.post("/{repo_id}/dependencies/identify")
async def identify_dependencies(repo_id: str, body: IdentifyDepsBody):
    """Use an AI prompt to help identify additional downstream dependencies.

    The caller provides a prompt with hints, patterns, or sample service names
    to scan for in the codebase.
    """
    repo = repo_service.get_repo(repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")

    local_path = repo.local_path if (repo.local_path and os.path.isdir(repo.local_path)) else ""

    # Auto-clone if needed
    if not local_path and repo.url:
        try:
            from src.services.config_service import ConfigService
            config = ConfigService().load_config()
            local_path = repo_service.ensure_local_clone(repo_id, config=config)
        except Exception as exc:
            logger.warning("Auto-clone failed for %s: %s", repo_id, exc)

    if not local_path:
        raise HTTPException(status_code=400, detail="Repository has no local path and could not be cloned")

    try:
        import re

        prompt_text = body.prompt.strip()
        repo_path = Path(local_path)

        # Parse prompt for service names/patterns to search for
        # Users can provide things like: "look for OrderService, PaymentGateway, redis cache"
        search_terms = [t.strip() for t in re.split(r"[,;\n]+", prompt_text) if t.strip()]

        found_services: list[dict] = []
        source_exts = {".java", ".py", ".ts", ".js", ".kt", ".go", ".cs", ".yaml", ".yml", ".xml", ".properties", ".json"}
        skip_dirs = {"node_modules", "vendor", "build", "target", "dist", "__pycache__", ".git"}

        # Check for special keyword to scan enterprise patterns
        is_enterprise_scan = any(
            kw in prompt_text.lower()
            for kw in ("restproxy", "rest proxy", "channelutil", "channel util", "getinstance", "enterprise", "custom proxy")
        )

        for term in search_terms:
            term_lower = term.lower()
            pattern = re.compile(re.escape(term), re.IGNORECASE)
            files_found: list[str] = []

            for f in repo_path.rglob("*"):
                if not f.is_file() or f.suffix not in source_exts:
                    continue
                if any(p in skip_dirs for p in f.parts):
                    continue
                try:
                    content = f.read_text(errors="ignore")
                    if pattern.search(content):
                        files_found.append(str(f.relative_to(repo_path)))
                        if len(files_found) >= 5:
                            break
                except Exception:
                    continue

            if files_found:
                found_services.append({
                    "name": term,
                    "client_type": "identified_skill",
                    "url": "",
                    "files_referencing": files_found,
                    "confidence": "high" if len(files_found) >= 3 else "medium" if len(files_found) >= 1 else "low",
                })

        # Enterprise pattern scan: find RESTProxy.getInstance() and property-based URLs
        if is_enterprise_scan:
            rest_proxy_re = re.compile(r"RESTProxy\s*\.\s*getInstance\s*\(\s*(\w+)\s*\)")
            const_def_re = re.compile(r'(?:static\s+final|final\s+static)\s+String\s+(\w+)\s*=\s*["\']([^"\']+)["\']')
            prop_url_re = re.compile(r"^([\w.]+\.(?:svc\.rest\.url|rest\.url|svc\.url|endpoint\.url))\s*=\s*(.+)$", re.MULTILINE)
            proxy_names = set()

            # Scan Java files for RESTProxy patterns
            for f in repo_path.rglob("*.java"):
                if any(p in skip_dirs for p in f.parts):
                    continue
                try:
                    content = f.read_text(errors="ignore")
                    constants = {}
                    for cm in const_def_re.finditer(content):
                        constants[cm.group(1)] = cm.group(2)
                    for pm in rest_proxy_re.finditer(content):
                        var_name = pm.group(1)
                        resolved = constants.get(var_name, var_name)
                        proxy_names.add(resolved)
                except Exception:
                    continue

            # Scan .properties files for service URL entries
            for f in repo_path.rglob("*.properties"):
                if any(p in skip_dirs for p in f.parts):
                    continue
                try:
                    content = f.read_text(errors="ignore")
                    for pm in prop_url_re.finditer(content):
                        proxy_names.add(pm.group(1))
                except Exception:
                    continue

            existing = {s["name"] for s in found_services}
            for pname in sorted(proxy_names):
                if pname not in existing:
                    from src.consciousness.stack_analyzer import _property_key_to_service_name
                    readable = _property_key_to_service_name(pname)
                    found_services.append({
                        "name": readable,
                        "client_type": "RESTProxy",
                        "url": pname if "." in pname else "",
                        "files_referencing": [],
                        "confidence": "high",
                    })

        return {
            "identified_services": found_services,
            "search_terms_used": search_terms,
            "prompt": prompt_text,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Dependency identification failed: {exc}")


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
