"""
Agent-based code analysis with tool use (Claude-Code-like).

The agent iteratively explores, edits, tests, and fixes code within a single
agentic loop.  Supports OpenAI, Anthropic, Gemini via the unified LLM client.
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.agent.tools import build_agent_tools, build_plan_tools, build_ask_tools, execute_tool, execute_plan_tool, execute_ask_tool, AGENT_TOOLS
from src.agent.knowledge import WorkingMemory, load_knowledge, save_knowledge, compute_repo_id
from src.agent.gcc import GCCController
from src.agent.ai_utils import parse_ai_changes
from src.agent.activity import log_agent_activity, summarize_tool_result
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


@dataclass
class PlanResult:
    """Result from the plan-mode agent loop."""

    success: bool = False
    plan: "ChangePlan | None" = None
    summary: str = ""
    turns_used: int = 0
    trace_id: str = ""


@dataclass
class AskResult:
    """Result from ask-mode agent loop."""

    success: bool = False
    answer: str = ""
    sources: list[str] = field(default_factory=list)
    summary: str = ""
    turns_used: int = 0
    trace_id: str = ""


# ---------------------------------------------------------------------------
# Guard: abort after N consecutive empty LLM responses
# ---------------------------------------------------------------------------
MAX_CONSECUTIVE_EMPTY = 3


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

## Completion
- task_complete(summary, files_changed): Call when ALL changes are done and verified

## Workflow
1. **EXPLORE** — Use read tools to understand the codebase structure, conventions, and the files relevant to the requirements.
2. **RECORD** — After exploring, use update_memory to record what you learn (project overview, patterns, important files).
3. **IMPLEMENT** — Use write/edit tools to make changes incrementally. Prefer edit_file for existing files (surgical, not full replacement). Use write_file only for brand-new files.
4. **VERIFY** — Run tests with run_command after making changes (e.g., `pytest -v`, `mvn test`).
5. **FIX** — If tests fail, read the error output, edit files to fix the issues, and re-run tests.
6. **COMPLETE** — Call task_complete with a summary and the list of files changed.

## Rules
- ALWAYS explore before modifying. Read existing files to understand conventions and structure.
- Use update_memory to record project knowledge after initial exploration (language, build tool, patterns, key files).
- The old_string in edit_file MUST match exactly (including whitespace and indentation). Include enough surrounding context to make the match unique.
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

## Completion
- task_complete(answer, sources): Call when you have fully answered the question.

## Workflow
1. **EXPLORE** — Use read tools to understand the codebase and find information relevant to the question.
2. **RECORD** — Use update_memory to record what you learn.
3. **ANSWER** — Call task_complete with your complete answer and the list of source files consulted.

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
    consciousness_context: str = "",
    framework_context: str = "",
    config: Optional[dict] = None,
    repo_url: str = "",
    instruction_suffix: str = "",
) -> tuple[str, str]:
    """Build the user message and knowledge context for both agent and plan modes.

    Returns (user_message, knowledge_context).
    """
    from pathlib import Path
    repo_root = Path(repo_path)

    # Load persistent knowledge
    knowledge_context = ""
    try:
        prior = load_knowledge(config, repo_path, repo_url)
        if prior:
            knowledge_context = prior.to_context_string()
    except Exception:
        pass

    # Initial context (consciousness)
    initial_context = ""
    try:
        from src.agent.context import build_smart_initial_context
        from src.consciousness.core import ProjectConsciousness
        if consciousness_context:
            initial_context = consciousness_context
    except ImportError:
        initial_context = consciousness_context or ""

    # Testing strategy
    testing_section = ""
    try:
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
    knowledge_section = f"\n\n{knowledge_context}\n" if knowledge_context else ""

    suffix = instruction_suffix or (
        "Start by listing the repo root with list_dir, then explore relevant files "
        "before making any changes."
    )

    user_msg = (
        f"## Requirements\n{requirements}\n"
        f"{initial_context}\n"
        f"{framework_section}"
        f"{testing_section}"
        f"{ref_section}"
        f"{knowledge_section}\n\n"
        f"{suffix}"
    )

    return user_msg, knowledge_context


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
    consciousness_context: str = "",
    framework_context: str = "",
    agent_config: Optional[dict] = None,
    config: Optional[dict] = None,
    repo_url: str = "",
) -> AgentResult:
    """Run the agentic loop: explore → edit → test → fix → complete.

    Returns an :class:`AgentResult` with *success*, *files_changed*,
    *summary*, etc.  When the LLM falls back to legacy JSON-output mode the
    result carries ``changes`` instead.
    """
    from src.llm_client import chat_completion

    repo_root = Path(repo_path)
    agent_cfg = agent_config or {}
    max_turns = agent_cfg.get("max_turns", max_turns)
    smart_summarization = agent_cfg.get("smart_summarization", True)
    truncation_limit = agent_cfg.get("truncation_limit", 30_000)

    # Track every file the agent creates / edits / deletes
    changes_tracker: set[str] = set()

    # Working memory (survives context compression)
    working_memory = WorkingMemory()

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
            model=llm_config.get("model", "gpt-4o"),
            requirements=requirements,
        )

    # Build the full tool list (read + write + exec + memory + complete)
    all_tools = build_agent_tools(agent_cfg)

    # Build shared context
    user_msg, _knowledge_ctx = _build_agent_context(
        requirements=requirements,
        repo_path=repo_path,
        llm_config=llm_config,
        reference_pr_content=reference_pr_content,
        testing_strategy=testing_strategy,
        build_tool=build_tool,
        consciousness_context=consciousness_context,
        framework_context=framework_context,
        config=config,
        repo_url=repo_url,
    )

    system_prompt = _SYSTEM_PROMPT
    if gcc_controller:
        system_prompt += _GCC_PROMPT_SECTION

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]

    # ------------------------------------------------------------------ #
    # Agent loop
    # ------------------------------------------------------------------ #
    task_complete_data: Optional[dict] = None
    last_error_hash: Optional[str] = None
    stuck_count = 0
    consecutive_empty = 0

    model_name = llm_config.get("model", "gpt-4o")

    for turn in range(max_turns):
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
                metadata={"model": model_name, "temperature": 0.2},
            )

        content, msg = chat_completion(
            messages=messages,
            config=llm_config,
            tools=all_tools,
            tool_choice="auto",
            temperature=0.2,
            full_config=config,
        )

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
                )
                if collector:
                    try:
                        trace = collector.finalize(
                            success=True, turns_used=turn + 1,
                            files_changed=[], summary="Legacy JSON output mode",
                        )
                        legacy_result.trace_id = trace.trace_id
                        get_trace_store(config).save(trace)
                    except Exception:
                        pass
                return legacy_result

            # Nudge the agent to use tools
            consecutive_empty += 1
            if consecutive_empty >= MAX_CONSECUTIVE_EMPTY:
                logger.error(
                    "Aborting agent loop: %d consecutive empty LLM responses",
                    consecutive_empty,
                )
                break
            messages.append({"role": "assistant", "content": content})
            messages.append({
                "role": "user",
                "content": (
                    "Please use the tools to implement the changes. "
                    "When everything is done and tests pass, call task_complete."
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

            # --- Start tool span ---
            tool_span_id = None
            if collector:
                span_type = SPAN_GCC_COMMAND if name.startswith("gcc_") else SPAN_TOOL_CALL
                tool_span_id = collector.start_span(
                    span_type, name, turn,
                    inputs=_sanitize_tool_args(name, args),
                )

            # --- task_complete: signal termination + save knowledge ---
            if name == "task_complete":
                task_complete_data = args
                result = f"Task marked complete. Summary: {args.get('summary', '')}"
                # Save knowledge (non-fatal)
                try:
                    if not working_memory.is_empty():
                        save_knowledge(
                            config, repo_path, repo_url,
                            working_memory,
                            summary=args.get("summary", ""),
                            files_changed=args.get("files_changed"),
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
                result = execute_tool(
                    repo_root, name, args,
                    changes_tracker=changes_tracker,
                    agent_config=agent_cfg,
                    working_memory=working_memory,
                    gcc_controller=gcc_controller,
                )
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

            # Intelligent summarization for large outputs
            if len(result) > truncation_limit:
                try:
                    from src.agent.context import summarize_large_output

                    if smart_summarization:
                        result = summarize_large_output(result, name, llm_config)
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

            # --- Working memory protection: inject into system prompt ---
            if name == "update_memory" and not working_memory.is_empty():
                wm_block = working_memory.to_message_block()
                gcc_block = gcc_controller.to_message_block() if gcc_controller else ""
                messages[0] = {"role": "system", "content": system_prompt + "\n" + wm_block + gcc_block}

            # --- GCC context injection after gcc_* tool calls ---
            if name.startswith("gcc_") and gcc_controller:
                gcc_block = gcc_controller.to_message_block()
                wm_block = working_memory.to_message_block() if not working_memory.is_empty() else ""
                messages[0] = {"role": "system", "content": system_prompt + "\n" + wm_block + gcc_block}

            # --- Stuck detection (same error 3 times) ---
            if name == "run_command" and "[exit code:" in result and "exit code: 0]" not in result:
                err_hash = str(hash(result[:500]))
                if err_hash == last_error_hash:
                    stuck_count += 1
                else:
                    last_error_hash = err_hash
                    stuck_count = 1
                if stuck_count >= 3:
                    if collector:
                        collector.add_event(
                            SPAN_STUCK_DETECT, "stuck_3x_same_error", turn,
                            inputs={"error_hash": err_hash},
                            reward=-1.0,
                        )
                    messages.append({
                        "role": "user",
                        "content": (
                            "The same test failure has occurred 3 times. "
                            "Step back and consider a different approach to fix this issue. "
                            "Re-read the failing test and the relevant source code before editing."
                        ),
                    })
                    stuck_count = 0

        if task_complete_data:
            break

    # ------------------------------------------------------------------ #
    # Build result + finalize trace
    # ------------------------------------------------------------------ #
    if task_complete_data:
        result_obj = AgentResult(
            success=True,
            files_changed=sorted(changes_tracker),
            summary=task_complete_data.get("summary", ""),
            turns_used=turn + 1,
            tests_passed=True,
        )
    else:
        # Agent exhausted turns without completing
        result_obj = AgentResult(
            success=False,
            files_changed=sorted(changes_tracker),
            summary=f"Agent did not call task_complete within {max_turns} turns",
            turns_used=max_turns,
        )

    # --- Save execution trace ---
    if collector:
        try:
            trace = collector.finalize(
                success=result_obj.success,
                turns_used=result_obj.turns_used,
                files_changed=result_obj.files_changed,
                summary=result_obj.summary,
            )
            result_obj.trace_id = trace.trace_id
            store = get_trace_store(config)
            trace_path = store.save(trace)
            if verbose:
                print(f"  Trace saved: {trace_path} ({trace.metrics.get('total_spans', 0)} spans)")
        except Exception:
            pass  # tracing is non-fatal

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
    consciousness_context: str = "",
    framework_context: str = "",
    agent_config: Optional[dict] = None,
    config: Optional[dict] = None,
    repo_url: str = "",
) -> "PlanResult":
    """Run the agent in plan mode: explore → propose changes → complete.

    Returns a :class:`PlanResult` with the accumulated :class:`ChangePlan`.
    No files are written to disk.
    """
    from src.llm_client import chat_completion
    from src.agent.plan import ChangePlan

    repo_root = Path(repo_path)
    agent_cfg = agent_config or {}
    max_turns = agent_cfg.get("plan_max_turns", agent_cfg.get("max_turns", max_turns))
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
            model=llm_config.get("model", "gpt-4o"),
            requirements=requirements,
        )

    # Build plan-mode tool list (read + propose + memory + completion)
    all_tools = build_plan_tools(agent_cfg)

    # Build shared context
    user_msg, _knowledge_ctx = _build_agent_context(
        requirements=requirements,
        repo_path=repo_path,
        llm_config=llm_config,
        reference_pr_content=reference_pr_content,
        testing_strategy=testing_strategy,
        build_tool=build_tool,
        consciousness_context=consciousness_context,
        framework_context=framework_context,
        config=config,
        repo_url=repo_url,
        instruction_suffix=(
            "Start by listing the repo root with list_dir, then explore relevant files. "
            "Once you understand the codebase, use propose_change to propose ALL needed changes. "
            "When done proposing, call task_complete."
        ),
    )

    system_prompt = _PLAN_SYSTEM_PROMPT
    if gcc_controller:
        system_prompt += _GCC_PROMPT_SECTION

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]

    task_complete_data: Optional[dict] = None
    consecutive_empty = 0
    model_name = llm_config.get("model", "gpt-4o")

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
                metadata={"model": model_name, "temperature": 0.2},
            )

        content, msg = chat_completion(
            messages=messages,
            config=llm_config,
            tools=all_tools,
            tool_choice="auto",
            temperature=0.2,
            full_config=config,
        )

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
                logger.error(
                    "Aborting plan loop: %d consecutive empty LLM responses",
                    consecutive_empty,
                )
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
                )
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
                        result = summarize_large_output(result, name, llm_config)
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

            # Working memory protection
            if name == "update_memory" and not working_memory.is_empty():
                wm_block = working_memory.to_message_block()
                gcc_block = gcc_controller.to_message_block() if gcc_controller else ""
                messages[0] = {"role": "system", "content": system_prompt + "\n" + wm_block + gcc_block}

            # GCC context injection after gcc_* tool calls
            if name.startswith("gcc_") and gcc_controller:
                gcc_block = gcc_controller.to_message_block()
                wm_block = working_memory.to_message_block() if not working_memory.is_empty() else ""
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
        )
    else:
        plan_result = PlanResult(
            success=not change_plan.is_empty,
            plan=change_plan,
            summary=f"Agent did not call task_complete within {max_turns} turns",
            turns_used=max_turns,
        )

    # --- Save trace ---
    if collector:
        try:
            trace = collector.finalize(
                success=plan_result.success,
                turns_used=plan_result.turns_used,
                files_changed=change_plan.files_affected if change_plan else [],
                summary=plan_result.summary,
            )
            plan_result.trace_id = trace.trace_id
            store = get_trace_store(config)
            store.save(trace)
        except Exception:
            pass

    return plan_result


# ---------------------------------------------------------------------------
# Ask-mode entry point
# ---------------------------------------------------------------------------

def generate_answer_with_agent(
    question: str,
    repo_path: str,
    llm_config: dict,
    max_turns: int = 20,
    verbose: bool = False,
    consciousness_context: str = "",
    agent_config: Optional[dict] = None,
    config: Optional[dict] = None,
    repo_url: str = "",
) -> "AskResult":
    """Run the agent in ask mode: explore → answer question → complete.

    Returns an :class:`AskResult` with the answer and source files consulted.
    No files are written to disk.
    """
    from src.llm_client import chat_completion

    repo_root = Path(repo_path)
    agent_cfg = agent_config or {}
    max_turns = agent_cfg.get("ask_max_turns", agent_cfg.get("max_turns", max_turns))
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
            model=llm_config.get("model", "gpt-4o"),
            requirements=question,
        )

    # Build ask-mode tool list (read + memory + ask completion)
    all_tools = build_ask_tools(agent_cfg)

    # Build simplified context (question + consciousness + prior knowledge)
    knowledge_context = ""
    try:
        prior = load_knowledge(config, repo_path, repo_url)
        if prior:
            knowledge_context = prior.to_context_string()
    except Exception:
        pass

    initial_context = consciousness_context or ""
    knowledge_section = f"\n\n{knowledge_context}\n" if knowledge_context else ""

    user_msg = (
        f"## Question\n{question}\n"
        f"{initial_context}\n"
        f"{knowledge_section}\n\n"
        "Start by listing the repo root with list_dir, then explore relevant files "
        "to answer the question. When you have a complete answer, call task_complete."
    )

    system_prompt = _ASK_SYSTEM_PROMPT
    if gcc_controller:
        system_prompt += _GCC_ASK_PROMPT_SECTION

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_msg},
    ]

    task_complete_data: Optional[dict] = None
    consecutive_empty = 0
    model_name = llm_config.get("model", "gpt-4o")

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
                metadata={"model": model_name, "temperature": 0.2},
            )

        content, msg = chat_completion(
            messages=messages,
            config=llm_config,
            tools=all_tools,
            tool_choice="auto",
            temperature=0.2,
            full_config=config,
        )

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
                )
                # Track sources from successful read_file calls
                if name == "read_file" and not result.startswith("Error:"):
                    sources_consulted.add(args.get("path", ""))
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
                        result = summarize_large_output(result, name, llm_config)
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

            # Working memory protection
            if name == "update_memory" and not working_memory.is_empty():
                wm_block = working_memory.to_message_block()
                gcc_block = gcc_controller.to_message_block() if gcc_controller else ""
                messages[0] = {"role": "system", "content": system_prompt + "\n" + wm_block + gcc_block}

            # GCC context injection after gcc_* tool calls
            if name.startswith("gcc_") and gcc_controller:
                gcc_block = gcc_controller.to_message_block()
                wm_block = working_memory.to_message_block() if not working_memory.is_empty() else ""
                messages[0] = {"role": "system", "content": system_prompt + "\n" + wm_block + gcc_block}

        if task_complete_data:
            break

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
        )
    else:
        ask_result = AskResult(
            success=False,
            answer="",
            sources=sorted(sources_consulted),
            summary=f"Agent did not call task_complete within {max_turns} turns",
            turns_used=max_turns,
        )

    # --- Save trace ---
    if collector:
        try:
            trace = collector.finalize(
                success=ask_result.success,
                turns_used=ask_result.turns_used,
                files_changed=ask_result.sources,
                summary=ask_result.summary,
            )
            ask_result.trace_id = trace.trace_id
            store = get_trace_store(config)
            store.save(trace)
        except Exception:
            pass

    return ask_result
