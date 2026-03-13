"""
Agent-based code analysis with tool use (Claude-Code-like).

The agent iteratively explores, edits, tests, and fixes code within a single
agentic loop.  Supports OpenAI, Anthropic, Gemini via the unified LLM client.
"""

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.agent.tools import build_agent_tools, build_plan_tools, build_ask_tools, execute_tool, execute_plan_tool, execute_ask_tool, AGENT_TOOLS
from src.agent.knowledge import (
    WorkingMemory, load_knowledge, save_knowledge, save_knowledge_with_outcome,
    get_fix_suggestions, compute_repo_id,
    save_checkpoint, load_checkpoint, clear_checkpoint, compute_requirement_hash,
)
from src.agent.gcc import GCCController
from src.agent.ai_utils import parse_ai_changes
from src.agent.activity import log_agent_activity, log_agent_tool_start, summarize_tool_result
from src.agent.tracing import (
    TraceCollector,
    FileTraceStore,
    get_trace_store,
    is_tracing_enabled,
    _sanitize_tool_args,
    _summarize_output,
    SPAN_LLM_CALL,
    SPAN_TOOL_CALL,
    SPAN_GCC_COMMAND,
    SPAN_CONTEXT_MGMT,
    SPAN_STUCK_DETECT,
    SPAN_SESSION,
)


# ---------------------------------------------------------------------------
# Trace save helper — fire-and-forget to avoid blocking the result
# ---------------------------------------------------------------------------

def _save_trace_async(trace, config):
    """Save trace in a daemon thread so it never blocks the agent result."""
    import threading

    def _do_save():
        try:
            store = get_trace_store(config)
            trace_path = store.save(trace)
            print(f"  [trace] Saved: {trace_path} ({trace.metrics.get('total_spans', 0)} spans)")
        except Exception as exc:
            print(f"  [trace] Failed to save trace: {exc}")

    t = threading.Thread(target=_do_save, daemon=True)
    t.start()


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------

@dataclass
class AgentResult:
    """Result from the agent loop."""

    success: bool = False
    files_changed: list[str] = field(default_factory=list)
    summary: str = ""
    turns_used: int = 0
    tests_passed: bool = False
    # Backward-compat: populated only when the agent falls back to legacy
    # JSON-output mode (no write tools used).
    changes: list[dict] = field(default_factory=list)
    # Execution trace ID (for retrieving the full trace from the store)
    trace_id: str = ""
    # LLM token usage statistics (populated when stats tracking is enabled)
    usage_stats: "LLMUsageStats | None" = None
    # Checkpoint from an incomplete run (populated when agent exhausts turns)
    checkpoint: "Checkpoint | None" = None
    # Working memory accumulated during the run (file notes, patterns, etc.)
    working_memory: dict[str, str] = field(default_factory=dict)
    # True when the run ended before task_complete — summary has partial results
    partial: bool = False
    # True when a checkpoint was saved and further exploration would yield more
    can_explore_deeper: bool = False


@dataclass
class PlanResult:
    """Result from the plan-mode agent loop."""

    success: bool = False
    plan: "ChangePlan | None" = None
    summary: str = ""
    turns_used: int = 0
    trace_id: str = ""
    usage_stats: "LLMUsageStats | None" = None
    partial: bool = False
    can_explore_deeper: bool = False


@dataclass
class AskResult:
    """Result from ask-mode agent loop."""

    success: bool = False
    answer: str = ""
    sources: list[str] = field(default_factory=list)
    summary: str = ""
    turns_used: int = 0
    trace_id: str = ""
    usage_stats: "LLMUsageStats | None" = None
    partial: bool = False
    can_explore_deeper: bool = False


# ---------------------------------------------------------------------------
# Guard: abort after N consecutive empty LLM responses
# ---------------------------------------------------------------------------
MAX_CONSECUTIVE_EMPTY = 3
MAX_CONSECUTIVE_API_ERRORS = 3


def _format_tool_breakdown(tool_call_counts: dict, tool_errors: dict) -> list[str]:
    """Format tool call counts for end-of-run report."""
    if not tool_call_counts:
        return []
    lines = [f"Tool calls ({sum(tool_call_counts.values())} total):"]
    for tname in sorted(tool_call_counts, key=tool_call_counts.get, reverse=True):
        err_suffix = f" ({tool_errors.get(tname, 0)} errors)" if tool_errors.get(tname, 0) else ""
        lines.append(f"  - {tname}: {tool_call_counts[tname]}{err_suffix}")
    return lines


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert software engineer with tools to explore AND modify the codebase.

## Read tools (explore the codebase)
- read_file(path, start_line?, end_line?): Read file contents
- grep(pattern, path_filter?, context_lines?): Search for a pattern across code files
- list_dir(path): List directory contents (use "" for repo root)
- find_files(extension?, pattern?): Find files by extension or glob

## Write tools (make changes)
- write_file(path, content): Create a new file or overwrite completely
- edit_file(path, old_string, new_string): Surgical edit — find the *exact* old_string (must be unique in the file) and replace with new_string
- delete_file(path): Delete a file

## Execution tools
- run_command(command, timeout?): Run a shell command (tests, builds, etc.) sandboxed to the repo directory

## Memory tools
- update_memory(key, content): Write a note to working memory. Notes survive context compression and are saved when you call task_complete. Use keys: 'project_overview', 'key_patterns', 'file_notes', or any custom key.
- read_memory(): Read all notes from working memory and prior knowledge from previous runs.

## Code intelligence tools (available when code index is built)
- find_callers(symbol_name): Find all callers of a function/method/class
- find_dependents(file_path): Find all files that import from a given file
- impact_analysis(file_path): Callers + dependents + related tests for a file
- describe_entity(symbol_name): Full signature, docstring, callers, callees
- find_similar(query, top_k?): Semantic search across all code entities
- context_for_edit(file_path, symbol_name?, intent?): Pre-edit context — callers, callees, dependents, hierarchy, tests
- predict_breakage(file_path, changes_description?): Risk report — what callers/children/dependents will break

## Completion
- task_complete(summary, files_changed): Call when ALL changes are done and verified

## Workflow
1. **EXPLORE** — Use read tools to understand the codebase structure, conventions, and the files relevant to the requirements.
2. **RECORD** — After exploring, use update_memory to record what you learn (project overview, patterns, important files).
3. **IMPLEMENT** — Use write/edit tools to make changes incrementally. Prefer edit_file for existing files (surgical, not full replacement). Use write_file only for brand-new files.
4. **VERIFY** — Run tests with run_command after making changes (e.g., `pytest -v`, `mvn test`).
5. **FIX** — If tests fail, read the error output, edit files to fix the issues, and re-run tests.
6. **COMPLETE** — Call task_complete with a summary and the list of files changed.

## Working with large files (properties, config, XML, CSV, etc.)
Files over ~2000 lines WILL be truncated if you read them fully.
**Do NOT repeatedly read_file on large files hoping to see more.** Instead:
1. Use `grep(property_name)` to find the exact line number and surrounding context.
2. Use `read_file(path, start_line, end_line)` with a reasonable range (e.g. ±1000 lines around the match).
3. Use `edit_file` with the exact old_string from that read.
4. To ADD a new property: grep for a nearby existing property in the same section, read that area, then edit_file to insert your new line after it.
5. If grep returns no matches, the property does NOT exist in the file yet — you need to add it.
Most source files (under ~2000 lines) can be read fully in one call — no need for line ranges on normal-sized files.

## Property defaults in Java/Spring projects
When a property is NOT present in a config file (env.properties, application.yml, etc.), Java code
typically uses a hardcoded default value. Common patterns:
- `@Value("${prop.name:defaultValue}")` — Spring annotation with default after colon
- `env.getProperty("prop.name", "default")` — Environment.getProperty with fallback
- `config.getOrDefault("prop.name", "default")` — Map-style lookup
- `Optional.ofNullable(props.get("key")).orElse("default")` — Optional fallback

When adding a new property:
1. First grep the Java source for the property name to find where it's consumed and what default is used.
2. Add the property to the config file with the appropriate value.
3. If the Java code does NOT reference the property yet, you need to add both the config entry AND the Java code that reads it.
4. Record these patterns in working memory with `update_memory("property_patterns", ...)`.

## Rules
- Explore briefly before modifying — read a few key files to understand conventions, then start making changes. Do NOT over-read; 2-3 reads of relevant files is enough.
- Use update_memory to record project knowledge after initial exploration (language, build tool, patterns, key files).
- The old_string in edit_file MUST match exactly (including whitespace and indentation). If a file is large (over ~2000 lines), use grep to find the line, then read_file with start_line/end_line (±1000 lines) to get exact text.
- Run tests after making changes. Fix failures within this session — do not leave broken tests.
- When framework context is provided: it is REFERENCE ONLY. Do NOT modify framework files.
- When generating Java tests, follow the testing strategy guidance when provided."""


_PLAN_SYSTEM_PROMPT = """\
You are an expert software engineer in PLAN mode. You can explore the codebase \
(read-only) and propose changes, but you CANNOT write files or run commands directly.

## Read tools (explore the codebase)
- read_file(path, start_line?, end_line?): Read file contents
- grep(pattern, path_filter?, context_lines?): Search for a pattern across code files
- list_dir(path): List directory contents (use "" for repo root)
- find_files(extension?, pattern?): Find files by extension or glob

## Plan tool (propose changes)
- propose_change(path, action, description, content?, old_string?, new_string?):
  Propose a change without writing to disk.
  Actions: 'create' (new file — provide content), 'modify' (edit existing — provide old_string+new_string for surgical edit, or content for full replacement), 'delete' (remove file).
  The old_string must match exactly once in the file (same as edit_file). You get immediate feedback if the match fails.

## Memory tools
- update_memory(key, content): Write a note to working memory.
- read_memory(): Read all notes from working memory and prior knowledge.

## Code intelligence tools (available when code index is built)
- find_callers(symbol_name): Find all callers of a function/method/class
- find_dependents(file_path): Find all files that import from a given file
- impact_analysis(file_path): Callers + dependents + related tests for a file
- describe_entity(symbol_name): Full signature, docstring, callers, callees
- find_similar(query, top_k?): Semantic search across all code entities
- context_for_edit(file_path, symbol_name?, intent?): Pre-edit context — callers, callees, dependents, hierarchy, tests
- predict_breakage(file_path, changes_description?): Risk report — what callers/children/dependents will break

## Completion
- task_complete(summary, files_changed): Call when you have proposed ALL necessary changes.

## Workflow
1. **EXPLORE** — Use read tools to understand the codebase structure, conventions, and relevant files.
2. **RECORD** — Use update_memory to record what you learn.
3. **PROPOSE** — Use propose_change for every file you want to create, modify, or delete.
   - For new files: action='create', provide full content.
   - For existing files: action='modify', provide old_string+new_string for surgical edits.
   - For deletions: action='delete'.
4. **COMPLETE** — Call task_complete with a summary and list of files affected.

## Rules
- ALWAYS explore before proposing. Read existing files first.
- Do NOT attempt to use write_file, edit_file, delete_file, or run_command — they are blocked in plan mode.
- Propose ALL changes needed. The user will review diffs and approve/reject the plan.
- Be precise with old_string — it must match exactly (whitespace, indentation)."""


# ---------------------------------------------------------------------------
# Question classification for ask-mode efficiency
# ---------------------------------------------------------------------------

# File extensions that indicate a targeted lookup question
_LOOKUP_EXTENSIONS_RE = re.compile(
    r"\.(properties|yml|yaml|xml|json|env|cfg|ini|conf|toml|sql|proto|graphql)\b",
    re.IGNORECASE,
)

# Keywords that suggest a config/property lookup
_LOOKUP_KEYWORDS_RE = re.compile(
    r"\b(propert(?:y|ies)|value\s+of|config(?:uration)?|setting|variable|environment|"
    r"application\.yml|application\.properties|env\.properties|bootstrap\.yml|"
    r"pom\.xml|build\.gradle)\b",
    re.IGNORECASE,
)

# Path-like patterns (e.g., /prod/, src/main/resources/)
_LOOKUP_PATH_RE = re.compile(
    r"(?:/(?:prod|dev|staging|test|qa|uat)/|src/main/resources/|resources/)",
    re.IGNORECASE,
)


def _classify_question(question: str) -> str:
    """Classify a question as 'lookup' (targeted file/property) or 'general'.

    Lookup questions mention specific file types, config keys, property names,
    or path patterns — they can be answered in 2-4 tool calls.
    General questions require broad exploration (architecture, flow, design).
    """
    if _LOOKUP_EXTENSIONS_RE.search(question):
        return "lookup"
    if _LOOKUP_KEYWORDS_RE.search(question):
        return "lookup"
    if _LOOKUP_PATH_RE.search(question):
        return "lookup"
    return "general"


_ASK_SYSTEM_PROMPT = """\
You are an expert software engineer in ASK mode. You can explore the codebase \
(read-only) to answer questions, but you CANNOT write files, run commands, or \
propose changes.

## Read tools (explore the codebase)
- read_file(path, start_line?, end_line?): Read file contents
- grep(pattern, path_filter?, context_lines?): Search for a pattern across code files
- list_dir(path): List directory contents (use "" for repo root)
- find_files(extension?, pattern?): Find files by extension or glob

## Memory tools
- update_memory(key, content): Write a note to working memory.
- read_memory(): Read all notes from working memory and prior knowledge.

## Code intelligence tools (available when code index is built)
- find_callers(symbol_name): Find all callers of a function/method/class
- find_dependents(file_path): Find all files that import from a given file
- impact_analysis(file_path): Callers + dependents + related tests for a file
- describe_entity(symbol_name): Full signature, docstring, callers, callees
- find_similar(query, top_k?): Semantic search across all code entities
- context_for_edit(file_path, symbol_name?, intent?): Pre-edit context — callers, callees, dependents, hierarchy, tests
- predict_breakage(file_path, changes_description?): Risk report — what callers/children/dependents will break

## Completion
- task_complete(answer, sources): Call when you have fully answered the question.

## Workflow
1. **EXPLORE** — Use read tools to understand the codebase and find information relevant to the question.
2. **RECORD** — Use update_memory to record what you learn.
3. **ANSWER** — Call task_complete with your complete answer and the list of source files consulted.

## Strategy — be efficient, minimize tool calls
- For targeted lookups (specific file, property, config value):
  1. find_files(extension=".properties") to locate the file
  2. read_file(path) to read its contents
  3. task_complete(answer, sources) immediately
  You should need 2-4 tool calls, not 20.
- For broad exploration (architecture, flow, design):
  1. list_dir("") to see the structure
  2. grep + read_file to find relevant code
  3. task_complete when you have enough
- Do NOT repeat the same grep pattern. If grep returns empty, try a different
  extension filter, or use find_files/list_dir to locate the file first.
- Prefer read_file over grep when you know or can guess the file path.
- Call task_complete as soon as you have enough information to answer.

## Rules
- ALWAYS explore before answering. Read relevant files first.
- Do NOT attempt to use write_file, edit_file, delete_file, run_command, or propose_change — they are blocked in ask mode.
- Provide a thorough, well-cited answer. List every file you consulted in sources.
- Be specific: reference file paths, line numbers, function names, and code snippets in your answer."""


_GCC_PROMPT_SECTION = """

## Context management tools (Git Context Controller)
- gcc_commit(summary, milestone?): Checkpoint your progress. Creates a versioned snapshot with a summary. Optionally mark as a milestone.
- gcc_branch(name, purpose): Start exploring an alternative approach in an isolated reasoning branch.
- gcc_merge(branch_name): Merge a reasoning branch back into main, consolidating findings.
- gcc_context(scope?, branch?): Retrieve stored context. Scopes: status, main, commits, branch, all.

### When to use GCC tools
- gcc_commit after: initial exploration, completing implementation, tests passing, significant progress
- gcc_branch when: trying an alternative approach, need to explore without losing current context, stuck and want to experiment
- gcc_merge when: branch exploration succeeded and findings should be consolidated
- gcc_context when: need to recall what you've done, resuming work, want to review milestones"""


_GCC_ASK_PROMPT_SECTION = """

## Context management tools (Git Context Controller)
- gcc_commit(summary, milestone?): Checkpoint exploration progress.
- gcc_context(scope?, branch?): Retrieve stored context. Scopes: status, main, commits, branch, all."""


_SPLUNK_PROMPT_SECTION = """

## Splunk tools (query production logs and metrics)

### Quick one-shot (recommended for most questions):
- `splunk_ask(question, index?, earliest?, latest?)` — automatically discovers metadata,
  generates SPL via AI, executes on Splunk, and returns results in one call.
  Example: `splunk_ask(question="what is the TPS of REST invoker")`

### Advanced two-step workflow (for custom/complex SPL):
1. First call `splunk_discover(query)` to find relevant Splunk indexes, fields, and sources
2. Read the returned metadata (index names, fields, sourcetypes, relationships)
3. Then call `splunk_search(spl)` or `splunk_stats(spl)` with a precise SPL query
   built from the discovered metadata

### When to use Splunk (auto-detect these patterns):
- Error investigation: errors, exceptions, stack traces, 500s, failures
- Performance: slow responses, timeouts, latency, resource exhaustion
- Log analysis: check logs, audit trails, events
- Monitoring: error rates, traffic, SLA breaches
- Deployment: before/after comparison, release validation

### SPL tips (use metadata from splunk_discover):
- Always use the exact `index` and `sourcetype` from discover results
- Use `field` values for filtering (e.g., `error_message="NullPointerException"`)
- Use `relationship` fields for correlation across services
- For charts, use `splunk_stats` with timechart/stats/chart commands

### Tools:
- splunk_ask(question, index?, earliest?, latest?): One-shot question → answer pipeline
- splunk_discover(query, top_k?): Search for relevant Splunk indexes/fields/sources
- splunk_search(spl, earliest?, latest?, max_results?): Run SPL query, returns table
- splunk_stats(spl, chart_type?, earliest?, latest?): Run SPL aggregation for charts
- splunk_saved_search(name?): List or run saved searches"""


_CERTS_PROMPT_SECTION = """

## Certificate inspection tools (Java KeyStore / PKCS12)

### Recommended workflow:
1. Call `cert_find()` to discover all keystore files (.jks, .p12, .pfx, .keystore, .truststore)
2. Call `cert_list(keystore_path)` to list aliases/entries in a specific keystore
3. Call `cert_details(keystore_path, alias)` to get full certificate details (expiry, subject, issuer, fingerprints)

### When to use (auto-detect these patterns):
- Certificate questions: "certificate", "cert", "SSL", "TLS", "keystore", "truststore"
- Expiry checks: "expire", "expiry", "expiration", "valid", "renewal"
- Security audit: "fingerprint", "issuer", "subject", "self-signed"

### Password handling:
- If no password is provided, these defaults are tried automatically: changeit, changeme, password, empty
- If defaults fail, ask the user for the password

### Store type auto-detection:
- .jks / .keystore → JKS
- .p12 / .pfx / .pkcs12 → PKCS12

### Tools:
- cert_find(path?): Find all keystore files in the repo (or subdirectory)
- cert_list(keystore_path, password?, storetype?): List aliases in a keystore
- cert_details(keystore_path, alias, password?, storetype?): Full cert info with expiry status"""


# ---------------------------------------------------------------------------
# Shared context builder
# ---------------------------------------------------------------------------

def _build_agent_context(
    requirements: str,
    repo_path: str,
    llm_config: dict,
    reference_pr_content: str = "",
    testing_strategy: str = "auto",
    build_tool: Optional[str] = None,
    consciousness: "ProjectConsciousness | None" = None,
    framework_context: str = "",
    config: Optional[dict] = None,
    repo_url: str = "",
    instruction_suffix: str = "",
    repo_knowledge: str = "",
) -> tuple[str, str]:
    """Build the user message and knowledge context for both agent and plan modes.

    Uses ``build_smart_initial_context`` to produce focused, requirement-relevant
    context instead of dumping the full consciousness string.  When
    *repo_knowledge* (hand-written ``.code-autonomy.md``) is present, it is
    included directly and the auto-generated consciousness structure/conventions
    are suppressed in favour of the higher-quality manual docs.

    Returns (user_message, knowledge_context).
    """
    from pathlib import Path
    repo_root = Path(repo_path)

    # Load persistent knowledge from prior runs
    knowledge_context = ""
    try:
        prior = load_knowledge(config, repo_path, repo_url)
        if prior:
            knowledge_context = prior.to_context_string()
    except Exception:
        pass

    # Build focused initial context (requirement-relevant only)
    initial_context = ""
    try:
        from src.agent.context import build_smart_initial_context
        initial_context = build_smart_initial_context(
            repo_path, requirements, consciousness=consciousness,
        )
    except ImportError:
        # Fallback: render consciousness directly if smart builder unavailable
        if consciousness is not None:
            initial_context = consciousness.to_context_string()

    # Repo knowledge (hand-written .code-autonomy.md) — higher quality than
    # auto-generated consciousness, so include it alongside the focused extract.
    repo_knowledge_section = f"\n{repo_knowledge}\n" if repo_knowledge else ""

    # Testing strategy — use JISI BDD prompt when spec is available
    testing_section = ""
    try:
        _bdd_spec = config.get("bdd_spec") if config else None
        if testing_strategy == "jisi_bdd" and _bdd_spec is not None:
            from src.bdd.prompt_builder import build_jisi_bdd_prompt
            ctx = build_jisi_bdd_prompt(_bdd_spec)
            if ctx:
                testing_section = f"\n{ctx}\n"
        else:
            from src.code.testing_strategies import get_testing_strategy_context
            from src.code.executor import detect_build_tool as _detect_bt
            bt = build_tool or _detect_bt(str(repo_root))
            ctx = get_testing_strategy_context(testing_strategy, bt, requirements)
            if ctx:
                testing_section = f"\n## Testing strategy (for tests)\n{ctx}\n"
    except Exception:
        pass

    framework_section = f"\n{framework_context}\n" if framework_context else ""
    ref_section = (
        f"\n\n## Reference PR (use as template)\n{reference_pr_content}"
        if reference_pr_content
        else ""
    )
    # Only include prior knowledge if it adds new info beyond repo_knowledge
    knowledge_section = f"\n\n{knowledge_context}\n" if knowledge_context and not repo_knowledge else ""

    suffix = instruction_suffix or (
        "Start by listing the repo root with list_dir, then explore relevant files "
        "before making any changes."
    )

    user_msg = (
        f"## Requirements\n{requirements}\n"
        f"{initial_context}\n"
        f"{repo_knowledge_section}"
        f"{framework_section}"
        f"{testing_section}"
        f"{ref_section}"
        f"{knowledge_section}\n\n"
        f"{suffix}"
    )

    return user_msg, knowledge_context


def _resolve_model_name(llm_config: dict) -> str:
    """Return the effective model/deployment name for tracing and logging.

    For Azure OpenAI the deployment_name is the actual model identifier.
    Falls back to the generic ``model`` field.
    """
    provider = llm_config.get("provider", "").lower()
    if provider == "azure":
        return llm_config.get("deployment_name") or llm_config.get("model", "gpt-4o")
    if provider in ("bedrock", "cdao"):
        # ARN can be long; take the last segment
        model = llm_config.get("model", "")
        return model.rsplit("/", 1)[-1] if "/" in model else model or "bedrock"
    return llm_config.get("model", "gpt-4o")


# ---------------------------------------------------------------------------
# Agent entry point
# ---------------------------------------------------------------------------

def generate_changes_with_agent(
    requirements: str,
    repo_path: str,
    llm_config: dict,
    reference_pr_content: str = "",
    max_turns: int = 50,
    verbose: bool = False,
    testing_strategy: str = "auto",
    build_tool: Optional[str] = None,
    consciousness: "ProjectConsciousness | None" = None,
    framework_context: str = "",
    agent_config: Optional[dict] = None,
    config: Optional[dict] = None,
    repo_url: str = "",
    repo_knowledge: str = "",
    code_index: "CodeIndex | None" = None,
    resume: bool = False,
    initial_working_memory: Optional[dict[str, str]] = None,
    conversation_context: Optional[list[dict]] = None,
) -> AgentResult:
    """Run the agentic loop: explore → edit → test → fix → complete.

    Returns an :class:`AgentResult` with *success*, *files_changed*,
    *summary*, etc.  When the LLM falls back to legacy JSON-output mode the
    result carries ``changes`` instead.
    """
    from src.llm_client import chat_completion, LLMUsageStats
    from src.code.file_cache import reset_session_cache
    reset_session_cache()

    repo_root = Path(repo_path)
    agent_cfg = agent_config or {}
    max_turns = agent_cfg.get("max_turns", max_turns)

    # LLM usage tracking
    usage_stats = LLMUsageStats()
    smart_summarization = agent_cfg.get("smart_summarization", True)
    truncation_limit = agent_cfg.get("truncation_limit", 100_000)

    # Budget tracking
    summarization_budget = agent_cfg.get("summarization_budget", 0)
    testing_budget = agent_cfg.get("testing_budget", 0)
    testing_turns_used = 0

    # Track every file the agent creates / edits / deletes
    changes_tracker: set[str] = set()
    # Track files the agent read and edit attempts (for end-of-run summary)
    reads_tracker: set[str] = set()
    read_counts: dict[str, int] = {}  # per-file read count to detect repeated reads
    failed_edits: list[str] = []  # brief descriptions of failed edit_file calls
    consecutive_reads_without_write = 0  # reads since last successful write
    tool_call_counts: dict[str, int] = {}    # ALL tool calls by name
    tool_errors: dict[str, int] = {}          # errors per tool
    consecutive_api_errors = 0                 # consecutive LLM API failures
    turns_without_write = 0                    # ANY turn without edit/write
    _code_intel_provided: set[str] = set()     # files that received pre-edit code intelligence
    _last_test_error_sig: str = ""             # last classified test error signature for feedback loop

    # Working memory (survives context compression)
    working_memory = WorkingMemory()
    if initial_working_memory:
        for k, v in initial_working_memory.items():
            working_memory.update(k, v)

    # --- GCC (opt-in structured versioned memory) ---
    gcc_controller: Optional[GCCController] = None
    if agent_cfg.get("gcc_enabled", False):
        gcc_controller = GCCController(
            repo_id=compute_repo_id(repo_path, repo_url),
            storage_dir=agent_cfg.get("gcc_storage_dir", ""),
        )

    # --- Execution tracing (Agent Lightning-inspired) ---
    tracing_enabled = is_tracing_enabled(config)
    collector: Optional[TraceCollector] = None
    if tracing_enabled:
        _repo_id = compute_repo_id(repo_path, repo_url)
        collector = TraceCollector(
            repo_id=_repo_id,
            repo_url=repo_url,
            model=_resolve_model_name(llm_config),
            requirements=requirements,
        )

    # Build the full tool list (read + write + exec + memory + complete + code_index)
    all_tools = build_agent_tools(agent_cfg, code_index=code_index)

    # Build shared context
    user_msg, _knowledge_ctx = _build_agent_context(
        requirements=requirements,
        repo_path=repo_path,
        llm_config=llm_config,
        reference_pr_content=reference_pr_content,
        testing_strategy=testing_strategy,
        build_tool=build_tool,
        consciousness=consciousness,
        framework_context=framework_context,
        config=config,
        repo_url=repo_url,
        repo_knowledge=repo_knowledge,
    )

    skip_tests = agent_cfg.get("skip_tests", False)

    system_prompt = _SYSTEM_PROMPT
    if skip_tests:
        # Remove VERIFY/FIX steps and instruct agent not to run tests
        system_prompt = system_prompt.replace(
            "4. **VERIFY** — Run tests with run_command after making changes (e.g., `pytest -v`, `mvn test`).\n"
            "5. **FIX** — If tests fail, read the error output, edit files to fix the issues, and re-run tests.\n"
            "6. **COMPLETE** — Call task_complete with a summary and the list of files changed.",
            "4. **COMPLETE** — Call task_complete with a summary and the list of files changed.",
        )
        system_prompt += (
            "\n\n## IMPORTANT: Skip Tests\n"
            "Do NOT run any tests or build commands. Skip the VERIFY and FIX steps entirely. "
            "Focus on EXPLORE → RECORD → IMPLEMENT → COMPLETE."
        )
    if gcc_controller:
        system_prompt += _GCC_PROMPT_SECTION
    if agent_cfg.get("splunk_enabled"):
        system_prompt += _SPLUNK_PROMPT_SECTION
    if agent_cfg.get("certs_enabled"):
        system_prompt += _CERTS_PROMPT_SECTION

    if conversation_context:
        context_lines = []
        for msg in conversation_context[-6:]:
            prefix = "User" if msg.get("role") == "user" else "Assistant"
            content = msg.get("content", "")[:500]
            context_lines.append(f"{prefix}: {content}")
        system_prompt += "\n\n## Prior Conversation\n" + "\n".join(context_lines)

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]

    # ------------------------------------------------------------------ #
    # Resume from checkpoint (if requested)
    # ------------------------------------------------------------------ #
    if resume:
        existing_checkpoint = load_checkpoint(config, repo_path, repo_url)
        if existing_checkpoint:
            req_hash = compute_requirement_hash(requirements)
            if existing_checkpoint.requirement_hash == req_hash:
                checkpoint_context = existing_checkpoint.to_context_string()
                # Restore working memory
                for k, v in existing_checkpoint.working_memory.items():
                    working_memory.update(k, v)
                # Pre-populate changes tracker
                for f in existing_checkpoint.files_changed:
                    changes_tracker.add(f)
                # Inject checkpoint context into user message
                messages[1]["content"] = user_msg + f"\n\n{checkpoint_context}\n"
                # Inject restored working memory into system prompt
                if not working_memory.is_empty():
                    messages[0]["content"] = system_prompt + "\n" + working_memory.to_message_block()
                print(f"  [resume] Restored checkpoint: {existing_checkpoint.turns_used}/{existing_checkpoint.max_turns} turns, {len(existing_checkpoint.files_changed)} file(s)")
            else:
                print("  [resume] Checkpoint found but requirement differs — starting fresh")
        else:
            print("  [resume] No checkpoint found — starting fresh")

    # Inject pre-populated working memory into system prompt
    # (covers initial_working_memory from prior JIRA stories when NOT resuming from checkpoint)
    if not working_memory.is_empty() and "<working_memory>" not in messages[0]["content"]:
        messages[0]["content"] = system_prompt + "\n" + working_memory.to_message_block()

    # ------------------------------------------------------------------ #
    # Agent loop
    # ------------------------------------------------------------------ #
    task_complete_data: Optional[dict] = None
    last_error_hash: Optional[str] = None
    stuck_count = 0
    consecutive_empty = 0

    model_name = _resolve_model_name(llm_config)

    for turn in range(max_turns):
        # --- Evict stale corrective messages (older than 3 turns) ---
        messages = [
            m for m in messages
            if "_corrective_turn" not in m or (turn - m["_corrective_turn"]) < 3
        ]

        # --- Context management (token-aware) ---
        ctx_span_id = None
        if collector:
            ctx_span_id = collector.start_span(
                SPAN_CONTEXT_MGMT, "manage_context", turn,
                inputs={"message_count": len(messages)},
            )
        try:
            from src.agent.context import manage_conversation_context

            prev_count = len(messages)
            messages = manage_conversation_context(
                messages,
                model=model_name,
                llm_config=llm_config,
                smart_summarization=smart_summarization,
                full_config=config,
                usage_stats=usage_stats,
                summarization_budget=summarization_budget,
            )
            if collector and ctx_span_id:
                collector.end_span(
                    ctx_span_id,
                    output_summary=f"{prev_count} -> {len(messages)} messages",
                    metadata={"messages_before": prev_count, "messages_after": len(messages)},
                )
                ctx_span_id = None
        except ImportError:
            pass  # graceful degradation
        if collector and ctx_span_id:
            collector.end_span(ctx_span_id, output_summary="skipped (no context module)")

        # --- LLM call ---
        llm_span_id = None
        if collector:
            tokens_est = sum(len(m.get("content", "") or "") // 4 for m in messages)
            llm_span_id = collector.start_span(
                SPAN_LLM_CALL, model_name, turn,
                inputs={"message_count": len(messages), "tokens_est": tokens_est},
                metadata={"model": model_name, "temperature": float(llm_config.get("temperature", 0.2))},
            )

        try:
            content, msg = chat_completion(
                messages=messages,
                config=llm_config,
                tools=all_tools,
                tool_choice="auto",
                temperature=float(llm_config.get("temperature", 0.2)),
                full_config=config,
                usage_stats=usage_stats,
            )
            consecutive_api_errors = 0
        except Exception as api_err:
            consecutive_api_errors += 1
            print(f"  [agent] LLM API error (attempt {consecutive_api_errors}): {api_err}")
            if collector and llm_span_id:
                collector.end_span(
                    llm_span_id,
                    output_summary=f"API error: {str(api_err)[:100]}",
                    success=False,
                    error=str(api_err)[:200],
                )
                llm_span_id = None
            if consecutive_api_errors >= MAX_CONSECUTIVE_API_ERRORS:
                print(f"  [agent] Aborting: {consecutive_api_errors} consecutive API errors")
                break
            # For 400 errors: trim messages to system + last 10 and retry
            err_str = str(api_err)
            if "400" in err_str or "Bad Request" in err_str:
                if len(messages) > 11:
                    messages = [messages[0]] + messages[-10:]
            messages.append({
                "role": "user",
                "content": (
                    f"The previous LLM call failed with: {str(api_err)[:200]}. "
                    "Please continue with the task."
                ),
            })
            continue

        tool_calls = getattr(msg, "tool_calls", None)

        if collector and llm_span_id:
            n_tool_calls = len(tool_calls) if tool_calls else 0
            content_len = len(content) if content else 0
            collector.end_span(
                llm_span_id,
                output_summary=f"{n_tool_calls} tool calls, {content_len} chars content",
                output_chars=content_len,
                metadata={"tool_call_count": n_tool_calls, "tokens_est": sum(len(m.get("content", "") or "") // 4 for m in messages)},
            )

        # ---- No tool calls: LLM is either done or confused ----
        if not tool_calls or len(tool_calls) == 0:
            if task_complete_data:
                break

            # Backward compat: try parsing legacy JSON changes
            parsed = parse_ai_changes(content)
            if parsed:
                legacy_result = AgentResult(
                    success=True,
                    changes=parsed,
                    turns_used=turn + 1,
                    summary="Legacy JSON output mode",
                    usage_stats=usage_stats,
                )
                if collector:
                    try:
                        trace = collector.finalize(
                            success=True, turns_used=turn + 1,
                            files_changed=[], summary="Legacy JSON output mode",
                        )
                        legacy_result.trace_id = trace.trace_id
                        trace_path = get_trace_store(config).save(trace)
                        print(f"  [trace] Saved: {trace_path}")
                    except Exception as _trace_err:
                        print(f"  [trace] Failed to save trace: {_trace_err}")
                return legacy_result

            # Nudge the agent to use tools (escalating messages)
            consecutive_empty += 1
            if consecutive_empty >= MAX_CONSECUTIVE_EMPTY:
                print(f"[agent] Aborting agent loop: {consecutive_empty} consecutive empty LLM responses")
                break
            messages.append({"role": "assistant", "content": content or ""})

            # Build escalating nudge with context recovery
            if consecutive_empty == 1:
                nudge_text = (
                    "Please use the available tools to implement the changes. "
                    "Start with read_file or grep to explore, then edit_file to modify code. "
                    "When everything is done and tests pass, call task_complete."
                )
            elif consecutive_empty == 2:
                # Include working memory recap so LLM can recover lost context
                wm_recap = ""
                if not working_memory.is_empty():
                    wm_recap = f"\n\nHere is what you've learned so far:\n{working_memory.read_all()}\n"
                nudge_text = (
                    f"Your previous response was empty. You have tools available: "
                    f"read_file, grep, list_dir, edit_file, write_file, run_command, task_complete.{wm_recap}\n"
                    f"Files modified so far: {sorted(changes_tracker) if changes_tracker else 'none'}. "
                    f"Please call a tool now."
                )
            else:
                # Last attempts: provide explicit next step
                if not changes_tracker:
                    nudge_text = (
                        "You have not made any changes yet. Please start by calling "
                        "grep to find the relevant code, then edit_file to make changes. "
                        "If you cannot proceed, call task_complete with a summary of what you found."
                    )
                else:
                    nudge_text = (
                        f"You have modified {len(changes_tracker)} file(s): {sorted(changes_tracker)}. "
                        "Please call run_command to test your changes, or call task_complete if done."
                    )
            messages.append({"role": "user", "content": nudge_text})
            continue

        # ---- Process tool calls ----
        consecutive_empty = 0
        messages.append({
            "role": "assistant",
            "content": msg.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments or "{}",
                    },
                }
                for tc in tool_calls
            ],
        })

        for tc in tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments) if tc.function.arguments else {}
            except json.JSONDecodeError:
                args = {}

            # --- Count every tool call ---
            tool_call_counts[name] = tool_call_counts.get(name, 0) + 1

            # --- Start tool span ---
            tool_span_id = None
            if collector:
                span_type = SPAN_GCC_COMMAND if name.startswith("gcc_") else SPAN_TOOL_CALL
                tool_span_id = collector.start_span(
                    span_type, name, turn,
                    inputs=_sanitize_tool_args(name, args),
                )

            # --- task_complete: signal termination + save knowledge with outcome ---
            if name == "task_complete":
                task_complete_data = args
                result = f"Task marked complete. Summary: {args.get('summary', '')}"
                # Save knowledge with outcome (non-fatal)
                try:
                    save_knowledge_with_outcome(
                        config, repo_path, repo_url,
                        working_memory,
                        success=True,
                        summary=args.get("summary", ""),
                        files_changed=args.get("files_changed"),
                        tools_used=dict(tool_call_counts),
                        # Record fix pattern if agent recovered from a test error
                        error_signature=_last_test_error_sig,
                        fix_description=args.get("summary", "") if _last_test_error_sig else "",
                    )
                except Exception:
                    pass
                # Save GCC state (non-fatal)
                try:
                    if gcc_controller:
                        gcc_controller.save()
                except Exception:
                    pass
                if collector and tool_span_id:
                    collector.end_span(
                        tool_span_id,
                        output_summary=_summarize_output(result),
                        output_chars=len(result),
                        success=True,
                        reward=1.0,
                    )
                if agent_cfg.get("show_activity", True):
                    log_agent_activity(turn, name, args, f"done — {args.get('summary', '')[:50]}")
            else:
                # Log before execution so long-running commands show activity
                if agent_cfg.get("show_activity", True):
                    log_agent_tool_start(turn, name, args)

                # --- P0-1: Pre-edit code intelligence injection ---
                _pre_edit_context = ""
                if (
                    name in ("edit_file", "write_file")
                    and code_index is not None
                    and args.get("path", "") not in _code_intel_provided
                ):
                    _edit_path = args.get("path", "")
                    try:
                        from src.code_index.tools import _context_for_edit, _predict_breakage
                        intel_context = _context_for_edit(code_index, _edit_path)
                        intel_risk = _predict_breakage(code_index, _edit_path)
                        if intel_context and "No symbols found" not in intel_context:
                            # Compact the intelligence to avoid flooding context
                            _pre_edit_context = (
                                f"\n[Code Intelligence for {_edit_path}]\n"
                                f"{intel_context[:2000]}\n"
                                f"{intel_risk[:1500]}\n"
                            )
                            _code_intel_provided.add(_edit_path)
                    except Exception:
                        pass  # code intelligence is best-effort

                result = execute_tool(
                    repo_root, name, args,
                    changes_tracker=changes_tracker,
                    agent_config=agent_cfg,
                    working_memory=working_memory,
                    gcc_controller=gcc_controller,
                    code_index=code_index,
                )

                # --- P0-1: Prepend code intelligence to the tool result ---
                if _pre_edit_context and not result.startswith("Error"):
                    result = _pre_edit_context + "\n" + result

                # --- P0-1: Post-edit verification gate ---
                if (
                    name in ("edit_file", "write_file")
                    and not result.startswith("Error")
                    and code_index is not None
                ):
                    _edited_path = args.get("path", "")
                    try:
                        from src.code_index.verifier import post_edit_verification_gate
                        _vresult = post_edit_verification_gate(
                            str(repo_root), [_edited_path], code_index, config or {},
                        )
                        if not _vresult.passed:
                            result += f"\n\n[Verification Warning]\n{_vresult.summary()}"
                        elif _vresult.warnings:
                            result += f"\n\n[Verification Note]\n{_vresult.summary()}"
                    except Exception:
                        pass  # verification is best-effort

                # --- Track reads and failed edits for end-of-run summary ---
                if name == "read_file" and not result.startswith("Error"):
                    _rpath = args.get("path", "")
                    reads_tracker.add(_rpath)
                    read_counts[_rpath] = read_counts.get(_rpath, 0) + 1
                    consecutive_reads_without_write += 1
                elif name in ("edit_file", "write_file") and result.startswith("Error"):
                    failed_edits.append(f"{args.get('path', '?')}: {result[:120]}")
                elif name in ("edit_file", "write_file", "delete_file") and not result.startswith("Error"):
                    consecutive_reads_without_write = 0  # successful write resets counter
                # --- Track tool errors ---
                if result.startswith("Error"):
                    tool_errors[name] = tool_errors.get(name, 0) + 1
                # --- End tool span with reward ---
                if collector and tool_span_id:
                    is_error = result.startswith("Error:")
                    # Reward heuristics
                    reward = 0.0
                    if is_error:
                        reward = -1.0
                    elif name == "run_command":
                        reward = 1.0 if "exit code: 0]" in result else -0.5
                    elif name in ("write_file", "edit_file", "delete_file"):
                        reward = 1.0
                    elif name in ("read_file", "grep", "list_dir", "find_files"):
                        reward = 0.5
                    elif name == "update_memory":
                        reward = 0.5
                    elif name in ("gcc_commit", "gcc_branch", "gcc_merge", "gcc_context"):
                        reward = 0.5

                    collector.end_span(
                        tool_span_id,
                        output_summary=_summarize_output(result),
                        output_chars=len(result),
                        success=not is_error,
                        error=result[:200] if is_error else "",
                        reward=reward,
                    )

                if agent_cfg.get("show_activity", True):
                    log_agent_activity(turn, name, args, summarize_tool_result(result, name))

            # Track testing turns (skip enforcement when skip_tests is active)
            if name == "run_command" and not skip_tests:
                testing_turns_used += 1
                if testing_budget > 0 and testing_turns_used >= testing_budget:
                    messages.append({
                        "role": "user",
                        "content": (
                            f"You have used {testing_turns_used} of {testing_budget} allowed testing/build turns. "
                            "Stop running tests and call task_complete with your current progress."
                        ),
                    })

            # Intelligent summarization for large outputs
            _was_truncated = len(result) > truncation_limit
            if _was_truncated:
                try:
                    from src.agent.context import summarize_large_output

                    if smart_summarization:
                        result = summarize_large_output(
                            result, name, llm_config, usage_stats=usage_stats,
                            summarization_budget=summarization_budget,
                        )
                    else:
                        result = result[:truncation_limit] + f"\n...(truncated, {len(result)} total chars)"
                except ImportError:
                    result = result[:truncation_limit] + f"\n...(truncated, {len(result)} total chars)"

            if verbose:
                print(f"  Agent turn {turn + 1}: {name}({list(args.keys())}) -> {len(result)} chars")

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

            # --- Hint when read_file output was truncated ---
            if name == "read_file" and _was_truncated:
                _read_path = args.get("path", "")
                messages.append({
                    "role": "user",
                    "content": (
                        f"Note: {_read_path} is a large file and was truncated. "
                        "Do NOT re-read the full file. Instead:\n"
                        f"1. Use grep(\"property_name\") to find the exact line number.\n"
                        f"2. Use read_file(\"{_read_path}\", start_line=N-1000, end_line=N+1000) for a focused range.\n"
                        "3. Then use edit_file with the exact text from that read.\n"
                        "4. If grep finds no match, the property does not exist yet — add it near related properties."
                    ),
                    "_corrective_turn": turn,
                })

            # --- Detect repeated reads on the same file ---
            if name == "read_file" and not result.startswith("Error"):
                _rpath2 = args.get("path", "")
                if read_counts.get(_rpath2, 0) >= 3:
                    messages.append({
                        "role": "user",
                        "content": (
                            f"You have read {_rpath2} {read_counts[_rpath2]} times. "
                            "Stop re-reading this file. You have enough context. "
                            "If you need to edit it, use the content you already have. "
                            "If edit_file fails, use grep to find the exact line, then "
                            "read_file with start_line/end_line (e.g., ±1000 lines around the match), "
                            "and copy the exact text into old_string."
                        ),
                        "_corrective_turn": turn,
                    })

            # --- Corrective injection after failed edit_file ---
            if name == "edit_file" and result.startswith("Error"):
                _epath = args.get("path", "")
                messages.append({
                    "role": "user",
                    "content": (
                        f"Your edit to {_epath} failed. To fix this:\n"
                        "1. Use grep to find the exact text you want to change (search for a unique keyword from old_string).\n"
                        f"2. Use read_file(\"{_epath}\", start_line=LINE-1000, end_line=LINE+1000) to get the exact content with context.\n"
                        "3. Copy the EXACT text (including all whitespace) from that read_file output into old_string.\n"
                        "4. Retry edit_file with the corrected old_string."
                    ),
                    "_corrective_turn": turn,
                })

            # --- Nudge after many consecutive reads without any write ---
            if consecutive_reads_without_write == 8:
                messages.append({
                    "role": "user",
                    "content": (
                        f"You have read {consecutive_reads_without_write} files in a row without making any edits. "
                        "You should have enough context by now. Please make your changes using edit_file or write_file. "
                        "If you are struggling to match old_string for edit_file, use grep to find the exact line, "
                        "then read_file with a narrow line range to get the precise text."
                    ),
                    "_corrective_turn": turn,
                })

            # --- Inject working memory / GCC context into system prompt ---
            if (name == "update_memory" and not working_memory.is_empty()) or \
               (name.startswith("gcc_") and gcc_controller):
                wm_block = working_memory.to_message_block() if not working_memory.is_empty() else ""
                gcc_block = gcc_controller.to_message_block() if gcc_controller else ""
                messages[0] = {"role": "system", "content": system_prompt + "\n" + wm_block + gcc_block}

            # --- P0-2: Error classification + P0-3: Fix suggestions on test failures ---
            if name == "run_command" and "[exit code:" in result and "exit code: 0]" not in result:
                _error_hints: list[str] = []
                # Classify errors
                try:
                    from src.services.testing_service import TestingService
                    _ts = TestingService()
                    _classifications = _ts._classify_test_errors(
                        result, "", 1  # result contains combined output
                    )
                    if _classifications:
                        _class_lines = ["[Error Classification]"]
                        for ec in _classifications[:3]:
                            _class_lines.append(
                                f"  - {ec['type']}/{ec['subtype']}: {ec['suggestion']}"
                            )
                            _last_test_error_sig = ec["message"][:200]
                        _error_hints.append("\n".join(_class_lines))
                except Exception:
                    pass

                # Check for known fix patterns from previous runs
                try:
                    _fix_suggs = get_fix_suggestions(config, repo_path, repo_url, result[:2000])
                    if _fix_suggs:
                        _fix_lines = ["[Known Fix Patterns from previous runs]"]
                        for fs in _fix_suggs[:3]:
                            _fix_lines.append(
                                f"  - Error: `{fs['error_signature'][:80]}` → "
                                f"Fix: {fs['fix_description'][:200]} "
                                f"(worked {fs.get('success_count', 0)}x)"
                            )
                        _error_hints.append("\n".join(_fix_lines))
                except Exception:
                    pass

                if _error_hints:
                    messages.append({
                        "role": "user",
                        "content": "\n\n".join(_error_hints),
                    })

            # --- Stuck detection (same error 3 times) ---
            if name == "run_command" and "[exit code:" in result and "exit code: 0]" not in result:
                err_hash = str(hash(result[:500]))
                if err_hash == last_error_hash:
                    stuck_count += 1
                else:
                    last_error_hash = err_hash
                    stuck_count = 1
                if stuck_count >= 2:
                    if collector:
                        collector.add_event(
                            SPAN_STUCK_DETECT, "stuck_2x_same_error", turn,
                            inputs={"error_hash": err_hash},
                            reward=-1.0,
                        )
                    messages.append({
                        "role": "user",
                        "content": (
                            "Same test failure repeated. Try a different approach. "
                            "Re-read the failing test and source before editing."
                        ),
                    })
                    stuck_count = 0

        # --- Track turns without any write ---
        wrote_this_turn = any(
            tc.function.name in ("edit_file", "write_file", "delete_file")
            and not (
                tc.function.name == "task_complete"
                or any(
                    m.get("tool_call_id") == tc.id
                    and m.get("content", "").startswith("Error")
                    for m in messages[-len(tool_calls):]
                )
            )
            for tc in tool_calls
        )
        if wrote_this_turn:
            turns_without_write = 0
        else:
            turns_without_write += 1

        if turns_without_write == 4:
            messages.append({
                "role": "user",
                "content": f"{turns_without_write} turns without edits. Start implementing now.",
            })
        elif turns_without_write >= 6:
            messages.append({
                "role": "user",
                "content": f"WARNING: {turns_without_write} turns, no edits. Edit now or session fails.",
            })

        if task_complete_data:
            break

        # --- Advisory deadline nudges (configurable, can be disabled) ---
        _nudge_enabled = agent_cfg.get("nudge_enabled", True)
        if _nudge_enabled:
            has_writes = len(changes_tracker) > 0
            has_plan = not working_memory.is_empty()
            explore_pct = float(agent_cfg.get("explore_budget_pct", 0.30))
            soft_pct = float(agent_cfg.get("soft_deadline_pct", 0.60))
            hard_pct = float(agent_cfg.get("hard_deadline_pct", 0.80))
            explore_limit = max(5, int(max_turns * explore_pct))
            soft_deadline = int(max_turns * soft_pct)
            hard_deadline = int(max_turns * hard_pct)

            if turn + 1 == explore_limit and not has_writes and not has_plan:
                messages.append({
                    "role": "user",
                    "content": f"{turn + 1}/{max_turns} turns exploring. Start implementing.",
                })
            elif turn + 1 == soft_deadline:
                if has_writes:
                    messages.append({
                        "role": "user",
                        "content": f"{turn + 1}/{max_turns} turns, {len(changes_tracker)} file(s) modified. Run tests and call task_complete.",
                    })
                else:
                    messages.append({
                        "role": "user",
                        "content": f"{turn + 1}/{max_turns} turns, no edits yet. Start implementing now.",
                    })
            elif turn + 1 == hard_deadline:
                status = f"{len(changes_tracker)} file(s) modified. Wrap up." if has_writes else "No edits. Make changes now."
                messages.append({
                    "role": "user",
                    "content": f"{turn + 1}/{max_turns} turns, {max_turns - turn - 1} left. {status}",
                })

    # ------------------------------------------------------------------ #
    # Build result + finalize trace
    # ------------------------------------------------------------------ #
    if task_complete_data:
        # Clear checkpoint on successful completion
        try:
            clear_checkpoint(config, repo_path, repo_url)
        except Exception:
            pass
        result_obj = AgentResult(
            success=True,
            files_changed=sorted(changes_tracker),
            summary=task_complete_data.get("summary", ""),
            turns_used=turn + 1,
            tests_passed=True,
            usage_stats=usage_stats,
            working_memory=working_memory.to_dict(),
        )
    else:
        # --- Build detailed end-of-run summary ---
        activity_lines = [f"Turns used: {max_turns}"]
        activity_lines.append(f"Files read: {sorted(reads_tracker) if reads_tracker else 'none'}")
        activity_lines.append(f"Files modified: {sorted(changes_tracker) if changes_tracker else 'none'}")
        if failed_edits:
            activity_lines.append(f"Failed edits ({len(failed_edits)}):")
            for fe in failed_edits[-10:]:  # last 10
                activity_lines.append(f"  - {fe}")
        activity_lines.extend(_format_tool_breakdown(tool_call_counts, tool_errors))
        wm_summary = ""
        if not working_memory.is_empty():
            wm_summary = f"\nWorking memory:\n{working_memory.read_all()}"
        activity_report = "\n".join(activity_lines) + wm_summary

        # --- Force a reflection call to get a useful failure summary ---
        reflection_summary = ""
        try:
            reflection_prompt = (
                "The agent session has ended without calling task_complete. "
                "Based on the conversation so far, provide a brief summary (3-5 sentences) covering:\n"
                "1. What files were reviewed and what was understood\n"
                "2. What changes were attempted (if any) and what went wrong\n"
                "3. Why the task could not be completed\n"
                "4. What specific steps should be taken on the next attempt\n\n"
                f"Activity report:\n{activity_report}"
            )
            reflection_content, _ = chat_completion(
                messages=[
                    {"role": "system", "content": "You are summarizing an incomplete agent session. Be concise and specific."},
                    {"role": "user", "content": reflection_prompt},
                ],
                config=llm_config,
                temperature=0.1,
                full_config=config,
            )
            reflection_summary = reflection_content.strip() if reflection_content else ""
        except Exception:
            pass  # reflection is best-effort

        # Build user-facing summary: lead with reflection (the useful content).
        # Tool breakdown is internal-only — don't show it to users.
        if reflection_summary:
            detailed_summary = reflection_summary
            if changes_tracker:
                detailed_summary += f"\n\nFiles modified ({len(changes_tracker)}): {', '.join(sorted(changes_tracker))}"
        elif not working_memory.is_empty():
            detailed_summary = working_memory.read_all()[:2000]
            if changes_tracker:
                detailed_summary += f"\n\nFiles modified ({len(changes_tracker)}): {', '.join(sorted(changes_tracker))}"
        elif changes_tracker:
            detailed_summary = f"Modified {len(changes_tracker)} file(s): {', '.join(sorted(changes_tracker))}. The agent ran out of turns before completing all tasks."
        else:
            detailed_summary = "The agent could not complete the task within the turn limit. Try a more specific request or increasing the turn budget."

        print(f"\n  [agent] End-of-run report:")
        print(f"  Files read ({len(reads_tracker)}): {sorted(reads_tracker) if reads_tracker else 'none'}")
        print(f"  Files modified ({len(changes_tracker)}): {sorted(changes_tracker) if changes_tracker else 'none'}")
        if failed_edits:
            print(f"  Failed edits ({len(failed_edits)}):")
            for fe in failed_edits[-5:]:
                print(f"    - {fe}")
        for _tb_line in _format_tool_breakdown(tool_call_counts, tool_errors):
            print(f"  {_tb_line}")
        if reflection_summary:
            print(f"  Reflection: {reflection_summary[:200]}")

        # Agent exhausted turns without completing — save checkpoint
        checkpoint = save_checkpoint(
            config, repo_path, repo_url, requirements,
            sorted(changes_tracker), working_memory,
            turns_used=max_turns, max_turns=max_turns,
            summary=detailed_summary[:500],
            pending_work=reflection_summary or working_memory.read_all()[:500] or "No specific pending work identified.",
            summarization_calls_used=usage_stats.calls_by_category("summarization") if usage_stats else 0,
            testing_turns_used=testing_turns_used,
        )
        # Save working memory + outcome into knowledge (even on failure)
        try:
            save_knowledge_with_outcome(
                config, repo_path, repo_url, working_memory,
                success=False,
                summary=detailed_summary[:500],
                files_changed=sorted(changes_tracker),
                tools_used=dict(tool_call_counts),
                error_type="incomplete_run",
                error_signature=_last_test_error_sig,
            )
        except Exception:
            pass
        result_obj = AgentResult(
            success=False,
            files_changed=sorted(changes_tracker),
            summary=detailed_summary,
            turns_used=max_turns,
            usage_stats=usage_stats,
            checkpoint=checkpoint,
            working_memory=working_memory.to_dict(),
            partial=True,
            can_explore_deeper=True,
        )

    # --- Save execution trace (non-blocking) ---
    if collector:
        try:
            trace = collector.finalize(
                success=result_obj.success,
                turns_used=result_obj.turns_used,
                files_changed=result_obj.files_changed,
                summary=result_obj.summary,
            )
            result_obj.trace_id = trace.trace_id
            _save_trace_async(trace, config)
        except Exception as _trace_err:
            print(f"  [trace] Failed to finalize trace: {_trace_err}")

    return result_obj


# ---------------------------------------------------------------------------
# Plan-mode entry point
# ---------------------------------------------------------------------------

def generate_plan_with_agent(
    requirements: str,
    repo_path: str,
    llm_config: dict,
    reference_pr_content: str = "",
    max_turns: int = 30,
    verbose: bool = False,
    testing_strategy: str = "auto",
    build_tool: Optional[str] = None,
    consciousness: "ProjectConsciousness | None" = None,
    framework_context: str = "",
    agent_config: Optional[dict] = None,
    config: Optional[dict] = None,
    repo_url: str = "",
    repo_knowledge: str = "",
    code_index: "CodeIndex | None" = None,
    resume: bool = False,
    conversation_context: Optional[list[dict]] = None,
) -> "PlanResult":
    """Run the agent in plan mode: explore → propose changes → complete.

    Returns a :class:`PlanResult` with the accumulated :class:`ChangePlan`.
    No files are written to disk.
    """
    from src.llm_client import chat_completion, LLMUsageStats
    from src.agent.plan import ChangePlan
    from src.code.file_cache import reset_session_cache
    reset_session_cache()

    repo_root = Path(repo_path)
    agent_cfg = agent_config or {}
    max_turns = agent_cfg.get("plan_max_turns", agent_cfg.get("max_turns", max_turns))

    # LLM usage tracking
    usage_stats = LLMUsageStats()
    smart_summarization = agent_cfg.get("smart_summarization", True)
    truncation_limit = agent_cfg.get("truncation_limit", 30_000)

    working_memory = WorkingMemory()
    change_plan = ChangePlan()

    # --- GCC (opt-in structured versioned memory) ---
    gcc_controller: Optional[GCCController] = None
    if agent_cfg.get("gcc_enabled", False):
        gcc_controller = GCCController(
            repo_id=compute_repo_id(repo_path, repo_url),
            storage_dir=agent_cfg.get("gcc_storage_dir", ""),
        )

    # --- Execution tracing ---
    tracing_enabled = is_tracing_enabled(config)
    collector: Optional[TraceCollector] = None
    if tracing_enabled:
        _repo_id = compute_repo_id(repo_path, repo_url)
        collector = TraceCollector(
            repo_id=_repo_id,
            repo_url=repo_url,
            model=_resolve_model_name(llm_config),
            requirements=requirements,
        )

    # Build plan-mode tool list (read + propose + memory + completion + code_index)
    all_tools = build_plan_tools(agent_cfg, code_index=code_index)

    # Build shared context
    user_msg, _knowledge_ctx = _build_agent_context(
        requirements=requirements,
        repo_path=repo_path,
        llm_config=llm_config,
        reference_pr_content=reference_pr_content,
        testing_strategy=testing_strategy,
        build_tool=build_tool,
        consciousness=consciousness,
        framework_context=framework_context,
        config=config,
        repo_url=repo_url,
        instruction_suffix=(
            "Start by listing the repo root with list_dir, then explore relevant files. "
            "Once you understand the codebase, use propose_change to propose ALL needed changes. "
            "When done proposing, call task_complete."
        ),
        repo_knowledge=repo_knowledge,
    )

    system_prompt = _PLAN_SYSTEM_PROMPT
    if gcc_controller:
        system_prompt += _GCC_PROMPT_SECTION
    if agent_cfg.get("splunk_enabled"):
        system_prompt += _SPLUNK_PROMPT_SECTION
    if agent_cfg.get("certs_enabled"):
        system_prompt += _CERTS_PROMPT_SECTION

    if conversation_context:
        context_lines = []
        for msg in conversation_context[-6:]:
            prefix = "User" if msg.get("role") == "user" else "Assistant"
            content = msg.get("content", "")[:500]
            context_lines.append(f"{prefix}: {content}")
        system_prompt += "\n\n## Prior Conversation\n" + "\n".join(context_lines)

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]

    # ------------------------------------------------------------------ #
    # Resume from checkpoint (if requested)
    # ------------------------------------------------------------------ #
    if resume:
        existing_checkpoint = load_checkpoint(config, repo_path, repo_url)
        if existing_checkpoint:
            req_hash = compute_requirement_hash(requirements)
            if existing_checkpoint.requirement_hash == req_hash:
                checkpoint_context = existing_checkpoint.to_context_string()
                # Restore working memory
                for k, v in existing_checkpoint.working_memory.items():
                    working_memory.update(k, v)
                # Inject checkpoint context into user message
                messages[1]["content"] = user_msg + f"\n\n{checkpoint_context}\n"
                # Inject restored working memory into system prompt
                if not working_memory.is_empty():
                    messages[0]["content"] = system_prompt + "\n" + working_memory.to_message_block()
                print(f"  [plan-resume] Restored checkpoint: {existing_checkpoint.turns_used}/{existing_checkpoint.max_turns} turns")
            else:
                print("  [plan-resume] Checkpoint found but requirement differs — starting fresh")
        else:
            print("  [plan-resume] No checkpoint found — starting fresh")

    # Inject pre-populated working memory into system prompt
    if not working_memory.is_empty() and "<working_memory>" not in messages[0]["content"]:
        messages[0]["content"] = system_prompt + "\n" + working_memory.to_message_block()

    task_complete_data: Optional[dict] = None
    consecutive_empty = 0
    tool_call_counts: dict[str, int] = {}
    tool_errors: dict[str, int] = {}
    consecutive_api_errors = 0
    model_name = _resolve_model_name(llm_config)

    for turn in range(max_turns):
        # --- Context management ---
        ctx_span_id = None
        if collector:
            ctx_span_id = collector.start_span(
                SPAN_CONTEXT_MGMT, "manage_context", turn,
                inputs={"message_count": len(messages)},
            )
        try:
            from src.agent.context import manage_conversation_context
            prev_count = len(messages)
            messages = manage_conversation_context(
                messages, model=model_name, llm_config=llm_config,
                smart_summarization=smart_summarization,
                full_config=config,
                usage_stats=usage_stats,
            )
            if collector and ctx_span_id:
                collector.end_span(
                    ctx_span_id,
                    output_summary=f"{prev_count} -> {len(messages)} messages",
                    metadata={"messages_before": prev_count, "messages_after": len(messages)},
                )
                ctx_span_id = None
        except ImportError:
            pass
        if collector and ctx_span_id:
            collector.end_span(ctx_span_id, output_summary="skipped (no context module)")

        # --- LLM call ---
        llm_span_id = None
        if collector:
            tokens_est = sum(len(m.get("content", "") or "") // 4 for m in messages)
            llm_span_id = collector.start_span(
                SPAN_LLM_CALL, model_name, turn,
                inputs={"message_count": len(messages), "tokens_est": tokens_est},
                metadata={"model": model_name, "temperature": float(llm_config.get("temperature", 0.2))},
            )

        try:
            content, msg = chat_completion(
                messages=messages,
                config=llm_config,
                tools=all_tools,
                tool_choice="auto",
                temperature=float(llm_config.get("temperature", 0.2)),
                full_config=config,
                usage_stats=usage_stats,
            )
            consecutive_api_errors = 0
        except Exception as api_err:
            consecutive_api_errors += 1
            print(f"  [plan] LLM API error (attempt {consecutive_api_errors}): {api_err}")
            if collector and llm_span_id:
                collector.end_span(
                    llm_span_id,
                    output_summary=f"API error: {str(api_err)[:100]}",
                    success=False,
                    error=str(api_err)[:200],
                )
                llm_span_id = None
            if consecutive_api_errors >= MAX_CONSECUTIVE_API_ERRORS:
                print(f"  [plan] Aborting: {consecutive_api_errors} consecutive API errors")
                break
            err_str = str(api_err)
            if "400" in err_str or "Bad Request" in err_str:
                if len(messages) > 11:
                    messages = [messages[0]] + messages[-10:]
            messages.append({
                "role": "user",
                "content": (
                    f"The previous LLM call failed with: {str(api_err)[:200]}. "
                    "Please continue with the task."
                ),
            })
            continue

        tool_calls = getattr(msg, "tool_calls", None)

        if collector and llm_span_id:
            n_tool_calls = len(tool_calls) if tool_calls else 0
            content_len = len(content) if content else 0
            collector.end_span(
                llm_span_id,
                output_summary=f"{n_tool_calls} tool calls, {content_len} chars content",
                output_chars=content_len,
                metadata={"tool_call_count": n_tool_calls},
            )

        # ---- No tool calls ----
        if not tool_calls or len(tool_calls) == 0:
            if task_complete_data:
                break
            consecutive_empty += 1
            if consecutive_empty >= MAX_CONSECUTIVE_EMPTY:
                print(f"[plan] Aborting plan loop: {consecutive_empty} consecutive empty LLM responses")
                break
            messages.append({"role": "assistant", "content": content})
            messages.append({
                "role": "user",
                "content": (
                    "Please use the tools to explore the codebase and propose changes. "
                    "When all changes are proposed, call task_complete."
                ),
            })
            continue

        # ---- Process tool calls ----
        consecutive_empty = 0
        messages.append({
            "role": "assistant",
            "content": msg.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments or "{}",
                    },
                }
                for tc in tool_calls
            ],
        })

        for tc in tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments) if tc.function.arguments else {}
            except json.JSONDecodeError:
                args = {}

            tool_call_counts[name] = tool_call_counts.get(name, 0) + 1

            tool_span_id = None
            if collector:
                span_type = SPAN_GCC_COMMAND if name.startswith("gcc_") else SPAN_TOOL_CALL
                tool_span_id = collector.start_span(
                    span_type, name, turn,
                    inputs=_sanitize_tool_args(name, args),
                )

            if name == "task_complete":
                task_complete_data = args
                result = f"Plan complete. Summary: {args.get('summary', '')}"
                # Save GCC state (non-fatal)
                try:
                    if gcc_controller:
                        gcc_controller.save()
                except Exception:
                    pass
                if collector and tool_span_id:
                    collector.end_span(
                        tool_span_id,
                        output_summary=_summarize_output(result),
                        output_chars=len(result),
                        success=True,
                        reward=1.0,
                    )
                if agent_cfg.get("show_activity", True):
                    log_agent_activity(turn, name, args, f"done — {args.get('summary', '')[:50]}")
            else:
                result = execute_plan_tool(
                    repo_root, name, args,
                    change_plan=change_plan,
                    working_memory=working_memory,
                    gcc_controller=gcc_controller,
                    code_index=code_index,
                )
                if result.startswith("Error"):
                    tool_errors[name] = tool_errors.get(name, 0) + 1
                if agent_cfg.get("show_activity", True):
                    log_agent_activity(turn, name, args, summarize_tool_result(result, name))
                if collector and tool_span_id:
                    is_error = result.startswith("Error:")
                    reward = -1.0 if is_error else (0.8 if name == "propose_change" else 0.5)
                    collector.end_span(
                        tool_span_id,
                        output_summary=_summarize_output(result),
                        output_chars=len(result),
                        success=not is_error,
                        error=result[:200] if is_error else "",
                        reward=reward,
                    )

            # Truncation
            if len(result) > truncation_limit:
                try:
                    from src.agent.context import summarize_large_output
                    if smart_summarization:
                        result = summarize_large_output(
                            result, name, llm_config, usage_stats=usage_stats,
                        )
                    else:
                        result = result[:truncation_limit] + f"\n...(truncated, {len(result)} total chars)"
                except ImportError:
                    result = result[:truncation_limit] + f"\n...(truncated, {len(result)} total chars)"

            if verbose:
                print(f"  Plan turn {turn + 1}: {name}({list(args.keys())}) -> {len(result)} chars")

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

            # --- Inject working memory / GCC context into system prompt ---
            if (name == "update_memory" and not working_memory.is_empty()) or \
               (name.startswith("gcc_") and gcc_controller):
                wm_block = working_memory.to_message_block() if not working_memory.is_empty() else ""
                gcc_block = gcc_controller.to_message_block() if gcc_controller else ""
                messages[0] = {"role": "system", "content": system_prompt + "\n" + wm_block + gcc_block}

        if task_complete_data:
            break

    # ---- Build result ----
    if task_complete_data:
        plan_result = PlanResult(
            success=True,
            plan=change_plan,
            summary=task_complete_data.get("summary", ""),
            turns_used=turn + 1,
            usage_stats=usage_stats,
        )
    else:
        _tb_lines = _format_tool_breakdown(tool_call_counts, tool_errors)
        _tb_str = "\n".join(_tb_lines)
        print(f"\n  [plan] End-of-run report:")
        for _tb_line in _tb_lines:
            print(f"  {_tb_line}")

        # Build user-facing summary from proposed changes + working memory
        files_proposed = change_plan.files_affected if change_plan else []
        if files_proposed:
            change_lines = []
            for ch in change_plan.changes:
                desc = ch.description or ch.action.value
                change_lines.append(f"- **{ch.path}**: {desc}")
            plan_summary = (
                f"Partial plan — proposed changes for {len(files_proposed)} file(s):\n\n"
                + "\n".join(change_lines)
            )
        elif not working_memory.is_empty():
            plan_summary = working_memory.read_all()[:2000]
        else:
            plan_summary = "The agent could not complete the plan within the turn limit. Try a more specific request or increasing the plan turn budget."

        # Build pending_work from what was learned but not yet proposed
        plan_pending_parts: list[str] = []
        if not working_memory.is_empty():
            plan_pending_parts.append(working_memory.read_all()[:400])
        if files_proposed:
            remaining_hint = (
                f"Already proposed changes for: {', '.join(files_proposed)}. "
                "Continue proposing changes for remaining files, then call task_complete."
            )
            plan_pending_parts.append(remaining_hint)
        else:
            plan_pending_parts.append(
                "No changes proposed yet. Use the exploration notes above to "
                "propose_change for each affected file, then call task_complete."
            )
        plan_pending = "\n".join(plan_pending_parts) if plan_pending_parts else "Continue exploration and propose changes."

        # Save checkpoint so plan can be resumed
        save_checkpoint(
            config, repo_path, repo_url, requirements,
            files_proposed, working_memory,
            turns_used=max_turns, max_turns=max_turns,
            summary=plan_summary[:500],
            pending_work=plan_pending,
        )

        plan_result = PlanResult(
            success=not change_plan.is_empty,
            plan=change_plan,
            summary=plan_summary,
            turns_used=max_turns,
            usage_stats=usage_stats,
            partial=True,
            can_explore_deeper=True,
        )

    # --- Save trace (non-blocking — don't let trace save hang the result) ---
    if collector:
        try:
            trace = collector.finalize(
                success=plan_result.success,
                turns_used=plan_result.turns_used,
                files_changed=change_plan.files_affected if change_plan else [],
                summary=plan_result.summary,
            )
            plan_result.trace_id = trace.trace_id
            _save_trace_async(trace, config)
        except Exception as _trace_err:
            print(f"  [trace] Failed to finalize trace: {_trace_err}")

    return plan_result


# ---------------------------------------------------------------------------
# Ask-mode fast path
# ---------------------------------------------------------------------------

_FAST_ANSWER_SYSTEM = """\
You are an expert software engineer. Answer the user's question using ONLY the \
provided project context. If the context does not contain enough information to \
give a confident, accurate answer, respond with exactly: INSUFFICIENT_CONTEXT

Rules:
- Be specific: reference file paths, function names, and patterns from the context.
- Do NOT guess or fabricate information not present in the context.
- If unsure, respond with: INSUFFICIENT_CONTEXT"""


def _retrieve_rag_context(
    question: str,
    code_index: "CodeIndex | None",
    top_k: int = 5,
) -> str:
    """Retrieve relevant code chunks via embeddings for the fast-path.

    Uses hybrid vector + BM25 search to find the most relevant symbols,
    then returns their source text (signature + body) formatted as context.
    """
    if code_index is None:
        return ""
    if code_index.embeddings is None or len(code_index.embeddings) == 0:
        return ""

    try:
        results = code_index.embeddings.find_similar(question, top_k=top_k)
    except Exception:
        return ""

    if not results:
        return ""

    parts: list[str] = ["\n\n## Relevant Code (retrieved via semantic search)"]
    chars_budget = 12_000
    chars_used = 0

    for fqn, score in results:
        if chars_used >= chars_budget:
            break

        # Get the symbol entry for file path and line info
        entry = code_index.symbol_table.get_by_fqn(fqn) if code_index.symbol_table else None

        # Get the full embedded text for this FQN (includes signature + body)
        chunk_text = _get_embedded_text(code_index.embeddings, fqn)
        if not chunk_text:
            continue

        file_info = f" ({entry.file_path}:{entry.line_start})" if entry else ""
        section = f"\n### {fqn}{file_info}\n```\n{chunk_text}\n```"

        if chars_used + len(section) > chars_budget:
            # Truncate this chunk to fit
            remaining = chars_budget - chars_used - 100
            if remaining > 200:
                section = f"\n### {fqn}{file_info}\n```\n{chunk_text[:remaining]}\n...\n```"
            else:
                break

        parts.append(section)
        chars_used += len(section)

    if len(parts) <= 1:
        return ""
    return "\n".join(parts)


def _get_embedded_text(embeddings: "EntityEmbeddings", fqn: str) -> str:
    """Get the full embedded text for a given FQN, merging all chunks."""
    texts = []
    for i, stored_fqn in enumerate(embeddings._fqns):
        if stored_fqn == fqn:
            texts.append(embeddings._texts[i])
    if not texts:
        return ""
    # For single-chunk symbols, return as-is; for multi-chunk, join with separator
    if len(texts) == 1:
        return texts[0]
    return "\n...\n".join(texts)


def _try_fast_answer(
    question: str,
    context: str,
    llm_config: dict,
    full_config: Optional[dict] = None,
    usage_stats: "LLMUsageStats | None" = None,
    code_index: "CodeIndex | None" = None,
) -> Optional[str]:
    """Attempt to answer *question* from pre-built context + RAG retrieval.

    If ``code_index`` is provided, retrieves relevant code chunks via
    embedding similarity and appends them to the context. This allows
    the fast-path to answer code-specific questions without agent exploration.

    Returns the answer string if the LLM is confident, or ``None`` if the
    context is insufficient (triggering fallback to the full agent loop).
    """
    from src.llm_client import chat_completion

    # Retrieve relevant code via embeddings (RAG)
    rag_context = _retrieve_rag_context(question, code_index, top_k=5)

    # Cap context to avoid blowing token limits on the fast path
    max_context_chars = 15_000
    max_rag_chars = 12_000
    trimmed_context = context[:max_context_chars]
    trimmed_rag = rag_context[:max_rag_chars]

    user_content = f"## Project context\n{trimmed_context}\n"
    if trimmed_rag:
        user_content += f"\n{trimmed_rag}\n"
    user_content += f"\n## Question\n{question}"

    messages = [
        {"role": "system", "content": _FAST_ANSWER_SYSTEM},
        {"role": "user", "content": user_content},
    ]

    content, _msg = chat_completion(
        messages=messages,
        config=llm_config,
        tools=None,
        tool_choice="none",
        temperature=0.1,
        full_config=full_config,
        usage_stats=usage_stats,
        usage_category="ask_fast_path",
    )

    if not content or "INSUFFICIENT_CONTEXT" in content:
        return None

    return content.strip()


# ---------------------------------------------------------------------------
# Ask-mode entry point
# ---------------------------------------------------------------------------

def generate_answer_with_agent(
    question: str,
    repo_path: str,
    llm_config: dict,
    max_turns: int = 20,
    verbose: bool = False,
    consciousness: "ProjectConsciousness | None" = None,
    agent_config: Optional[dict] = None,
    config: Optional[dict] = None,
    repo_url: str = "",
    repo_knowledge: str = "",
    code_index: "CodeIndex | None" = None,
    resume: bool = False,
    conversation_context: Optional[list[dict]] = None,
) -> "AskResult":
    """Run the agent in ask mode: explore → answer question → complete.

    Returns an :class:`AskResult` with the answer and source files consulted.
    No files are written to disk.
    """
    from src.llm_client import chat_completion, LLMUsageStats
    from src.code.file_cache import reset_session_cache
    reset_session_cache()

    repo_root = Path(repo_path)
    agent_cfg = agent_config or {}
    max_turns = agent_cfg.get("ask_max_turns", agent_cfg.get("max_turns", max_turns))

    # LLM usage tracking
    usage_stats = LLMUsageStats()
    smart_summarization = agent_cfg.get("smart_summarization", True)
    truncation_limit = agent_cfg.get("truncation_limit", 30_000)

    working_memory = WorkingMemory()
    sources_consulted: set[str] = set()

    # --- GCC (opt-in structured versioned memory) ---
    gcc_controller: Optional[GCCController] = None
    if agent_cfg.get("gcc_enabled", False):
        gcc_controller = GCCController(
            repo_id=compute_repo_id(repo_path, repo_url),
            storage_dir=agent_cfg.get("gcc_storage_dir", ""),
        )

    # --- Execution tracing ---
    tracing_enabled = is_tracing_enabled(config)
    collector: Optional[TraceCollector] = None
    if tracing_enabled:
        _repo_id = compute_repo_id(repo_path, repo_url)
        collector = TraceCollector(
            repo_id=_repo_id,
            repo_url=repo_url,
            model=_resolve_model_name(llm_config),
            requirements=question,
        )

    # Build ask-mode tool list (read + memory + ask completion + code_index)
    all_tools = build_ask_tools(agent_cfg, code_index=code_index)

    # Build focused context (question-relevant only)
    initial_context = ""
    try:
        from src.agent.context import build_smart_initial_context
        initial_context = build_smart_initial_context(
            repo_path, question, consciousness=consciousness,
        )
    except ImportError:
        if consciousness is not None:
            initial_context = consciousness.to_context_string()

    # Repo knowledge (hand-written .code-autonomy.md)
    repo_knowledge_section = f"\n{repo_knowledge}\n" if repo_knowledge else ""

    # Prior knowledge from previous runs (skip if repo_knowledge already present)
    knowledge_context = ""
    if not repo_knowledge:
        try:
            prior = load_knowledge(config, repo_path, repo_url)
            if prior:
                knowledge_context = prior.to_context_string()
        except Exception:
            pass
    knowledge_section = f"\n\n{knowledge_context}\n" if knowledge_context else ""

    # Classify question early (used by direct lookup and search guidance)
    q_type = _classify_question(question)

    # --- Zero-LLM direct lookup for simple file/property questions ---
    if q_type == "lookup":
        try:
            from src.agent.direct_lookup import direct_lookup
            direct_answer = direct_lookup(question, repo_path, consciousness=consciousness)
            if direct_answer is not None:
                return AskResult(
                    success=True,
                    answer=direct_answer,
                    sources=[],
                    summary="Answered via direct file lookup (zero LLM calls)",
                    turns_used=0,
                    usage_stats=usage_stats,
                )
        except Exception:
            pass

    # --- Fast-path: try answering from available context + RAG retrieval ---
    available_context = (initial_context + repo_knowledge_section + knowledge_section).strip()
    if available_context and len(available_context) > 200:
        try:
            fast_answer = _try_fast_answer(
                question, available_context, llm_config, config, usage_stats,
                code_index=code_index,
            )
            if fast_answer is not None:
                rag_used = " + RAG" if code_index and code_index.embeddings and len(code_index.embeddings) > 0 else ""
                if verbose:
                    print(f"  Ask fast-path{rag_used}: answered from existing context (0 tool calls)")
                return AskResult(
                    success=True,
                    answer=fast_answer,
                    sources=[],
                    summary=f"Answered from project context{rag_used} (fast path, no file exploration needed)",
                    turns_used=1,
                    usage_stats=usage_stats,
                )
        except Exception:
            pass  # Fall through to full agent loop
    splunk_enabled = agent_cfg.get("splunk_enabled", False)

    if q_type == "lookup":
        max_turns = min(max_turns, 4)
        search_guidance = (
            "The question targets a specific file or property. "
            "Use find_files to locate the file, read_file to get its contents, "
            "then call task_complete with the answer. Aim for 2-4 tool calls."
        )
    elif splunk_enabled:
        search_guidance = (
            "For questions about logs, errors, metrics, or production behavior, "
            "prefer splunk_ask() as the first tool call for a quick answer. "
            "For code/file questions, use list_dir and find_files to explore the repo. "
            "When you have a complete answer, call task_complete."
        )
    else:
        search_guidance = (
            "Start by listing the repo root with list_dir, then explore relevant files "
            "to answer the question. When you have a complete answer, call task_complete."
        )

    user_msg = (
        f"## Question\n{question}\n"
        f"{initial_context}\n"
        f"{repo_knowledge_section}"
        f"{knowledge_section}\n\n"
        f"{search_guidance}"
    )

    # Check for prior exploration notes on this question
    try:
        from src.agent.knowledge import load_ask_notes
        prior_notes = load_ask_notes(repo_path, question)
    except Exception:
        prior_notes = None

    if prior_notes:
        user_msg += (
            f"\n\n## Prior Exploration Notes\n"
            f"A previous session explored this question but ran out of time. "
            f"Here is what was found:\n{prior_notes['partial_answer']}\n\n"
            f"Sources consulted: {', '.join(prior_notes.get('sources', []))}\n\n"
            f"Build on this — don't re-explore what was already found. "
            f"Focus on filling gaps and completing the answer."
        )

    system_prompt = _ASK_SYSTEM_PROMPT
    if gcc_controller:
        system_prompt += _GCC_ASK_PROMPT_SECTION
    if agent_cfg.get("splunk_enabled"):
        system_prompt += _SPLUNK_PROMPT_SECTION
    if agent_cfg.get("certs_enabled"):
        system_prompt += _CERTS_PROMPT_SECTION

    if conversation_context:
        context_lines = []
        for msg in conversation_context[-6:]:
            prefix = "User" if msg.get("role") == "user" else "Assistant"
            content = msg.get("content", "")[:500]
            context_lines.append(f"{prefix}: {content}")
        system_prompt += "\n\n## Prior Conversation\n" + "\n".join(context_lines)

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]

    # ------------------------------------------------------------------ #
    # Resume from checkpoint (if requested)
    # ------------------------------------------------------------------ #
    if resume:
        existing_checkpoint = load_checkpoint(config, repo_path, repo_url)
        if existing_checkpoint:
            req_hash = compute_requirement_hash(question)
            if existing_checkpoint.requirement_hash == req_hash:
                checkpoint_context = existing_checkpoint.to_context_string()
                # Restore working memory
                for k, v in existing_checkpoint.working_memory.items():
                    working_memory.update(k, v)
                # Restore source files from checkpoint
                for f in existing_checkpoint.files_changed:
                    sources_consulted.add(f)
                # Inject checkpoint context into user message
                messages[1]["content"] = user_msg + f"\n\n{checkpoint_context}\n"
                # Inject restored working memory into system prompt
                if not working_memory.is_empty():
                    messages[0]["content"] = system_prompt + "\n" + working_memory.to_message_block()
                print(f"  [ask-resume] Restored checkpoint: {existing_checkpoint.turns_used}/{existing_checkpoint.max_turns} turns, {len(existing_checkpoint.files_changed)} source(s)")
            else:
                print("  [ask-resume] Checkpoint found but question differs — starting fresh")
        else:
            print("  [ask-resume] No checkpoint found — starting fresh")

    # Inject pre-populated working memory into system prompt
    if not working_memory.is_empty() and "<working_memory>" not in messages[0]["content"]:
        messages[0]["content"] = system_prompt + "\n" + working_memory.to_message_block()

    task_complete_data: Optional[dict] = None
    consecutive_empty = 0
    consecutive_empty_greps = 0  # Track consecutive grep calls with 0 results
    tool_call_counts: dict[str, int] = {}
    tool_errors: dict[str, int] = {}
    consecutive_api_errors = 0
    model_name = _resolve_model_name(llm_config)

    for turn in range(max_turns):
        # --- Context management ---
        ctx_span_id = None
        if collector:
            ctx_span_id = collector.start_span(
                SPAN_CONTEXT_MGMT, "manage_context", turn,
                inputs={"message_count": len(messages)},
            )
        try:
            from src.agent.context import manage_conversation_context
            prev_count = len(messages)
            messages = manage_conversation_context(
                messages, model=model_name, llm_config=llm_config,
                smart_summarization=smart_summarization,
                full_config=config,
                usage_stats=usage_stats,
            )
            if collector and ctx_span_id:
                collector.end_span(
                    ctx_span_id,
                    output_summary=f"{prev_count} -> {len(messages)} messages",
                    metadata={"messages_before": prev_count, "messages_after": len(messages)},
                )
                ctx_span_id = None
        except ImportError:
            pass
        if collector and ctx_span_id:
            collector.end_span(ctx_span_id, output_summary="skipped (no context module)")

        # --- LLM call ---
        llm_span_id = None
        if collector:
            tokens_est = sum(len(m.get("content", "") or "") // 4 for m in messages)
            llm_span_id = collector.start_span(
                SPAN_LLM_CALL, model_name, turn,
                inputs={"message_count": len(messages), "tokens_est": tokens_est},
                metadata={"model": model_name, "temperature": float(llm_config.get("temperature", 0.2))},
            )

        try:
            content, msg = chat_completion(
                messages=messages,
                config=llm_config,
                tools=all_tools,
                tool_choice="auto",
                temperature=float(llm_config.get("temperature", 0.2)),
                full_config=config,
                usage_stats=usage_stats,
            )
            consecutive_api_errors = 0
        except Exception as api_err:
            consecutive_api_errors += 1
            print(f"  [ask] LLM API error (attempt {consecutive_api_errors}): {api_err}")
            if collector and llm_span_id:
                collector.end_span(
                    llm_span_id,
                    output_summary=f"API error: {str(api_err)[:100]}",
                    success=False,
                    error=str(api_err)[:200],
                )
                llm_span_id = None
            if consecutive_api_errors >= MAX_CONSECUTIVE_API_ERRORS:
                print(f"  [ask] Aborting: {consecutive_api_errors} consecutive API errors")
                break
            err_str = str(api_err)
            if "400" in err_str or "Bad Request" in err_str:
                if len(messages) > 11:
                    messages = [messages[0]] + messages[-10:]
            messages.append({
                "role": "user",
                "content": (
                    f"The previous LLM call failed with: {str(api_err)[:200]}. "
                    "Please continue with the task."
                ),
            })
            continue

        tool_calls = getattr(msg, "tool_calls", None)

        if collector and llm_span_id:
            n_tool_calls = len(tool_calls) if tool_calls else 0
            content_len = len(content) if content else 0
            collector.end_span(
                llm_span_id,
                output_summary=f"{n_tool_calls} tool calls, {content_len} chars content",
                output_chars=content_len,
                metadata={"tool_call_count": n_tool_calls},
            )

        # ---- No tool calls ----
        if not tool_calls or len(tool_calls) == 0:
            if task_complete_data:
                break
            consecutive_empty += 1
            if consecutive_empty >= MAX_CONSECUTIVE_EMPTY:
                break
            messages.append({"role": "assistant", "content": content})
            messages.append({
                "role": "user",
                "content": (
                    "Please use the read tools to explore the codebase and answer the question. "
                    "When you have a complete answer, call task_complete."
                ),
            })
            continue

        # ---- Process tool calls ----
        consecutive_empty = 0
        messages.append({
            "role": "assistant",
            "content": msg.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments or "{}",
                    },
                }
                for tc in tool_calls
            ],
        })

        for tc in tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments) if tc.function.arguments else {}
            except json.JSONDecodeError:
                args = {}

            tool_call_counts[name] = tool_call_counts.get(name, 0) + 1

            tool_span_id = None
            if collector:
                span_type = SPAN_GCC_COMMAND if name.startswith("gcc_") else SPAN_TOOL_CALL
                tool_span_id = collector.start_span(
                    span_type, name, turn,
                    inputs=_sanitize_tool_args(name, args),
                )

            if name == "task_complete":
                task_complete_data = args
                result = f"Answer complete. Summary: {args.get('summary', '')}"
                # Save GCC state (non-fatal)
                try:
                    if gcc_controller:
                        gcc_controller.save()
                except Exception:
                    pass
                if collector and tool_span_id:
                    collector.end_span(
                        tool_span_id,
                        output_summary=_summarize_output(result),
                        output_chars=len(result),
                        success=True,
                        reward=1.0,
                    )
                if agent_cfg.get("show_activity", True):
                    log_agent_activity(turn, name, args, f"done — {args.get('summary', '')[:50]}")
            else:
                result = execute_ask_tool(
                    repo_root, name, args,
                    working_memory=working_memory,
                    gcc_controller=gcc_controller,
                    code_index=code_index,
                )
                # Track sources from successful read_file calls
                if name == "read_file" and not result.startswith("Error:"):
                    sources_consulted.add(args.get("path", ""))
                # Track consecutive empty grep results for anti-loop detection
                if name == "grep":
                    if result.strip() in ("", "No matches found.", "No matches found"):
                        consecutive_empty_greps += 1
                    else:
                        consecutive_empty_greps = 0
                else:
                    # Non-grep tool call resets the counter
                    consecutive_empty_greps = 0
                if result.startswith("Error"):
                    tool_errors[name] = tool_errors.get(name, 0) + 1
                if agent_cfg.get("show_activity", True):
                    log_agent_activity(turn, name, args, summarize_tool_result(result, name))
                if collector and tool_span_id:
                    is_error = result.startswith("Error:")
                    reward = -1.0 if is_error else 0.5
                    collector.end_span(
                        tool_span_id,
                        output_summary=_summarize_output(result),
                        output_chars=len(result),
                        success=not is_error,
                        error=result[:200] if is_error else "",
                        reward=reward,
                    )

            # Truncation
            if len(result) > truncation_limit:
                try:
                    from src.agent.context import summarize_large_output
                    if smart_summarization:
                        result = summarize_large_output(
                            result, name, llm_config, usage_stats=usage_stats,
                        )
                    else:
                        result = result[:truncation_limit] + f"\n...(truncated, {len(result)} total chars)"
                except ImportError:
                    result = result[:truncation_limit] + f"\n...(truncated, {len(result)} total chars)"

            if verbose:
                print(f"  Ask turn {turn + 1}: {name}({list(args.keys())}) -> {len(result)} chars")

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result,
            })

            # --- Inject working memory / GCC context into system prompt ---
            if (name == "update_memory" and not working_memory.is_empty()) or \
               (name.startswith("gcc_") and gcc_controller):
                wm_block = working_memory.to_message_block() if not working_memory.is_empty() else ""
                gcc_block = gcc_controller.to_message_block() if gcc_controller else ""
                messages[0] = {"role": "system", "content": system_prompt + "\n" + wm_block + gcc_block}

        if task_complete_data:
            break

        # --- Grep anti-loop nudge ---
        # After 3 consecutive empty grep results, nudge the agent to try
        # a different strategy (find_files / list_dir).
        if consecutive_empty_greps >= 3:
            messages.append({
                "role": "user",
                "content": (
                    "Your last 3 grep calls returned no results. The file type may not "
                    "be in the default search set. Try find_files(extension='.properties') "
                    "or list_dir to explore the directory structure instead."
                ),
            })
            consecutive_empty_greps = 0  # Reset after nudge

        # --- Answer deadline nudge ---
        # At 60% of max_turns, nudge the agent to wrap up.
        # At 80%, issue a hard deadline.
        turns_used_so_far = turn + 1
        deadline_soft = int(max_turns * 0.6)
        deadline_hard = int(max_turns * 0.8)
        if turns_used_so_far == deadline_hard:
            messages.append({
                "role": "user",
                "content": (
                    f"DEADLINE: You have used {turns_used_so_far} of {max_turns} turns. "
                    "You MUST call task_complete NOW with your best answer based on "
                    "what you have explored so far. Do NOT explore further."
                ),
            })
        elif turns_used_so_far == deadline_soft:
            messages.append({
                "role": "user",
                "content": (
                    f"Note: You have used {turns_used_so_far} of {max_turns} turns. "
                    "Start wrapping up your exploration and prepare to call "
                    "task_complete with a comprehensive answer soon."
                ),
            })

    # ---- Build result ----
    if task_complete_data:
        # Merge agent-reported sources with tracked sources
        reported_sources = task_complete_data.get("sources", [])
        all_sources = sorted(set(reported_sources) | sources_consulted)
        ask_result = AskResult(
            success=True,
            answer=task_complete_data.get("answer", ""),
            sources=all_sources,
            summary=task_complete_data.get("summary", ""),
            turns_used=turn + 1,
            usage_stats=usage_stats,
        )
    else:
        _tb_lines = _format_tool_breakdown(tool_call_counts, tool_errors)
        _tb_str = "\n".join(_tb_lines)
        print(f"\n  [ask] End-of-run report:")
        for _tb_line in _tb_lines:
            print(f"  {_tb_line}")

        # --- Recovery: synthesize partial answer from what the agent explored ---
        partial_answer = ""
        try:
            recovery_messages = [messages[0]] + messages[-12:]
            recovery_messages.append({
                "role": "user",
                "content": (
                    "You ran out of turns before completing your answer. "
                    "Based on everything you explored and learned so far, provide your "
                    "BEST PARTIAL ANSWER to the original question. Include what you found, "
                    "what you were still investigating, and any open questions. "
                    "Format as a clear, helpful response — this is what the user will see."
                ),
            })
            recovery_content, _ = chat_completion(
                messages=recovery_messages,
                config=llm_config,
                tools=[],
                full_config=config,
                usage_stats=usage_stats,
            )
            if recovery_content and len(recovery_content.strip()) > 20:
                partial_answer = recovery_content.strip()
                if verbose:
                    print(f"  [ask] Recovery call produced {len(partial_answer)} chars")
        except Exception as _recovery_err:
            if verbose:
                print(f"  [ask] Recovery call failed: {_recovery_err}")

        # --- Save exploration notes for future sessions ---
        if partial_answer or sources_consulted:
            try:
                from src.agent.knowledge import save_ask_notes
                save_ask_notes(
                    repo_path=repo_path,
                    repo_url=repo_url,
                    question=question,
                    partial_answer=partial_answer,
                    sources=sorted(sources_consulted),
                )
            except Exception:
                pass  # Non-fatal

        # Build user-facing summary: use partial answer if available,
        # then working memory, then sources — tool breakdown is internal-only.
        if partial_answer:
            ask_summary = partial_answer
            if sources_consulted:
                ask_summary += f"\n\n---\nSources consulted: {', '.join(sorted(sources_consulted))}"
        elif not working_memory.is_empty():
            ask_summary = working_memory.read_all()[:2000]
            if sources_consulted:
                ask_summary += f"\n\n---\nSources consulted: {', '.join(sorted(sources_consulted))}"
        elif sources_consulted:
            ask_summary = (
                f"Explored {len(sources_consulted)} source file(s) but ran out of turns before synthesising an answer.\n\n"
                f"Sources consulted: {', '.join(sorted(sources_consulted))}"
            )
        else:
            ask_summary = "The agent could not find relevant information within the turn limit. Try rephrasing the question or increasing the ask turn budget."

        # Build pending_work: what was found + what still needs investigation
        ask_pending_parts: list[str] = []
        if partial_answer:
            ask_pending_parts.append(
                "Partial answer so far:\n" + partial_answer[:300]
            )
        if not working_memory.is_empty():
            ask_pending_parts.append(working_memory.read_all()[:300])
        if sources_consulted:
            ask_pending_parts.append(
                f"Already explored: {', '.join(sorted(sources_consulted))}. "
                "Build on these findings — don't re-read these files. "
                "Focus on filling gaps and completing the answer."
            )
        else:
            ask_pending_parts.append(
                "No files explored yet. Start exploring to answer the question."
            )
        ask_pending = "\n".join(ask_pending_parts) if ask_pending_parts else "Continue exploring to answer the question."

        # Save checkpoint so ask session can be resumed with working memory
        save_checkpoint(
            config, repo_path, repo_url, question,
            sorted(sources_consulted), working_memory,
            turns_used=max_turns, max_turns=max_turns,
            summary=partial_answer[:500] if partial_answer else ask_summary[:500],
            pending_work=ask_pending,
        )

        ask_result = AskResult(
            success=False,
            answer=partial_answer,
            sources=sorted(sources_consulted),
            summary=ask_summary,
            turns_used=max_turns,
            usage_stats=usage_stats,
            partial=True,
            can_explore_deeper=True,
        )

    # --- Save trace (non-blocking) ---
    if collector:
        try:
            trace = collector.finalize(
                success=ask_result.success,
                turns_used=ask_result.turns_used,
                files_changed=ask_result.sources,
                summary=ask_result.summary,
            )
            ask_result.trace_id = trace.trace_id
            _save_trace_async(trace, config)
        except Exception as _trace_err:
            print(f"  [trace] Failed to finalize trace: {_trace_err}")

    return ask_result
