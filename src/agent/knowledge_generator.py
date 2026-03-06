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
_CLAUDE_BUDGET = 15000  # CLAUDE.md — prescriptive rules for Claude Code

# ---------------------------------------------------------------------------
# Build-command lookup: (language, build_tool) → commands
# ---------------------------------------------------------------------------

_BUILD_COMMANDS: dict[tuple[str, str], dict[str, str]] = {
    ("java", "maven"): {
        "build": "mvn clean package -DskipTests",
        "test": "mvn test",
        "single_test": "mvn test -Dtest={ClassName}",
        "run": "mvn spring-boot:run",
    },
    ("java", "gradle"): {
        "build": "./gradlew build -x test",
        "test": "./gradlew test",
        "single_test": "./gradlew test --tests {ClassName}",
        "run": "./gradlew bootRun",
    },
    ("python", "pip"): {
        "build": "pip install -e .",
        "test": "pytest",
        "single_test": "pytest {file}::{test}",
        "run": "python -m app",
    },
    ("python", "poetry"): {
        "build": "poetry install",
        "test": "poetry run pytest",
        "single_test": "poetry run pytest {file}::{test}",
        "run": "poetry run python -m app",
    },
    ("javascript", "npm"): {
        "build": "npm run build",
        "test": "npm test",
        "single_test": "npx jest {file}",
        "run": "npm start",
    },
    ("javascript", "yarn"): {
        "build": "yarn build",
        "test": "yarn test",
        "single_test": "yarn jest {file}",
        "run": "yarn start",
    },
    ("typescript", "npm"): {
        "build": "npm run build",
        "test": "npm test",
        "single_test": "npx jest {file}",
        "run": "npm start",
    },
    ("typescript", "yarn"): {
        "build": "yarn build",
        "test": "yarn test",
        "single_test": "yarn jest {file}",
        "run": "yarn start",
    },
    ("go", "go"): {
        "build": "go build ./...",
        "test": "go test ./...",
        "single_test": "go test -run {TestName} ./...",
        "run": "go run .",
    },
}


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


# ---------------------------------------------------------------------------
# Prescriptive section generators for CLAUDE.md (consume StackProfile)
# ---------------------------------------------------------------------------

def _resolve_build_commands(conventions: dict, profile) -> dict[str, str]:
    """Resolve build/test/run commands from conventions and profile."""
    lang = conventions.get("language", "").lower()
    build_tool = conventions.get("build_tool", "").lower()
    test_fw = conventions.get("test_framework", "").lower()

    cmds = dict(_BUILD_COMMANDS.get((lang, build_tool), {}))
    if not cmds:
        # Try partial match on language
        for (l, _b), c in _BUILD_COMMANDS.items():
            if l == lang:
                cmds = dict(c)
                break

    # Refine test command based on test framework
    if test_fw:
        if "pytest" in test_fw:
            cmds["test"] = "pytest"
            cmds["single_test"] = "pytest {file}::{test}"
        elif "unittest" in test_fw:
            cmds["test"] = "python -m unittest discover"
            cmds["single_test"] = "python -m unittest {module}.{TestClass}.{test}"
        elif "junit5" in test_fw or "jupiter" in test_fw:
            pass  # maven/gradle defaults are fine
        elif "jest" in test_fw:
            cmds["single_test"] = "npx jest {file}"
        elif "mocha" in test_fw:
            cmds["test"] = "npx mocha"
            cmds["single_test"] = "npx mocha --grep '{pattern}'"

    # Add port from config_properties if available
    if profile and profile.config_properties:
        port = profile.config_properties.get("server.port", "")
        if port and "run" in cmds:
            cmds["run"] = cmds["run"] + f"  # serves on port {port}"

    return cmds


def _claude_section_build_and_test(conventions: dict, profile) -> str:
    """Prescriptive build, test, and run commands."""
    cmds = _resolve_build_commands(conventions, profile)
    if not cmds:
        return "\n".join([
            "## Build & Test",
            "",
            "<!-- TODO: Add build command, e.g. `mvn clean package` -->",
            "<!-- TODO: Add test command, e.g. `mvn test` -->",
        ])

    lines = ["## Build & Test", ""]
    if "build" in cmds:
        lines.append(f"- **Build:** `{cmds['build']}`")
    if "test" in cmds:
        lines.append(f"- **Test:** `{cmds['test']}`")
    if "single_test" in cmds:
        lines.append(f"- **Single test:** `{cmds['single_test']}`")
    if "run" in cmds:
        lines.append(f"- **Run:** `{cmds['run']}`")
    return "\n".join(lines)


def _claude_section_project_structure(structure: dict) -> str:
    """Prescriptive directory layout rules."""
    lines = ["## Project Structure", ""]
    if not structure:
        lines.append("<!-- TODO: Define source and test directories -->")
        return "\n".join(lines)

    tree = _format_structure(structure, indent=0, max_depth=2)
    if len(tree) > 1200:
        tree = tree[:1200] + "\n... (trimmed)"

    # Extract top-level dirs for prescriptive rules
    subdirs = structure.get("subdirs", {})
    src_dirs = [d for d in subdirs if "src" in d.lower()]
    test_dirs = [d for d in subdirs if "test" in d.lower()]

    if src_dirs:
        lines.append(f"- **Source:** `{', '.join(src_dirs)}`")
    if test_dirs:
        lines.append(f"- **Tests:** `{', '.join(test_dirs)}`")
    if not src_dirs and not test_dirs:
        lines.append("```")
        lines.append(tree)
        lines.append("```")
    return "\n".join(lines)


def _claude_section_code_style(conventions: dict) -> str:
    """Prescriptive naming and style rules."""
    naming = conventions.get("naming_style", "")
    lang = conventions.get("language", "").lower()
    lines = ["## Code Style", ""]

    if naming and naming != "unknown":
        lines.append(f"- Use **{naming}** for variables and functions")
    elif lang == "java":
        lines.append("- Use **camelCase** for methods, **PascalCase** for classes")
    elif lang in ("python",):
        lines.append("- Use **snake_case** for functions/variables, **PascalCase** for classes")
    elif lang in ("javascript", "typescript"):
        lines.append("- Use **camelCase** for functions/variables, **PascalCase** for components/classes")
    else:
        lines.append("<!-- TODO: Define naming conventions -->")

    return "\n".join(lines)


def _claude_section_api_rules(profile) -> str:
    """Prescriptive rules for API layer."""
    if not profile or not profile.api_endpoints:
        return ""

    api_techs = profile.technologies.get("api", [])
    lines = ["## API Rules", ""]

    # Detect framework
    if any("spring" in t.lower() for t in api_techs):
        lines.append("- Use `@RestController` for REST endpoints")
        lines.append("- Use `@RequestMapping` or shorthand (`@GetMapping`, `@PostMapping`) for routes")
        lines.append("- Return `ResponseEntity<>` for explicit status codes")
    elif any("flask" in t.lower() for t in api_techs):
        lines.append("- Use `@app.route()` or Blueprint for route definitions")
        lines.append("- Use `jsonify()` for JSON responses")
    elif any("fastapi" in t.lower() for t in api_techs):
        lines.append("- Use `@router` decorators for route definitions")
        lines.append("- Use Pydantic models for request/response validation")
    elif any("express" in t.lower() for t in api_techs):
        lines.append("- Use `router.get/post/put/delete` for route definitions")
        lines.append("- Use `res.json()` for JSON responses")

    # List existing controllers as patterns to follow
    classes = {ep.get("class", "") for ep in profile.api_endpoints if ep.get("class")}
    if classes:
        examples = list(classes)[:3]
        lines.append(f"- Follow the pattern of: `{'`, `'.join(examples)}`")

    return "\n".join(lines)


def _claude_section_messaging_rules(profile) -> str:
    """Prescriptive messaging rules (Kafka, RabbitMQ, etc.)."""
    if not profile or not profile.messaging:
        return ""

    msg_techs = profile.technologies.get("messaging", [])
    lines = ["## Messaging Rules", ""]

    if any("kafka" in t.lower() for t in msg_techs):
        lines.append("- Use `@KafkaListener` with `JsonDeserializer` for consumers")
        lines.append("- Always specify `groupId` on consumer annotations")
        lines.append("- Use `KafkaTemplate` for producers")
    elif any("rabbit" in t.lower() for t in msg_techs):
        lines.append("- Use `@RabbitListener` for consumers")
        lines.append("- Define exchanges and queues in configuration")
    elif any("sqs" in t.lower() for t in msg_techs):
        lines.append("- Use `@SqsListener` for consumers")

    # List existing topics
    topics = {m.get("topic", "") for m in profile.messaging if m.get("topic")}
    if topics:
        lines.append(f"- Existing topics: `{'`, `'.join(t for t in topics if t)}`")

    return "\n".join(lines)


def _claude_section_data_rules(profile) -> str:
    """Prescriptive data-layer rules."""
    if not profile or not profile.data_stores:
        return ""

    db_techs = profile.technologies.get("database", [])
    lines = ["## Data Layer Rules", ""]

    has_jpa = any("jpa" in t.lower() or "hibernate" in t.lower() for t in db_techs)
    has_flyway = any("flyway" in t.lower() for t in db_techs)
    has_liquibase = any("liquibase" in t.lower() for t in db_techs)
    has_sqlalchemy = any("sqlalchemy" in t.lower() for t in db_techs)

    if has_jpa:
        lines.append("- Use `@Entity` with `@Table` for JPA entities")
        lines.append("- Use Spring Data `JpaRepository<>` for data access")
    if has_sqlalchemy:
        lines.append("- Use SQLAlchemy `declarative_base()` models")
        lines.append("- Use sessions via dependency injection")
    if has_flyway:
        lines.append("- Always add a Flyway migration for schema changes (`db/migration/V{N}__{desc}.sql`)")
    if has_liquibase:
        lines.append("- Always add a Liquibase changeset for schema changes")

    # List entities
    entities = []
    for store in profile.data_stores:
        entities.extend(store.get("entities", []))
    if entities:
        lines.append(f"- Existing entities: `{'`, `'.join(entities[:10])}`")

    return "\n".join(lines)


def _claude_section_caching_rules(profile) -> str:
    """Prescriptive caching rules."""
    cache_techs = profile.technologies.get("cache", []) if profile else []
    if not cache_techs:
        return ""

    lines = ["## Caching Rules", ""]
    if any("redis" in t.lower() for t in cache_techs):
        lines.append("- Use `@Cacheable` / `@CacheEvict` for method-level caching")
        lines.append("- Always set TTL — do not cache indefinitely")
        lines.append("- Use Redis as the backing store")
    elif any("ehcache" in t.lower() for t in cache_techs):
        lines.append("- Use `@Cacheable` with Ehcache configuration")
        lines.append("- Always set TTL in ehcache.xml")
    else:
        lines.append(f"- Cache provider: {', '.join(cache_techs)}")
        lines.append("- Always set TTL on cache entries")

    return "\n".join(lines)


def _claude_section_downstream_rules(profile) -> str:
    """Prescriptive rules for calling downstream services."""
    if not profile or not profile.downstream_services:
        return ""

    http_techs = profile.technologies.get("http_client", [])
    lines = ["## Downstream Service Rules", ""]

    has_feign = any("feign" in t.lower() for t in http_techs)
    has_resilience = any("resilience" in t.lower() or "circuit" in t.lower() for t in http_techs)

    if has_feign:
        lines.append("- Use `@FeignClient` for declarative HTTP clients")
    if has_resilience:
        lines.append("- Always wrap external calls with `@CircuitBreaker` (fallback required)")
        lines.append("- Use `@Retry` for transient failures")

    for svc in profile.downstream_services[:5]:
        name = svc.get("name", "")
        client = svc.get("client_type", "")
        if name:
            lines.append(f"- `{name}` — via {client}" if client else f"- `{name}`")

    return "\n".join(lines)


def _claude_section_config_rules(profile) -> str:
    """Prescriptive configuration rules."""
    if not profile:
        return ""
    config_techs = profile.technologies.get("config", [])
    if not config_techs and not profile.config_sources:
        return ""

    lines = ["## Configuration Rules", ""]

    if any("cloud config" in t.lower() or "consul" in t.lower() for t in config_techs):
        lines.append("- Configuration is externalized — do not hardcode values")

    # RefreshScope classes
    refresh = [cs.get("source", "") for cs in profile.config_sources if cs.get("type") == "RefreshScope"]
    if refresh:
        for cls in refresh:
            lines.append(f"- `@RefreshScope` on `{cls}` — do not remove")

    # ConfigurationProperties
    config_props = [cs for cs in profile.config_sources if cs.get("type") == "ConfigurationProperties"]
    if config_props:
        for cp in config_props[:5]:
            prefix = cp.get("key_prefix", "")
            source = cp.get("source", "")
            if prefix and source:
                lines.append(f"- `@ConfigurationProperties(\"{prefix}\")` bound to `{source}`")

    return "\n".join(lines)


def _claude_section_deployment_rules(profile) -> str:
    """Prescriptive deployment rules."""
    if not profile or not profile.k8s_resources:
        return ""

    lines = ["## Deployment Rules", ""]
    for res in profile.k8s_resources[:5]:
        kind = res.get("kind", "")
        name = res.get("name", "")
        image = res.get("image", "")
        replicas = res.get("replicas", "")
        if kind == "Deployment" or kind == "StatefulSet":
            if image:
                lines.append(f"- Docker base image: `{image}`")
            if replicas:
                lines.append(f"- Default replicas: {replicas}")

    # Check for port in config_properties
    if profile.config_properties:
        port = profile.config_properties.get("server.port", "")
        if port:
            lines.append(f"- Application port: {port}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLAUDE.md assembly + write
# ---------------------------------------------------------------------------

def generate_claude_md(consciousness: ProjectConsciousness, repo_path: str = "") -> str:
    """Assemble a prescriptive CLAUDE.md from ProjectConsciousness + stack analysis.

    CLAUDE.md is prescriptive — it tells Claude Code *how* to work in this repo
    with imperative rules like "Use @KafkaListener", "Always add migration".
    Enforces a 15,000 character budget.
    """
    conventions = consciousness.conventions or {}
    structure = consciousness.structure or {}

    # Run stack analysis if repo_path available
    profile = None
    if repo_path:
        try:
            from src.consciousness.stack_analyzer import analyze_stack
            profile = analyze_stack(repo_path, consciousness)
        except Exception:
            pass

    lang = conventions.get("language", "unknown")
    build = conventions.get("build_tool", "unknown")

    parts = [
        "# CLAUDE.md",
        "",
        f"Prescriptive rules for working in this {lang} project.",
        "",
        _claude_section_build_and_test(conventions, profile),
    ]

    parts.extend(["", _claude_section_project_structure(structure)])
    parts.extend(["", _claude_section_code_style(conventions)])

    if profile:
        # Conditional prescriptive sections — only include when data exists
        for section_fn, check in [
            (_claude_section_api_rules, profile.api_endpoints),
            (_claude_section_messaging_rules, profile.messaging),
            (_claude_section_data_rules, profile.data_stores),
            (_claude_section_caching_rules, profile.technologies.get("cache")),
            (_claude_section_downstream_rules, profile.downstream_services),
            (_claude_section_config_rules,
             profile.technologies.get("config") or profile.config_sources),
            (_claude_section_deployment_rules, profile.k8s_resources),
        ]:
            if check:
                section = section_fn(profile)
                if section:
                    parts.extend(["", section])

    content = "\n".join(parts)
    return _trim_to_budget(content, _CLAUDE_BUDGET)


def write_claude_md(repo_path: str, content: str) -> str:
    """Write CLAUDE.md to the repo root. Returns absolute path."""
    root = Path(repo_path)
    target = root / "CLAUDE.md"
    target.write_text(content, encoding="utf-8")
    return str(target.resolve())


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
