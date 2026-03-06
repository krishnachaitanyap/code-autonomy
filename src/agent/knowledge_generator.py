"""
One-time scaffolding tool: auto-generate a `.code-autonomy.md` repo knowledge
file from ProjectConsciousness data.

Separate from knowledge.py (which handles runtime load/persist) since this is
a CLI-invoked generation tool, not part of the agent loop.
"""

import os
from pathlib import Path
from typing import Optional

from src.consciousness.core import ProjectConsciousness, _format_structure
from src.agent.knowledge import (
    _REPO_KNOWLEDGE_DIR,
    _REPO_KNOWLEDGE_FILE,
    _REPO_KNOWLEDGE_ALT_FILE,
    _REPO_KNOWLEDGE_MAX_CHARS,
)

_BUDGET = 9500  # leave headroom below _REPO_KNOWLEDGE_MAX_CHARS (10,000)
_SKILLS_BUDGET = 12000  # SKILLS.md with deep stack analysis


# ---------------------------------------------------------------------------
# Section generators
# ---------------------------------------------------------------------------

def _section_project_overview(conventions: dict) -> str:
    lang = conventions.get("language", "unknown")
    build = conventions.get("build_tool", "unknown")

    lines = ["## Project Overview", ""]
    if lang != "unknown":
        lines.append(f"- **Language:** {lang}")
    else:
        lines.append("- **Language:** <!-- TODO: e.g. python, java, typescript -->")
    if build != "unknown":
        lines.append(f"- **Build tool:** {build}")
    else:
        lines.append("- **Build tool:** <!-- TODO: e.g. pip, maven, gradle, npm -->")
    lines.append("- **Description:** <!-- TODO: one-line project description -->")
    return "\n".join(lines)


def _section_repository_layout(structure: dict) -> str:
    lines = ["## Repository Layout", ""]
    if not structure or (not structure.get("subdirs") and not structure.get("files")):
        lines.append("<!-- TODO: describe your directory layout -->")
        return "\n".join(lines)

    tree = _format_structure(structure, indent=0, max_depth=2)
    # Cap the tree at 1500 chars
    if len(tree) > 1500:
        tree = tree[:1500] + "\n... (trimmed)"
    lines.append("```")
    lines.append(tree)
    lines.append("```")
    return "\n".join(lines)


def _section_coding_conventions(conventions: dict) -> str:
    naming = conventions.get("naming_style", "unknown")

    lines = ["## Coding Conventions", ""]
    if naming != "unknown":
        lines.append(f"- **Naming style:** {naming}")
    else:
        lines.append("- **Naming style:** <!-- TODO: snake_case, camelCase, etc. -->")
    lines.append("- **Formatting/linting:** <!-- TODO: e.g. black, ruff, prettier, checkstyle -->")
    lines.append("- **Import ordering:** <!-- TODO: e.g. isort, stdlib-first -->")
    return "\n".join(lines)


def _section_testing(conventions: dict) -> str:
    framework = conventions.get("test_framework", "unknown")

    lines = ["## Testing", ""]
    if framework != "unknown":
        lines.append(f"- **Framework:** {framework}")
    else:
        lines.append("- **Framework:** <!-- TODO: e.g. pytest, junit5, jest -->")
    lines.append("- **Run tests:** <!-- TODO: e.g. pytest tests/, mvn test -->")
    lines.append("- **Coverage:** <!-- TODO: e.g. pytest --cov=src -->")
    return "\n".join(lines)


def _section_important_files(signatures: list, samples: list) -> str:
    lines = ["## Important Files", ""]

    # Build table from top 8 ranked samples + their signature names
    entries: list[tuple[str, str]] = []
    sig_by_path: dict[str, list[str]] = {}
    for sig in signatures:
        p = sig.get("path", "")
        n = sig.get("name", "")
        if p and n:
            sig_by_path.setdefault(p, []).append(n)

    for sample in samples[:8]:
        path = sample.get("path", "")
        if not path:
            continue
        names = sig_by_path.get(path, [])
        desc = ", ".join(names[:4]) if names else "<!-- TODO: describe -->"
        entries.append((path, desc))

    if entries:
        lines.append("| File | Key symbols / purpose |")
        lines.append("|------|----------------------|")
        for path, desc in entries:
            lines.append(f"| `{path}` | {desc} |")
    else:
        lines.append("| File | Key symbols / purpose |")
        lines.append("|------|----------------------|")
        lines.append("| <!-- TODO --> | <!-- TODO --> |")

    return "\n".join(lines)


def _section_architecture_notes() -> str:
    return "\n".join([
        "## Architecture Notes",
        "",
        "<!-- TODO: describe high-level architecture, data flow, key design decisions -->",
    ])


def _section_domain_context() -> str:
    return "\n".join([
        "## Domain Context",
        "",
        "<!-- TODO: describe the business domain, key terminology, domain rules -->",
    ])


def _section_things_to_watch() -> str:
    return "\n".join([
        "## Things to Watch",
        "",
        "<!-- TODO: gotchas, common mistakes, files that should not be modified, etc. -->",
    ])


# ---------------------------------------------------------------------------
# Stack-aware section generators (consume StackProfile)
# ---------------------------------------------------------------------------

def _section_app_type(profile) -> str:
    return f"- **App type:** {profile.app_type}"


def _section_tech_stack_table(profile) -> str:
    if not profile.technologies:
        return ""
    lines = ["## Technology Stack", "",
             "| Category | Technologies |",
             "|----------|-------------|"]
    category_labels = {
        "api": "API", "messaging": "Messaging", "cache": "Cache",
        "database": "Database", "http_client": "HTTP Clients",
        "observability": "Observability", "config": "Config",
        "security": "Security", "discovery": "Discovery",
        "batch": "Batch", "frontend": "Frontend",
    }
    for cat, techs in profile.technologies.items():
        label = category_labels.get(cat, cat.title())
        lines.append(f"| {label} | {', '.join(techs)} |")
    return "\n".join(lines)


def _section_api_layer(profile) -> str:
    if not profile.api_endpoints:
        return ""
    lines = ["## API Layer", ""]
    # Group by class
    by_class: dict[str, list] = {}
    for ep in profile.api_endpoints:
        cls = ep.get("class", "")
        by_class.setdefault(cls, []).append(ep)
    for cls, eps in by_class.items():
        methods = []
        for ep in eps:
            http = ep.get("http_method", "")
            path = ep.get("path", "")
            if http and http != "CONTROLLER" and path:
                methods.append(f"{http} {path}")
        if methods:
            lines.append(f"- `{cls}` \u2192 {', '.join(methods)}")
        elif cls:
            lines.append(f"- `{cls}` (REST controller)")
    return "\n".join(lines)


def _section_messaging(profile) -> str:
    if not profile.messaging:
        return ""
    lines = ["## Messaging", "",
             "| Direction | Type | Topic | Consumer Group |",
             "|-----------|------|-------|----------------|"]
    for msg in profile.messaging:
        direction = msg.get("direction", "").title()
        msg_type = msg.get("type", "")
        topic = msg.get("topic", "") or "\u2014"
        group = msg.get("group", "") or "\u2014"
        lines.append(f"| {direction} | {msg_type} | {topic} | {group} |")
    return "\n".join(lines)


def _section_data_layer(profile) -> str:
    if not profile.data_stores:
        return ""
    # Collect entities and types
    db_techs = profile.technologies.get("database", [])
    entities = []
    for store in profile.data_stores:
        entities.extend(store.get("entities", []))

    lines = ["## Data Layer", ""]
    if db_techs:
        lines.append(f"- **Database:** {', '.join(db_techs)}")
    if entities:
        lines.append(f"- **Entities:** {', '.join(entities)}")
    return "\n".join(lines)


def _section_caching(profile) -> str:
    cache_techs = profile.technologies.get("cache", [])
    if not cache_techs:
        return ""
    lines = ["## Caching", ""]
    lines.append(f"- **Provider:** {', '.join(cache_techs)}")
    # List cache annotations from observability
    cache_details = [o.get("detail", "") for o in profile.observability if o.get("type") == "cache"]
    if cache_details:
        lines.append(f"- **Cached:** {', '.join(cache_details)}")
    return "\n".join(lines)


def _section_downstream_calls(profile) -> str:
    if not profile.downstream_services:
        return ""
    http_techs = profile.technologies.get("http_client", [])
    lines = ["## Downstream Services", "",
             "| Service | Client | Notes |",
             "|---------|--------|-------|"]
    for svc in profile.downstream_services:
        name = svc.get("name", "")
        client = svc.get("client_type", "")
        url = svc.get("url", "") or ""
        # Check for circuit breaker
        cb = next((t for t in (http_techs or []) if "circuit" in t.lower() or "resilience" in t.lower()), "")
        notes = cb if cb else url
        lines.append(f"| {name} | {client} | {notes} |")
    return "\n".join(lines)


def _section_config_management(profile) -> str:
    config_techs = profile.technologies.get("config", [])
    if not config_techs and not profile.config_sources:
        return ""
    lines = ["## Config Management", ""]
    if config_techs:
        lines.append(f"- {', '.join(config_techs)}")
    refresh_classes = [cs.get("source", "") for cs in profile.config_sources if cs.get("type") == "RefreshScope"]
    if refresh_classes:
        lines.append(f"- @RefreshScope on: {', '.join(refresh_classes)}")
    config_props = [cs for cs in profile.config_sources if cs.get("type") == "ConfigurationProperties"]
    if config_props:
        prefixes = [cs.get("key_prefix", "") for cs in config_props if cs.get("key_prefix")]
        if prefixes:
            lines.append(f"- @ConfigurationProperties: {', '.join(prefixes)}")
    return "\n".join(lines)


def _section_observability_section(profile) -> str:
    obs_techs = profile.technologies.get("observability", [])
    if not obs_techs:
        return ""
    lines = ["## Observability", ""]
    lines.append(f"- {', '.join(obs_techs)}")
    # Custom metrics
    custom = [o for o in profile.observability if o.get("type") in ("Timed", "Counted", "Traced")]
    if custom:
        details = [f"@{o['type']}({o.get('detail', '')})" for o in custom[:5]]
        lines.append(f"- Custom: {', '.join(details)}")
    return "\n".join(lines)


def _section_deployment(profile) -> str:
    if not profile.k8s_resources:
        return ""
    lines = ["## Deployment", ""]
    for res in profile.k8s_resources:
        kind = res.get("kind", "")
        name = res.get("name", "")
        image = res.get("image", "")
        replicas = res.get("replicas", "")
        parts_list = [kind]
        if name:
            parts_list.append(name)
        detail_parts = []
        if image:
            detail_parts.append(image)
        if replicas:
            detail_parts.append(f"{replicas} replicas")
        detail = ", ".join(detail_parts)
        lines.append(f"- **{': '.join(parts_list)}** \u2014 {detail}" if detail else f"- **{': '.join(parts_list)}**")
    return "\n".join(lines)


def _section_security(profile) -> str:
    sec_techs = profile.technologies.get("security", [])
    if not sec_techs:
        return ""
    lines = ["## Security", ""]
    lines.append(f"- {', '.join(sec_techs)}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Trim to budget
# ---------------------------------------------------------------------------

def _trim_to_budget(content: str, max_chars: int = _BUDGET) -> str:
    """Trim content to fit within character budget.

    Strategy:
    1. Remove sections that are purely TODO placeholders (no auto-filled data).
    2. If still over budget, hard truncate with a marker.
    """
    if len(content) <= max_chars:
        return content

    # Split into sections by ## headings
    sections: list[str] = []
    current: list[str] = []
    for line in content.split("\n"):
        if line.startswith("## ") and current:
            sections.append("\n".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append("\n".join(current))

    # Identify TODO-only sections (all non-heading, non-empty lines contain <!-- TODO)
    def _is_todo_only(section: str) -> bool:
        lines = section.strip().split("\n")
        content_lines = [
            l for l in lines
            if l.strip() and not l.startswith("## ") and not l.startswith("```")
        ]
        if not content_lines:
            return True
        return all("<!-- TODO" in l for l in content_lines)

    # Remove TODO-only sections from the end first
    trimmed = list(sections)
    while len("\n\n".join(trimmed)) > max_chars and len(trimmed) > 1:
        # Find last TODO-only section
        removed = False
        for i in range(len(trimmed) - 1, 0, -1):
            if _is_todo_only(trimmed[i]):
                trimmed.pop(i)
                removed = True
                break
        if not removed:
            break

    result = "\n\n".join(trimmed)

    # Hard truncate if still over
    if len(result) > max_chars:
        result = result[:max_chars] + "\n\n[... trimmed to fit budget]\n"

    return result


# ---------------------------------------------------------------------------
# Detection + write
# ---------------------------------------------------------------------------

def detect_existing_knowledge_file(repo_path: str) -> Optional[str]:
    """Check for existing knowledge files. Returns absolute path or None."""
    root = Path(repo_path)
    if not root.is_dir():
        return None

    # Check directory first
    d = root / _REPO_KNOWLEDGE_DIR
    if d.is_dir() and any(d.glob("*.md")):
        return str(d.resolve())

    # Check .code-autonomy.md
    f = root / _REPO_KNOWLEDGE_FILE
    if f.is_file():
        return str(f.resolve())

    # Check AGENT.md
    a = root / _REPO_KNOWLEDGE_ALT_FILE
    if a.is_file():
        return str(a.resolve())

    return None


def write_knowledge_file(repo_path: str, content: str) -> str:
    """Write .code-autonomy.md to the repo root. Returns absolute path."""
    root = Path(repo_path)
    target = root / _REPO_KNOWLEDGE_FILE
    target.write_text(content, encoding="utf-8")
    return str(target.resolve())


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def generate_knowledge_markdown(consciousness: ProjectConsciousness) -> str:
    """Assemble a .code-autonomy.md from ProjectConsciousness data.

    Auto-fills what it can, leaves <!-- TODO --> markers for the rest.
    Enforces a 9,500 character budget.
    """
    conventions = consciousness.conventions or {}
    structure = consciousness.structure or {}
    signatures = consciousness.signatures or []
    samples = consciousness.implementation_samples or []

    parts = [
        "# Repo Knowledge",
        "",
        _section_project_overview(conventions),
        "",
        _section_repository_layout(structure),
        "",
        _section_coding_conventions(conventions),
        "",
        _section_testing(conventions),
        "",
        _section_important_files(signatures, samples),
        "",
        _section_architecture_notes(),
        "",
        _section_domain_context(),
        "",
        _section_things_to_watch(),
    ]

    content = "\n".join(parts)
    return _trim_to_budget(content, _BUDGET)


def generate_skills_markdown(consciousness: ProjectConsciousness, repo_path: str = "") -> str:
    """Assemble a rich SKILLS.md from ProjectConsciousness + stack analysis.

    When repo_path is provided, runs the static stack analyzer to extract
    deep technology profiles (APIs, messaging, caching, databases, etc.).
    Falls back to template-based output when repo_path is empty.

    Enforces a 12,000 character budget.
    """
    conventions = consciousness.conventions or {}
    structure = consciousness.structure or {}
    signatures = consciousness.signatures or []
    samples = consciousness.implementation_samples or []

    # Run stack analysis if repo_path available
    profile = None
    if repo_path:
        try:
            from src.consciousness.stack_analyzer import analyze_stack
            profile = analyze_stack(repo_path, consciousness)
        except Exception:
            pass

    parts = [
        "# SKILLS.md",
        "",
        _section_project_overview(conventions),
    ]

    if profile:
        # Inject app type into overview
        parts.append(_section_app_type(profile))

        # Rich technology stack table
        tech_table = _section_tech_stack_table(profile)
        if tech_table:
            parts.extend(["", tech_table])

        # Conditional sections — only include when data was detected
        for section_fn, check in [
            (_section_api_layer, profile.api_endpoints),
            (_section_messaging, profile.messaging),
            (_section_data_layer, profile.data_stores),
            (_section_caching, profile.technologies.get("cache")),
            (_section_downstream_calls, profile.downstream_services),
            (_section_config_management,
             profile.technologies.get("config") or profile.config_sources),
            (_section_observability_section,
             profile.technologies.get("observability")),
            (_section_deployment, profile.k8s_resources),
            (_section_security, profile.technologies.get("security")),
        ]:
            if check:
                section = section_fn(profile)
                if section:
                    parts.extend(["", section])
    else:
        # Fallback: basic tech stack summary (original behavior)
        lang = conventions.get("language", "unknown")
        build = conventions.get("build_tool", "unknown")
        framework = conventions.get("test_framework", "unknown")
        tech_lines = ["", "## Tech Stack", ""]
        tech_items = []
        if lang != "unknown":
            tech_items.append(f"**Language:** {lang}")
        if build != "unknown":
            tech_items.append(f"**Build tool:** {build}")
        if framework != "unknown":
            tech_items.append(f"**Test framework:** {framework}")
        if tech_items:
            tech_lines.append(" | ".join(tech_items))
        else:
            tech_lines.append("Not detected")
        parts.extend(tech_lines)

    parts.extend(["", _section_repository_layout(structure)])
    parts.extend(["", _section_important_files(signatures, samples)])

    content = "\n".join(parts)
    return _trim_to_budget(content, _SKILLS_BUDGET)
