"""
Agent-based code analysis with tool use (Claude-Code-like).

The agent iteratively explores, edits, tests, and fixes code within a single
agentic loop.  Supports OpenAI, Anthropic, Gemini via the unified LLM client.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.agent.tools import build_agent_tools, execute_tool, AGENT_TOOLS
from src.agent.knowledge import WorkingMemory, load_knowledge, save_knowledge
from src.agent.ai_utils import parse_ai_changes


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

    # Load persistent knowledge from previous runs
    knowledge_context = ""
    try:
        prior = load_knowledge(config, repo_path, repo_url)
        if prior:
            knowledge_context = prior.to_context_string()
    except Exception:
        pass  # non-fatal

    # Build the full tool list (read + write + exec + memory + complete)
    all_tools = build_agent_tools(agent_cfg)

    # ------------------------------------------------------------------ #
    # Build initial context (requirement-aware)
    # ------------------------------------------------------------------ #
    initial_context = ""
    try:
        from src.agent.context import build_smart_initial_context
        from src.consciousness.core import ProjectConsciousness

        if consciousness_context:
            # Try to build the smart version; fall back to raw string
            initial_context = consciousness_context
    except ImportError:
        initial_context = consciousness_context or ""

    # Testing strategy context
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

    user_msg = (
        f"## Requirements\n{requirements}\n"
        f"{initial_context}\n"
        f"{framework_section}"
        f"{testing_section}"
        f"{ref_section}"
        f"{knowledge_section}\n\n"
        "Start by listing the repo root with list_dir, then explore relevant files "
        "before making any changes."
    )

    messages: list[dict] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]

    # ------------------------------------------------------------------ #
    # Agent loop
    # ------------------------------------------------------------------ #
    task_complete_data: Optional[dict] = None
    last_error_hash: Optional[str] = None
    stuck_count = 0

    model_name = llm_config.get("model", "gpt-4o")

    for turn in range(max_turns):
        # --- Context management (token-aware) ---
        try:
            from src.agent.context import manage_conversation_context

            messages = manage_conversation_context(
                messages,
                model=model_name,
                llm_config=llm_config,
                smart_summarization=smart_summarization,
            )
        except ImportError:
            pass  # graceful degradation

        # --- LLM call ---
        content, msg = chat_completion(
            messages=messages,
            config=llm_config,
            tools=all_tools,
            tool_choice="auto",
            temperature=0.2,
        )

        tool_calls = getattr(msg, "tool_calls", None)

        # ---- No tool calls: LLM is either done or confused ----
        if not tool_calls or len(tool_calls) == 0:
            if task_complete_data:
                break

            # Backward compat: try parsing legacy JSON changes
            parsed = parse_ai_changes(content)
            if parsed:
                return AgentResult(
                    success=True,
                    changes=parsed,
                    turns_used=turn + 1,
                    summary="Legacy JSON output mode",
                )

            # Nudge the agent to use tools
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
            else:
                result = execute_tool(
                    repo_root, name, args,
                    changes_tracker=changes_tracker,
                    agent_config=agent_cfg,
                    working_memory=working_memory,
                )

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
                base_prompt = _SYSTEM_PROMPT
                messages[0] = {"role": "system", "content": base_prompt + "\n" + wm_block}

            # --- Stuck detection (same error 3 times) ---
            if name == "run_command" and "[exit code:" in result and "exit code: 0]" not in result:
                err_hash = str(hash(result[:500]))
                if err_hash == last_error_hash:
                    stuck_count += 1
                else:
                    last_error_hash = err_hash
                    stuck_count = 1
                if stuck_count >= 3:
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
    # Build result
    # ------------------------------------------------------------------ #
    if task_complete_data:
        return AgentResult(
            success=True,
            files_changed=sorted(changes_tracker),
            summary=task_complete_data.get("summary", ""),
            turns_used=turn + 1,
            tests_passed=True,
        )

    # Agent exhausted turns without completing
    return AgentResult(
        success=False,
        files_changed=sorted(changes_tracker),
        summary=f"Agent did not call task_complete within {max_turns} turns",
        turns_used=max_turns,
    )
