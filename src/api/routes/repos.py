"""API routes for repository management."""

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.api.schemas import RepoCreate, RepoResponse, SymbolResponse
from src.services.repo_service import RepoService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["repos"])
repo_service = RepoService()
_indexing_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="repo-index")


def _default_nickname(url: str, local_path: str) -> str:
    """Derive a short nickname from URL or local path."""
    source = url or local_path
    if not source:
        return ""
    # Strip trailing slashes and .git
    name = source.rstrip("/")
    if name.endswith(".git"):
        name = name[:-4]
    # Take the last path segment
    name = name.rsplit("/", 1)[-1]
    return name


def _index_repo_background(repo_id: str, local_path: str, repo_url: str) -> None:
    """Background: build consciousness index and auto-generate SKILLS.md / CLAUDE.md."""
    try:
        skills_path = Path(local_path) / "SKILLS.md"
        claude_path = Path(local_path) / "CLAUDE.md"
        needs_skills = not skills_path.is_file()
        needs_claude = not claude_path.is_file()

        if not needs_skills and not needs_claude:
            return

        from src.agent.knowledge_generator import generate_skills_markdown, generate_claude_md
        from src.services.config_service import ConfigService

        config = ConfigService().load_config()
        consciousness = repo_service.build_consciousness(local_path, config, repo_url)

        if needs_skills:
            content = generate_skills_markdown(consciousness, repo_path=local_path)
            skills_path.write_text(content, encoding="utf-8")
            logger.info("Auto-generated SKILLS.md for repo %s", repo_id)

        if needs_claude:
            content = generate_claude_md(consciousness, repo_path=local_path)
            claude_path.write_text(content, encoding="utf-8")
            logger.info("Auto-generated CLAUDE.md for repo %s", repo_id)
    except Exception as exc:
        logger.warning("Background indexing failed for repo %s: %s", repo_id, exc)


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
            platform=r.platform,
            nickname=r.nickname or _default_nickname(r.url, r.local_path),
            created_at=r.created_at, updated_at=r.updated_at,
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

    # Set nickname
    if body.nickname:
        nickname = body.nickname
    elif not repo.nickname:
        nickname = _default_nickname(repo.url, repo.local_path)
    else:
        nickname = repo.nickname

    if nickname and nickname != repo.nickname:
        from src.data.database import get_session
        from src.data.repositories import RepoRepository
        with get_session() as db:
            RepoRepository(db).update(repo.id, nickname=nickname)
            repo.nickname = nickname

    # Auto-generate SKILLS.md and CLAUDE.md in background (non-blocking)
    if repo.local_path and os.path.isdir(repo.local_path):
        repo_id = repo.id
        local_path = repo.local_path
        repo_url = repo.url
        loop = asyncio.get_running_loop()
        loop.run_in_executor(
            _indexing_executor,
            lambda: _index_repo_background(repo_id, local_path, repo_url),
        )

    return RepoResponse(
        id=repo.id, url=repo.url, local_path=repo.local_path,
        platform=repo.platform,
        nickname=repo.nickname or _default_nickname(repo.url, repo.local_path),
        created_at=repo.created_at, updated_at=repo.updated_at,
    )


@router.get("/{repo_id}", response_model=RepoResponse)
async def get_repo(repo_id: str):
    """Get repository details."""
    repo = repo_service.get_repo(repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")
    return RepoResponse(
        id=repo.id, url=repo.url, local_path=repo.local_path,
        platform=repo.platform,
        nickname=repo.nickname or _default_nickname(repo.url, repo.local_path),
        created_at=repo.created_at, updated_at=repo.updated_at,
    )


@router.get("/{repo_id}/branches")
async def list_repo_branches(repo_id: str):
    """List available branches for a repository."""
    repo = repo_service.get_repo(repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")

    branches: list[str] = []

    # Try platform REST API first
    try:
        from src.platform.platform_client import get_platform_client
        from src.services.config_service import ConfigService

        config = ConfigService().load_config()
        client = get_platform_client(repo.platform, repo.url, config=config)
        branches = client.list_branches(repo.url)
    except Exception as exc:
        logger.warning("Platform branch listing failed for %s: %s", repo_id, exc)

    # Fallback to local git if REST returned empty and local path exists
    if not branches and repo.local_path:
        try:
            from src.platform.git_ops import list_branches
            branches = list_branches(repo.local_path)
        except Exception as exc:
            logger.warning("Local git branch listing failed for %s: %s", repo_id, exc)

    # Detect the currently checked-out branch in the workspace
    current_branch = ""
    if repo.local_path:
        try:
            from src.platform.git_ops import get_current_branch
            current_branch = get_current_branch(repo.local_path)
        except Exception:
            pass

    return {"branches": branches, "current_branch": current_branch}


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


@router.get("/{repo_id}/file-tree")
async def get_repo_file_tree(repo_id: str, max_files: int = 2000):
    """Get the file tree for a repository — lightweight, no code index needed.

    Returns a list of source files with inferred type and directory info,
    suitable for building an architecture graph without a full code index.
    """
    import os
    from pathlib import Path

    repo = repo_service.get_repo(repo_id)
    if repo is None:
        raise HTTPException(status_code=404, detail="Repository not found")

    repo_path = repo.local_path
    if not repo_path or not Path(repo_path).is_dir():
        raise HTTPException(status_code=400, detail="Repository path not available locally")

    # Source file extensions to include
    SOURCE_EXTS = {
        '.java', '.py', '.ts', '.tsx', '.js', '.jsx', '.go', '.rs', '.kt', '.scala',
        '.cs', '.rb', '.php', '.swift', '.c', '.cpp', '.h', '.hpp',
        '.xml', '.yml', '.yaml', '.json', '.properties', '.ini', '.toml',
        '.sql', '.graphql', '.proto', '.tf', '.sh',
        '.feature', '.md',
    }

    # Directories to skip
    SKIP_DIRS = {
        'node_modules', '.git', '.svn', '__pycache__', '.idea', '.vscode',
        '.gradle', 'build', 'dist', 'target', '.next', '.nuxt',
        'vendor', '.tox', '.mypy_cache', '.pytest_cache', 'venv', 'env',
    }

    root = Path(repo_path)
    files = []

    for dirpath, dirnames, filenames in os.walk(root):
        # Prune skipped directories
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith('.')]

        rel_dir = os.path.relpath(dirpath, root)
        if rel_dir == '.':
            rel_dir = ''

        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in SOURCE_EXTS:
                continue

            rel_path = os.path.join(rel_dir, fname) if rel_dir else fname
            full_path = os.path.join(dirpath, fname)

            # Infer file type from extension
            if ext in {'.java', '.py', '.ts', '.tsx', '.js', '.jsx', '.go', '.rs', '.kt', '.scala', '.cs', '.rb', '.php', '.swift', '.c', '.cpp'}:
                file_type = 'source'
            elif ext in {'.xml', '.yml', '.yaml', '.json', '.properties', '.ini', '.toml'}:
                file_type = 'config'
            elif ext in {'.sql', '.graphql', '.proto'}:
                file_type = 'schema'
            elif ext in {'.tf', '.sh'}:
                file_type = 'infra'
            elif ext == '.feature':
                file_type = 'test'
            elif ext == '.md':
                file_type = 'docs'
            else:
                file_type = 'other'

            # Get file size for complexity hint
            try:
                size = os.path.getsize(full_path)
            except OSError:
                size = 0

            files.append({
                'path': rel_path.replace('\\', '/'),
                'name': fname,
                'directory': rel_dir.replace('\\', '/'),
                'extension': ext,
                'file_type': file_type,
                'size': size,
            })

            if len(files) >= max_files:
                break
        if len(files) >= max_files:
            break

    # Detect infrastructure: Dockerfiles, K8s manifests, Helm charts, docker-compose
    infra = _detect_infrastructure(root)

    # Auto-discover custom layers from directory names and class suffixes
    custom_layers = _discover_custom_layers(files)

    return {
        'files': files,
        'total': len(files),
        'repo_path': repo_path,
        'infrastructure': infra,
        'discovered_layers': custom_layers,
    }


def _discover_custom_layers(files: list[dict]) -> list[dict]:
    """Auto-discover architectural layers from actual directory names and class suffixes.

    Scans all source files and identifies recurring directory names and
    class name suffixes that likely represent architectural layers not
    covered by the static rules (e.g., Invoker, Gateway, Processor,
    Delegator, Adapter in enterprise frameworks).
    """
    import os
    import re
    from collections import Counter

    # Count directory name segments (the meaningful part, e.g., "invoker" from "com/foo/invoker/")
    dir_segments: Counter = Counter()
    suffix_counter: Counter = Counter()

    for f in files:
        if f.get('file_type') != 'source':
            continue
        path = f.get('path', '')
        name = f.get('name', '')

        # Extract meaningful directory segments
        parts = path.replace('\\', '/').split('/')
        for part in parts[:-1]:  # exclude filename
            lower = part.lower()
            # Skip generic names
            if lower in ('src', 'main', 'java', 'kotlin', 'python', 'com', 'org', 'net',
                         'resources', 'webapp', 'app', 'module', 'modules', 'core',
                         'internal', 'impl', 'pkg', 'cmd'):
                continue
            if len(lower) >= 3:
                dir_segments[lower] += 1

        # Extract class name suffix (e.g., "FooInvoker" → "Invoker")
        basename = os.path.splitext(name)[0]
        m = re.match(r'^.*?([A-Z][a-z]{2,}(?:[A-Z][a-z]+)*)$', basename)
        if m:
            suffix = m.group(1)
            # Only count multi-char suffixes that appear as a pattern
            if len(suffix) >= 4 and suffix[0].isupper():
                suffix_counter[suffix] += 1

    # Layers = directory segments or suffixes that appear 3+ times
    # and are not already covered by standard patterns
    STANDARD_NAMES = {
        'controller', 'service', 'repository', 'model', 'entity', 'dto',
        'config', 'test', 'util', 'utils', 'helper', 'middleware', 'filter',
        'client', 'resource', 'dao', 'mapper', 'aspect', 'interceptor',
    }

    discovered = []

    for segment, count in dir_segments.most_common(20):
        if segment in STANDARD_NAMES or count < 3:
            continue
        # Check if this is a meaningful architectural pattern
        discovered.append({
            'name': segment.capitalize(),
            'pattern': segment,
            'count': count,
            'source': 'directory',
        })

    for suffix, count in suffix_counter.most_common(20):
        if suffix.lower() in STANDARD_NAMES or count < 3:
            continue
        if not any(d['pattern'] == suffix.lower() for d in discovered):
            discovered.append({
                'name': suffix,
                'pattern': suffix.lower(),
                'count': count,
                'source': 'class_suffix',
            })

    return discovered[:10]  # top 10 custom layers


def _detect_infrastructure(root) -> dict:
    """Scan for Docker, Kubernetes, Helm, and docker-compose artifacts."""
    import os
    import re
    from pathlib import Path

    containers: list[dict] = []
    k8s_resources: list[dict] = []
    helm_charts: list[str] = []
    compose_services: list[dict] = []

    for dirpath, dirnames, filenames in os.walk(root):
        # Skip irrelevant dirs
        rel_dir = os.path.relpath(dirpath, root)
        if any(p in rel_dir for p in ['.git', 'node_modules', 'target', 'build', 'dist']):
            continue

        for fname in filenames:
            full_path = os.path.join(dirpath, fname)
            rel_path = os.path.join(rel_dir, fname).replace('\\', '/').lstrip('./')

            # Dockerfiles
            if fname == 'Dockerfile' or fname.startswith('Dockerfile.') or fname.endswith('.Dockerfile'):
                container = {'name': '', 'file': rel_path, 'base_image': '', 'ports': [], 'type': 'docker'}
                try:
                    content = open(full_path, 'r', errors='replace').read(4096)
                    m = re.search(r'^FROM\s+(\S+)', content, re.MULTILINE)
                    if m:
                        container['base_image'] = m.group(1)
                    ports = re.findall(r'^EXPOSE\s+(.+)', content, re.MULTILINE)
                    container['ports'] = [p.strip() for line in ports for p in line.split()]
                    # Derive container name from directory or Dockerfile suffix
                    if fname.startswith('Dockerfile.'):
                        container['name'] = fname.split('.', 1)[1]
                    elif rel_dir and rel_dir != '.':
                        container['name'] = rel_dir.rstrip('/').split('/')[-1]
                    else:
                        container['name'] = 'app'
                except Exception:
                    pass
                containers.append(container)

            # docker-compose
            if fname in ('docker-compose.yml', 'docker-compose.yaml', 'compose.yml', 'compose.yaml'):
                try:
                    import yaml
                    content = open(full_path, 'r', errors='replace').read(8192)
                    data = yaml.safe_load(content) or {}
                    services = data.get('services', {})
                    for svc_name, svc_cfg in (services or {}).items():
                        svc = {
                            'name': svc_name,
                            'image': svc_cfg.get('image', ''),
                            'build': str(svc_cfg.get('build', '')),
                            'ports': [str(p) for p in (svc_cfg.get('ports') or [])],
                            'depends_on': list(svc_cfg.get('depends_on', {}).keys()) if isinstance(svc_cfg.get('depends_on'), dict) else list(svc_cfg.get('depends_on', []) or []),
                            'environment': list((svc_cfg.get('environment') or {}).keys()) if isinstance(svc_cfg.get('environment'), dict) else [str(e).split('=')[0] for e in (svc_cfg.get('environment') or [])],
                            'file': rel_path,
                        }
                        compose_services.append(svc)
                except Exception:
                    pass

            # Kubernetes manifests (YAML with kind: Deployment/Service/etc)
            if fname.endswith(('.yml', '.yaml')) and any(p in rel_dir.lower() for p in ['k8s', 'kube', 'deploy', 'manifest', 'helm', 'chart']):
                try:
                    import yaml
                    content = open(full_path, 'r', errors='replace').read(8192)
                    for doc in yaml.safe_load_all(content):
                        if not isinstance(doc, dict):
                            continue
                        kind = doc.get('kind', '')
                        if kind in ('Deployment', 'StatefulSet', 'DaemonSet', 'Job', 'CronJob',
                                    'Service', 'Ingress', 'ConfigMap', 'Secret', 'HorizontalPodAutoscaler',
                                    'PersistentVolumeClaim', 'NetworkPolicy', 'ServiceAccount'):
                            resource = {
                                'kind': kind,
                                'name': (doc.get('metadata') or {}).get('name', ''),
                                'namespace': (doc.get('metadata') or {}).get('namespace', ''),
                                'file': rel_path,
                            }
                            # Extract container details from pod specs
                            if kind in ('Deployment', 'StatefulSet', 'DaemonSet', 'Job', 'CronJob'):
                                spec = (doc.get('spec', {}).get('template', {}).get('spec', {}))
                                for c in (spec.get('containers') or []):
                                    resource.setdefault('containers', []).append({
                                        'name': c.get('name', ''),
                                        'image': c.get('image', ''),
                                        'ports': [str(p.get('containerPort', '')) for p in (c.get('ports') or [])],
                                    })
                                replicas = doc.get('spec', {}).get('replicas')
                                if replicas:
                                    resource['replicas'] = replicas
                            # Extract service ports/selectors
                            if kind == 'Service':
                                svc_spec = doc.get('spec', {})
                                resource['service_type'] = svc_spec.get('type', 'ClusterIP')
                                resource['ports'] = [
                                    {'port': p.get('port'), 'target': p.get('targetPort'), 'protocol': p.get('protocol', 'TCP')}
                                    for p in (svc_spec.get('ports') or [])
                                ]
                                resource['selector'] = svc_spec.get('selector', {})
                            # Ingress rules
                            if kind == 'Ingress':
                                ing_spec = doc.get('spec', {})
                                resource['rules'] = [
                                    {'host': r.get('host', ''), 'paths': [p.get('path', '/') for p in (r.get('http', {}).get('paths') or [])]}
                                    for r in (ing_spec.get('rules') or [])
                                ]
                            k8s_resources.append(resource)
                except Exception:
                    pass

            # Helm charts
            if fname == 'Chart.yaml' or fname == 'Chart.yml':
                helm_charts.append(rel_dir.replace('\\', '/'))

    return {
        'containers': containers,
        'k8s_resources': k8s_resources,
        'helm_charts': helm_charts,
        'compose_services': compose_services,
        'has_docker': len(containers) > 0 or len(compose_services) > 0,
        'has_kubernetes': len(k8s_resources) > 0,
        'has_helm': len(helm_charts) > 0,
    }
