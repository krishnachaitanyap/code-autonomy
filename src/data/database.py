"""
Database engine, session factory, and initialization.

Defaults to SQLite at ``~/.code-autonomy/autonomy.db``.
Override with ``DATABASE_URL`` environment variable for PostgreSQL.
"""

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.data.models import Base

_DEFAULT_DB_PATH = Path.home() / ".code-autonomy" / "autonomy.db"
_DEFAULT_URL = f"sqlite:///{_DEFAULT_DB_PATH}"

_engine = None
_SessionFactory = None


def get_database_url() -> str:
    """Resolve the database URL from environment or default."""
    return os.environ.get("DATABASE_URL", _DEFAULT_URL)


def get_engine(url: str = ""):
    """Get or create the SQLAlchemy engine (singleton)."""
    global _engine
    if _engine is None:
        db_url = url or get_database_url()
        # Ensure parent directory exists for SQLite
        if db_url.startswith("sqlite:///"):
            db_path = db_url.replace("sqlite:///", "")
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        connect_args = {}
        if db_url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        _engine = create_engine(db_url, connect_args=connect_args, echo=False)
    return _engine


def get_session_factory(url: str = "") -> sessionmaker:
    """Get or create the session factory (singleton)."""
    global _SessionFactory
    if _SessionFactory is None:
        engine = get_engine(url)
        _SessionFactory = sessionmaker(bind=engine, expire_on_commit=False)
    return _SessionFactory


def init_db(url: str = "") -> None:
    """Create all tables. Safe to call multiple times (idempotent)."""
    engine = get_engine(url)
    Base.metadata.create_all(engine)

    # Migrate existing DBs
    from sqlalchemy import inspect, text
    inspector = inspect(engine)
    if 'sessions' in inspector.get_table_names():
        columns = [c['name'] for c in inspector.get_columns('sessions')]
        if 'log' not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE sessions ADD COLUMN log JSON DEFAULT '[]'"))
    if 'test_runs' in inspector.get_table_names():
        columns = [c['name'] for c in inspector.get_columns('test_runs')]
        if 'branch' not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE test_runs ADD COLUMN branch VARCHAR(256) DEFAULT 'main'"))
    if 'workflows' in inspector.get_table_names():
        columns = [c['name'] for c in inspector.get_columns('workflows')]
        if 'token_budget' not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE workflows ADD COLUMN token_budget INTEGER DEFAULT 0"))
                conn.execute(text("ALTER TABLE workflows ADD COLUMN total_tokens_used INTEGER DEFAULT 0"))
    if 'custom_migration_recipes' in inspector.get_table_names():
        columns = [c['name'] for c in inspector.get_columns('custom_migration_recipes')]
        if 'tool_ids' not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE custom_migration_recipes ADD COLUMN tool_ids JSON DEFAULT '[]'"))
    if 'model_configs' in inspector.get_table_names():
        columns = [c['name'] for c in inspector.get_columns('model_configs')]
        if 'is_system' not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE model_configs ADD COLUMN is_system BOOLEAN DEFAULT 0"))
    # Migrate sessions: add recipe_ids column
    if 'sessions' in inspector.get_table_names():
        columns = [c['name'] for c in inspector.get_columns('sessions')]
        if 'recipe_ids' not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE sessions ADD COLUMN recipe_ids JSON DEFAULT '[]'"))

    if 'repos' in inspector.get_table_names():
        columns = [c['name'] for c in inspector.get_columns('repos')]
        if 'nickname' not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE repos ADD COLUMN nickname VARCHAR(256) DEFAULT ''"))

    # Migrate custom_tools: add model_config_id column
    if 'custom_tools' in inspector.get_table_names():
        columns = [c['name'] for c in inspector.get_columns('custom_tools')]
        if 'model_config_id' not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE custom_tools ADD COLUMN model_config_id VARCHAR(64) REFERENCES model_configs(id)"))

    # Migrate custom_tools: add credential_config column
    if 'custom_tools' in inspector.get_table_names():
        columns = [c['name'] for c in inspector.get_columns('custom_tools')]
        if 'credential_config' not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE custom_tools ADD COLUMN credential_config JSON DEFAULT '{}'"))

    # Seed default tools
    _seed_default_tools(engine)

    # Backfill TestProject.repo_id → ensure every project points to a valid Repo
    _backfill_test_project_repos(engine)


def _seed_default_tools(engine) -> None:
    """Seed built-in custom tools on first run. Skips if they already exist."""
    from sqlalchemy import text

    DEFAULT_TOOLS = [
        {
            "name": "Reference",
            "description": "Reads and surfaces file, directory, or repo content as context for the current task",
            "tool_type": "analyzer",
            "enabled_for_migration": True,
            "enabled_for_chat": True,
            "enabled_for_testing": True,
            "goal": (
                "Read the specified file(s), directory tree, or repository structure "
                "referenced by the user and return their contents as structured context. "
                "Prioritize relevance — summarize large directories, return full content "
                "for individual files, and highlight key entry points for repos."
            ),
            "agent_instructions": (
                "When the user references a file, directory, or repo with @Reference:\n\n"
                "1. **File**: Read the full file contents. If the file exceeds 500 lines, "
                "return the first 100 lines with a summary of the rest and key sections "
                "(exports, classes, functions).\n\n"
                "2. **Directory**: List the directory tree (max 3 levels deep). For each file, "
                "include a one-line description of its purpose inferred from the filename and "
                "any leading comments. Highlight entry points (index.*, main.*, __init__.py, etc.).\n\n"
                "3. **Repository**: Show the top-level structure, README summary if present, and "
                "identify the tech stack, entry points, and key config files "
                "(package.json, pyproject.toml, config.ini, etc.).\n\n"
                "Return the context in this format:\n"
                "---\n"
                "**Referenced**: <path or repo>\n"
                "**Type**: file | directory | repo\n"
                "**Summary**: <1-2 sentence overview>\n"
                "**Contents**:\n"
                "<formatted content>\n"
                "---\n\n"
                "Use the read_file, list_directory, and search_code tools as needed. "
                "Do not modify any files."
            ),
            "allowed_tools": '["Read", "Glob", "Grep", "ListDir", "FindFiles"]',
            "parameters": "{}",
            "tags": '["context", "reference", "default"]',
            "prerequisites": "[]",
            "max_turns": 10,
            "model": "",
            "timeout_seconds": 120,
            "is_active": True,
        },
        {
            "name": "JISI_downstream_detector",
            "description": "Detects downstream dependencies (REST, SOAP, MQ, DB) in a Java/JISI repo or file by scanning code patterns, config keys, and call chains",
            "tool_type": "analyzer",
            "enabled_for_migration": True,
            "enabled_for_chat": True,
            "enabled_for_testing": True,
            "goal": (
                "Scan a repository or specific file to identify all downstream dependencies — "
                "REST calls, SOAP/RPC invocations, MQ messaging, and database access. "
                "Follow service/factory chains from controllers through to remote/data modules. "
                "Produce a structured downstream inventory with evidence links and confidence ratings."
            ),
            "agent_instructions": (
                "You are a JISI downstream dependency detector. Given a repo path or file path, "
                "systematically scan for all external downstream calls.\n\n"
                "## CRITICAL: Deep Call-Chain Traversal Strategy\n\n"
                "JISI call chains can be 15-20+ files deep (Controller → Invoker → Service → "
                "Factory → Helper → Remote/DAO → External). You MUST follow these chains to "
                "their full depth. Use these strategies to maximize coverage within your budget:\n\n"
                "### Efficiency Rules\n"
                "1. **Grep-first, read-second**: Use Grep to find ALL occurrences of a pattern "
                "across the entire repo before reading individual files. This discovers the full "
                "call graph in one turn instead of reading files one by one.\n"
                "2. **Batch tool calls**: In each turn, invoke MULTIPLE tools simultaneously — "
                "e.g., grep for RESTProxy AND RPCProxy AND ConnectionFactory in parallel.\n"
                "3. **Follow imports aggressively**: When you find a class reference like "
                "`FooService.doSomething()`, immediately grep for `class FooService` to find "
                "the implementation, then grep inside that file for further downstream calls.\n"
                "4. **Chain tracking**: Maintain a mental map of the call chain. Do NOT stop "
                "at intermediate layers. If file A calls B, B calls C, C calls D... keep going "
                "until you reach the actual external call (REST/SOAP/MQ/DB pattern).\n"
                "5. **Do NOT wrap up early**: You have a large turn budget. Use it. Keep tracing "
                "call chains even past the midpoint of your budget. Only compile the final "
                "output when you are confident you have traced ALL chains to their endpoints.\n\n"
                "## Detection Rules\n\n"
                "### A) REST Downstream\n"
                "Search for these patterns:\n"
                "- `RESTProxy.getInstance(...).invoke(...)` calls\n"
                "- `ChannelUtil.getChannelProperty(...)` + service key references\n"
                "- Service URL keys in app.properties (e.g. lines containing REST endpoint URLs)\n"
                "- Config keys matching `*.rest.url` in app.properties\n\n"
                "### B) SOAP Downstream\n"
                "Search for these patterns:\n"
                "- `RPCProxy.getInstance(...)` calls\n"
                "- SOAP port types (`*PortType` classes/interfaces)\n"
                "- `SoapFault`, `BindingProvider` references\n"
                "- `*.stub.url` / `*.stub.class` keys in app.properties\n\n"
                "### C) MQ Downstream\n"
                "Search for these patterns:\n"
                "- `com.cig.jisi.mq.ConnectionFactory` usage\n"
                "- `Poster`, `QueueManager`, `TextMessage`, `MQException` references\n"
                "- Properties matching `jisi.audit.mq.*` pattern\n\n"
                "### D) DB Downstream\n"
                "Search for these patterns:\n"
                "- Direct JDBC: `PreparedStatement`, SQL string literals\n"
                "- Dynamic table names via properties\n"
                "- Config keys matching `*.ds.name`, schema/table properties\n\n"
                "## Execution Steps\n\n"
                "1. **Scan app.properties** first — extract all URL keys, stub keys, MQ keys, "
                "and datasource keys. This is the primary config source.\n"
                "2. **Broad grep sweep**: Run grep for ALL detection patterns (REST, SOAP, MQ, DB) "
                "across the entire Java source tree in parallel. This gives you the full set of "
                "files that contain downstream markers.\n"
                "3. **Scan Java source files** for the code patterns listed above. "
                "For each match, record the file path, line number, class name, and method.\n"
                "4. **Follow call chains to full depth**: trace from Controller → Invoker → "
                "Service → Factory → Helper → Remote/DAO → External/DB → Response. "
                "Do NOT stop at intermediate layers. If a method delegates to another class, "
                "grep for that class and continue. Map each downstream call to its "
                "config key where possible. Chains can be 15-20 files deep — follow them all.\n"
                "5. **Classify confidence**:\n"
                "   - **High**: Direct pattern match with config key resolved\n"
                "   - **Medium**: Pattern match but config key unresolved or indirect\n"
                "   - **Low**: Inferred from imports/types only, no direct invocation found\n\n"
                "## Output Format\n\n"
                "The user can request one of three output formats via the `output_format` "
                "parameter or by stating it in their message. Default is `both`.\n\n"
                "**Detect the format from the user's message:**\n"
                "- If they say 'markdown', 'text', 'table' → use `markdown` format\n"
                "- If they say 'mermaid', 'diagram', 'visual', 'chart' → use `mermaid` format\n"
                "- If they say 'both' or don't specify → use `both` format\n\n"
                "---\n\n"
                "### Always include: Executive Summary\n"
                "Provide counts by type: REST, SOAP, MQ, DB.\n"
                "Provide confidence split: High/Medium/Low counts.\n\n"
                "---\n\n"
                "### FORMAT: `markdown` (text tables + traces)\n\n"
                "**Downstream Inventory Table**\n"
                "| Type | Caller (class.method) | Target system/client | "
                "Endpoint/Operation/Queue/Table | Protocol | Config key | "
                "Evidence link (file:line) | Confidence | Notes |\n\n"
                "**Endpoint Trace Sections** (at least 2):\n"
                "```\n"
                "Client → Controller → Invoker → Service → Remote/DAO → External/DB → Response\n"
                "```\n\n"
                "**Open Gaps** — list anything unresolved as Unknown.\n\n"
                "---\n\n"
                "### FORMAT: `mermaid` (diagrams only)\n\n"
                "**Downstream Dependency Flowchart:**\n"
                "```mermaid\n"
                "graph LR\n"
                "  subgraph Application\n"
                "    Controller[\"ControllerName\"]\n"
                "    Service[\"ServiceName\"]\n"
                "  end\n"
                "  subgraph REST Downstreams\n"
                "    REST1[\"TargetSystem<br/>endpoint\"]\n"
                "  end\n"
                "  subgraph SOAP Downstreams\n"
                "    SOAP1[\"TargetService<br/>operation\"]\n"
                "  end\n"
                "  subgraph MQ Downstreams\n"
                "    MQ1[\"QueueName\"]\n"
                "  end\n"
                "  subgraph DB Downstreams\n"
                "    DB1[(\"TableName\")]\n"
                "  end\n"
                "  Controller --> Service\n"
                "  Service -->|REST| REST1\n"
                "  Service -->|SOAP| SOAP1\n"
                "  Service -->|MQ| MQ1\n"
                "  Service -->|JDBC| DB1\n"
                "```\n"
                "Diagram rules:\n"
                "- Group nodes by downstream type using subgraphs\n"
                "- Label edges with the protocol (REST, SOAP, MQ, JDBC)\n"
                "- Use cylinder shape `[(...)]` for DB nodes\n"
                "- Use actual class/service names from the code, not placeholders\n"
                "- Solid edges `-->` for high-confidence, dotted `-.->` for low-confidence\n\n"
                "**Endpoint Trace Sequence Diagrams** (at least 2):\n"
                "```mermaid\n"
                "sequenceDiagram\n"
                "  Client->>Controller: request\n"
                "  Controller->>Service: invoke\n"
                "  Service->>Remote: downstream call\n"
                "  Remote-->>Service: response\n"
                "  Service-->>Controller: result\n"
                "  Controller-->>Client: response\n"
                "```\n\n"
                "---\n\n"
                "### FORMAT: `both` (default — all of the above)\n"
                "Include the full markdown inventory table AND mermaid diagrams.\n\n"
                "## Quality Constraints\n"
                "- Do NOT infer unknown endpoints/queues/tables — only report what is evidenced.\n"
                "- No generic statements; every row must have evidence line links.\n"
                "- Deduplicate equivalent downstreams called from multiple places.\n"
                "- Separate internal module calls from real external downstream dependencies.\n"
                "- If a file path is given (not full repo), focus on that file's execution path "
                "and trace which downstreams it may invoke."
            ),
            "allowed_tools": '["Read", "Glob", "Grep", "ListDir", "FindFiles", "Bash"]',
            "parameters": '{"output_format": {"type": "string", "enum": ["markdown", "mermaid", "both"], "default": "both", "description": "Output format: markdown (text tables), mermaid (diagrams), or both"}}',
            "tags": '["jisi", "downstream", "dependency", "analysis", "java", "default"]',
            "prerequisites": "[]",
            "max_turns": 75,
            "model": "",
            "timeout_seconds": 600,
            "is_active": True,
        },
        {
            "name": "Skill_Extractor",
            "description": "Learns framework contracts and repo conventions by downloading and inspecting dependency source code, then stores reusable skill documents",
            "tool_type": "analyzer",
            "enabled_for_migration": True,
            "enabled_for_chat": True,
            "enabled_for_testing": True,
            "goal": (
                "Download framework/library dependency sources, inspect their contracts "
                "(abstract methods, annotations, lifecycle hooks, configuration patterns), "
                "cross-reference with the target repo's conventions (test structure, naming, "
                "config files), and produce a comprehensive skill document that enables "
                "accurate code generation matching both framework rules and repo style."
            ),
            "agent_instructions": (
                "You are a Skill Extractor. Your job is to learn how a framework or library "
                "works by reading its actual source code, then combine that with the target "
                "repo's conventions to produce a reusable skill document.\n\n"
                "## EFFICIENCY RULES (read first)\n"
                "- **list_dependencies first**: Always start with list_dependencies to get the "
                "exact dependency coordinates and auto-detected frameworks. This saves turns.\n"
                "- **Batch grep**: When scanning the repo, search for ALL framework-related "
                "patterns in parallel (annotations, imports, base classes) in one turn. "
                "Do NOT search one pattern per turn.\n"
                "- **Read selectively**: After grep finds matches, read only the most representative "
                "files (2-3 per pattern). Do not read every match.\n"
                "- **Extract JARs efficiently**: List JAR contents once with `jar tf`, then extract "
                "only the key classes (base classes, annotations, config processors).\n\n"
                "## ANTI-HALLUCINATION RULES (critical)\n"
                "- **Every claim needs a source citation**: file path + line number or class name.\n"
                "- **If you cannot find the source, say so**: Write 'NOT VERIFIED — could not locate "
                "source for <X>' rather than guessing.\n"
                "- **Verify method signatures**: Copy-paste the actual signature from source code. "
                "Do NOT reconstruct from memory or inference.\n"
                "- **Verify annotations**: Read the actual annotation source to confirm attributes "
                "and default values. Do NOT assume based on naming.\n"
                "- **Test your claims**: Before publishing, re-read at least 2 repo files that use "
                "the framework and confirm your skill document matches what they actually do.\n\n"
                "## Step 0: Inventory and classify dependencies\n"
                "Call **list_dependencies** to get all dependencies classified as:\n"
                "- **INTERNAL/ENTERPRISE** — not in LLM training data, MUST download and inspect sources\n"
                "- **WELL-KNOWN** — LLM already knows these (Spring, JUnit, etc.), skip source download\n\n"
                "For well-known frameworks, you already know the API. Only document how THIS REPO "
                "uses them (conventions, patterns, config). Do NOT waste turns downloading Spring sources.\n\n"
                "For internal/enterprise frameworks, proceed to Steps 1-2 to download and inspect.\n\n"
                "## Step 1: Download enterprise dependency sources\n"
                "Call **download_dependencies** to fetch source JARs ONLY for internal dependencies.\n"
                "If this fails, explain what artifact repository configuration is needed.\n"
                "Skip this step entirely if all dependencies are well-known.\n\n"
                "## Step 2: Deep-inspect enterprise framework source code\n"
                "Only for INTERNAL dependencies. Find and extract key classes:\n"
                "- For Maven: `~/.m2/repository/{groupId path}/{artifactId}/{version}/*-sources.jar`\n"
                "- Run: `jar tf <sources.jar> | grep -E '(Base|Abstract|Service|Config|Annotation)'`\n"
                "- Extract key classes: `jar xf <sources.jar> <class-path> -d /tmp/extracted/`\n"
                "- Read and document:\n"
                "  - **Abstract base classes**: every abstract method with full signature\n"
                "  - **Annotations**: all attributes, defaults, retention, target\n"
                "  - **Lifecycle interfaces**: init/destroy/callback hooks with execution order\n"
                "  - **Configuration**: required properties, injection points, defaults\n"
                "  - **Exception hierarchy**: what exceptions the framework throws and when\n"
                "- For each finding, record: `Source: <jar-name>/<class-path>:<line>`\n\n"
                "## Step 3: Batch-scan repo for framework usage\n"
                "Run **parallel greps** in a single turn to find all framework usage:\n"
                "- Imports: `grep -r 'import com.enterprise.framework'`\n"
                "- Annotations: `grep -rn '@FrameworkAnnotation'`\n"
                "- Base class extensions: `grep -rn 'extends ServiceBase'`\n"
                "- Config references: `grep -rn 'framework.config.key'`\n"
                "Then read the top 2-3 most representative files per category.\n\n"
                "## Step 4: Cross-reference and verify\n"
                "For each framework contract point found in Step 2:\n"
                "1. Find at least one repo file that implements/uses it\n"
                "2. Verify the repo's usage matches the framework's contract\n"
                "3. Note any repo-specific patterns (wrappers, utilities, naming overrides)\n"
                "4. If a contract point has zero usage in the repo, note it as 'UNUSED in this repo'\n\n"
                "**Verification pass**: Re-read 2-3 repo files end-to-end and confirm every "
                "claim in your skill document against the actual code. Fix any discrepancies.\n\n"
                "## Step 5: Store in working memory\n"
                "Use update_memory with key 'skill:<framework_name>'.\n\n"
                "## Step 6: Publish to SKILLS.md\n"
                "Use the **publish_skill** tool to persist to the repo's SKILLS.md.\n"
                "This makes it visible in the Repos UI and auto-injected into future sessions.\n\n"
                "**Structure the skill_content with these sections:**\n\n"
                "### Contract\n"
                "For each base class/interface/annotation, include:\n"
                "- Full method signature (copy-pasted from source)\n"
                "- Purpose and when it's called\n"
                "- Source citation: `Source: <jar>/<path>:<line>`\n\n"
                "### Repo Conventions\n"
                "For each convention, include:\n"
                "- The pattern with a repo file example: `Example: see src/.../OrderService.java:45`\n"
                "- Package structure, naming rules, config locations\n\n"
                "### Code Generation Guide\n"
                "- Step-by-step recipe with a concrete template\n"
                "- Based on an actual repo file as the canonical pattern\n"
                "- Mark placeholders clearly: `<ServiceName>`, `<endpoint-path>`\n\n"
                "### Pitfalls\n"
                "- Only include pitfalls you found evidence for (missing config, wrong annotation usage)\n"
                "- Cite the source where you discovered each pitfall\n\n"
                "### Evidence Index\n"
                "List all source files consulted with what was learned from each:\n"
                "- `<jar>/<class>` — what contract points were extracted\n"
                "- `<repo-file>` — what conventions were observed"
            ),
            "allowed_tools": '["Read", "Glob", "Grep", "ListDir", "FindFiles", "Bash", "list_dependencies", "download_dependencies", "publish_skill"]',
            "parameters": '{"framework": {"type": "string", "description": "Framework or library name to extract skills for (e.g. SmartSpec, Spring Boot, jules)"}, "focus_area": {"type": "string", "description": "Optional: specific area to focus on (e.g. testing, configuration, service contracts)"}}',
            "tags": '["skill", "framework", "dependency", "learning", "default"]',
            "prerequisites": "[]",
            "max_turns": 60,
            "model": "",
            "timeout_seconds": 600,
            "is_active": True,
        },
        {
            "name": "Splunk",
            "description": "Query production Splunk logs, metrics, and saved searches using SPL or natural language",
            "tool_type": "analyzer",
            "enabled_for_migration": False,
            "enabled_for_chat": True,
            "enabled_for_testing": False,
            "goal": (
                "Query Splunk to answer questions about production logs, metrics, errors, "
                "performance, and system behavior. Supports SPL queries, saved searches, "
                "and natural language questions that are auto-translated to SPL."
            ),
            "agent_instructions": (
                "You are a Splunk query specialist with access to production log data.\n\n"
                "## Available Sub-Tools\n"
                "When this tool is active, you have access to these Splunk tools:\n"
                "- **splunk_ask(question)** — One-shot pipeline: discovers metadata, generates SPL, "
                "executes, returns results. Best for quick answers.\n"
                "- **splunk_discover(query)** — Search OpenSearch for relevant Splunk indexes, "
                "fields, sourcetypes. ALWAYS call this first before writing custom SPL.\n"
                "- **splunk_search(spl)** — Run an SPL query. Use metadata from splunk_discover.\n"
                "- **splunk_stats(spl, chart_type?)** — Run SPL aggregation for charts.\n"
                "- **splunk_saved_search(name?)** — List or run saved searches.\n\n"
                "## Workflow\n"
                "1. For simple questions, use splunk_ask for a quick one-shot answer\n"
                "2. For complex queries, first splunk_discover to find indexes/fields, "
                "then splunk_search or splunk_stats with precise SPL\n"
                "3. Always use exact index/sourcetype/field names from discover results\n"
                "4. For charts, use splunk_stats with timechart/stats/chart commands\n\n"
                "## Authentication\n"
                "Credentials are configured via the tool's Authentication section. "
                "Supports Splunk username/password via direct entry or config profile."
            ),
            "allowed_tools": '["Read", "Grep"]',
            "parameters": '{}',
            "credential_config": '{"auth_type": "basic"}',
            "tags": '["splunk", "logs", "monitoring", "observability", "default"]',
            "prerequisites": "[]",
            "max_turns": 15,
            "model": "",
            "timeout_seconds": 120,
            "is_active": False,
        },
    ]

    with engine.begin() as conn:
        for tool_def in DEFAULT_TOOLS:
            existing = conn.execute(
                text("SELECT id FROM custom_tools WHERE name = :name"),
                {"name": tool_def["name"]},
            ).fetchone()
            if existing:
                # Update existing default tools with latest instructions/limits
                conn.execute(text(
                    "UPDATE custom_tools SET "
                    "agent_instructions = :agent_instructions, "
                    "allowed_tools = :allowed_tools, "
                    "max_turns = :max_turns, "
                    "timeout_seconds = :timeout_seconds, "
                    "updated_at = CURRENT_TIMESTAMP "
                    "WHERE name = :name"
                ), {
                    "name": tool_def["name"],
                    "agent_instructions": tool_def["agent_instructions"],
                    "allowed_tools": tool_def.get("allowed_tools", "[]"),
                    "max_turns": tool_def["max_turns"],
                    "timeout_seconds": tool_def["timeout_seconds"],
                })
                continue
            from src.data.models import _uuid
            insert_data = {"id": _uuid(), **tool_def}
            # Ensure credential_config has a default value
            if "credential_config" not in insert_data:
                insert_data["credential_config"] = "{}"
            conn.execute(text(
                "INSERT INTO custom_tools "
                "(id, name, description, tool_type, "
                "enabled_for_migration, enabled_for_chat, enabled_for_testing, "
                "goal, agent_instructions, allowed_tools, parameters, "
                "credential_config, "
                "tags, prerequisites, max_turns, model, timeout_seconds, is_active, "
                "created_at, updated_at) "
                "VALUES (:id, :name, :description, :tool_type, "
                ":enabled_for_migration, :enabled_for_chat, :enabled_for_testing, "
                ":goal, :agent_instructions, :allowed_tools, :parameters, "
                ":credential_config, "
                ":tags, :prerequisites, :max_turns, :model, :timeout_seconds, :is_active, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ), insert_data)

        # Seed default recipes that bundle tools (inside same connection)
        _seed_default_recipes(conn)


def _seed_default_recipes(conn) -> None:
    """Seed built-in recipes that reference default tools. Skips if they already exist."""
    from sqlalchemy import text
    from src.data.models import _uuid

    DEFAULT_RECIPES = [
        {
            "name": "Skill Extraction",
            "category": "general",
            "description": (
                "Learn how a framework or library works by downloading its source code "
                "from the enterprise artifact repository, inspecting contracts and conventions, "
                "and storing a reusable skill document for future code generation."
            ),
            "priority": 70,
            "tags": '["skill", "framework", "dependency", "learning", "artifact-repo"]',
            "prerequisites": "[]",
            "agent_instructions": (
                "Use the @Skill_Extractor tool to learn a framework's contracts and conventions.\n\n"
                "**Workflow:**\n"
                "1. First, call download_dependencies to fetch dependency source JARs from the "
                "configured enterprise artifact repository\n"
                "2. Inspect the framework's source code — find abstract base classes, required "
                "annotations, lifecycle hooks, and configuration patterns\n"
                "3. Cross-reference with the target repo — how does this repo use the framework? "
                "What naming conventions, test patterns, and configuration styles are used?\n"
                "4. Store the skill in working memory via update_memory with key 'skill:<framework>'\n"
                "5. **Publish to SKILLS.md** using the publish_skill tool — this persists the skill "
                "to the repo's SKILLS.md file, making it visible in the Repos UI and automatically "
                "injected into all future agent sessions. Existing skills are preserved.\n\n"
                "**The skill document should enable accurate code generation** that matches both "
                "the framework's rules AND the repo's conventions. Include:\n"
                "- Required method signatures and their purposes\n"
                "- Annotation usage patterns with examples from the repo\n"
                "- Test structure and naming conventions\n"
                "- Configuration file patterns\n"
                "- Common pitfalls and framework-specific rules\n\n"
                "**Prerequisites:** Artifact Repository must be configured in Settings > Config > "
                "Artifact Repository with the enterprise Maven/npm registry URL and credentials."
            ),
            "source_framework": "",
            "target_framework": "",
            "tool_name": "Skill_Extractor",
        },
        {
            "name": "JISI Downstream Analysis",
            "category": "java",
            "description": (
                "Scan a JISI/Java repository to detect all downstream dependencies — "
                "REST, SOAP, MQ, and DB — with mermaid diagrams and evidence links."
            ),
            "priority": 80,
            "tags": '["jisi", "downstream", "dependency", "mermaid", "analysis"]',
            "prerequisites": "[]",
            "agent_instructions": (
                "Use the @JISI_downstream_detector tool instructions to scan this repo. "
                "Focus on producing:\n"
                "1. A mermaid flowchart showing all downstream dependencies grouped by type\n"
                "2. Sequence diagrams for the top 2-3 most critical call chains\n"
                "3. The inventory table with evidence links\n"
                "4. Open gaps and unresolved dependencies\n\n"
                "Start by scanning app.properties for config keys, then trace through "
                "the Java source to find the actual invocation patterns."
            ),
            "source_framework": "JISI",
            "target_framework": "",
            "tool_name": "JISI_downstream_detector",  # resolved to tool_ids at insert time
        },
    ]

    for recipe_def in DEFAULT_RECIPES:
        existing = conn.execute(
            text("SELECT id FROM custom_migration_recipes WHERE name = :name"),
            {"name": recipe_def["name"]},
        ).fetchone()
        if existing:
            continue

        # Resolve tool name to tool ID
        tool_ids = "[]"
        tool_name = recipe_def.pop("tool_name", None)
        if tool_name:
            tool_row = conn.execute(
                text("SELECT id FROM custom_tools WHERE name = :name"),
                {"name": tool_name},
            ).fetchone()
            if tool_row:
                tool_ids = f'["{tool_row[0]}"]'

        conn.execute(text(
            "INSERT INTO custom_migration_recipes "
            "(id, name, category, description, priority, tags, prerequisites, "
            "agent_instructions, source_framework, target_framework, tool_ids, "
            "created_at, updated_at) "
            "VALUES (:id, :name, :category, :description, :priority, :tags, :prerequisites, "
            ":agent_instructions, :source_framework, :target_framework, :tool_ids, "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ), {
            "id": _uuid(),
            "name": recipe_def["name"],
            "category": recipe_def["category"],
            "description": recipe_def["description"],
            "priority": recipe_def["priority"],
            "tags": recipe_def["tags"],
            "prerequisites": recipe_def["prerequisites"],
            "agent_instructions": recipe_def["agent_instructions"],
            "source_framework": recipe_def["source_framework"],
            "target_framework": recipe_def["target_framework"],
            "tool_ids": tool_ids,
        })


def _backfill_test_project_repos(engine) -> None:
    """Ensure every TestProject has a valid repo_id pointing to an existing Repo."""
    from sqlalchemy import text

    with engine.begin() as conn:
        # Find test_projects with NULL repo_id or repo_id not in repos table
        rows = conn.execute(text(
            "SELECT tp.id, tp.repo_id, tp.repo_url, tp.local_path "
            "FROM test_projects tp "
            "LEFT JOIN repos r ON tp.repo_id = r.id "
            "WHERE tp.repo_id IS NULL OR r.id IS NULL"
        )).fetchall()

        if not rows:
            return

        from src.agent.knowledge import compute_repo_id

        for row in rows:
            tp_id, old_repo_id, repo_url, local_path = row
            new_repo_id = compute_repo_id(local_path or "", repo_url or "")

            # Create Repo record if it doesn't exist
            existing = conn.execute(
                text("SELECT id FROM repos WHERE id = :rid"),
                {"rid": new_repo_id},
            ).fetchone()

            if not existing:
                platform = "local"
                url = repo_url or ""
                if "github.com" in url:
                    platform = "github"
                elif "bitbucket" in url:
                    platform = "bitbucket"
                conn.execute(text(
                    "INSERT INTO repos (id, url, local_path, platform, created_at, updated_at) "
                    "VALUES (:id, :url, :lp, :platform, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ), {"id": new_repo_id, "url": url, "lp": local_path or "", "platform": platform})

            # Update the test_project to point to the valid repo
            conn.execute(text(
                "UPDATE test_projects SET repo_id = :rid WHERE id = :tid"
            ), {"rid": new_repo_id, "tid": tp_id})


@contextmanager
def get_session(url: str = "") -> Generator[Session, None, None]:
    """Context manager yielding a SQLAlchemy session with auto-commit/rollback."""
    factory = get_session_factory(url)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine() -> None:
    """Reset the global engine and session factory (for testing)."""
    global _engine, _SessionFactory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionFactory = None
