# Roadmap: Integrate Features from Reviewed Git Repos

> **Scope:** Implementation plan for 18 features identified in `repo_data.md`,
> sourced from [everything-claude-code](https://github.com/affaan-m/everything-claude-code)
> and [get-shit-done (GSD)](https://github.com/gsd-build/get-shit-done).
>
> **Approach:** Each feature has exact file targets, code-level changes, and
> acceptance criteria. Grouped into 6 sprints by dependency order.

---

## Table of Contents

- [Sprint 1: Agent Loop Hardening](#sprint-1-agent-loop-hardening-week-1) — Features #4, #14, #9
- [Sprint 2: Discuss & Verify](#sprint-2-discuss--verify-week-2) — Features #3, #2, #8
- [Sprint 3: Multi-Agent Orchestration](#sprint-3-multi-agent-orchestration-weeks-3-4) — Features #6, #1, #13
- [Sprint 4: Hooks & Formatting](#sprint-4-hooks--formatting-week-5) — Features #7, #15, #12
- [Sprint 5: Learning System](#sprint-5-learning-system-week-6) — Features #5, #18, #11
- [Sprint 6: UX & Distribution](#sprint-6-ux--distribution-week-7) — Features #10, #16, #17
- [Dependency Graph](#dependency-graph)
- [Test Plan](#test-plan)

---

## Sprint 1: Agent Loop Hardening (Week 1)

### Feature #4 — Deviation Rules with Scope Boundaries

**Source:** GSD (`gsd-executor.md` deviation rules)
**Problem:** Agent spirals into fixing unrelated code, burns 20+ turns on tangents.
**Current state:** Only stuck detection exists (3x same error hash, `analyzer.py:739-762`).

#### 4.1 Add deviation rules to system prompt

**File:** `src/agent/analyzer.py` — append to `_SYSTEM_PROMPT` (after line 139)

```python
_DEVIATION_RULES = """

## Deviation Rules (MUST follow)
When you encounter failures or issues during implementation:
- Rule 1: Auto-fix bugs DIRECTLY caused by your current changes (max 3 attempts per bug).
- Rule 2: Auto-add missing functionality that is EXPLICITLY stated in the requirements.
- Rule 3: Auto-fix build/test blockers caused by your changes (max 3 attempts).
- Rule 4: STOP and call task_complete with pending_work if you encounter:
  - Architectural changes needed beyond the requirements
  - Pre-existing bugs unrelated to your changes
  - Failures in code you did not modify
- SCOPE: Only fix issues directly caused by the current task's changes.
  Do NOT fix pre-existing issues, refactor unrelated code, or change
  architecture without explicit instruction."""
```

Append to the prompt: `system_prompt = _SYSTEM_PROMPT + _DEVIATION_RULES`

#### 4.2 Add deviation tracking in the agent loop

**File:** `src/agent/analyzer.py` — inside the `for turn in range(max_turns):` loop

Add counter tracking alongside existing `stuck_count`:

```python
# After line ~388 (budget tracking section)
deviation_attempts: dict[str, int] = {}  # error_signature → attempt count
MAX_DEVIATION_ATTEMPTS = 3
```

In the `run_command` error detection block (after line ~739), extend stuck detection:

```python
if name == "run_command" and "[exit code:" in result and "exit code: 0]" not in result:
    err_sig = result[:300].strip()
    deviation_attempts[err_sig] = deviation_attempts.get(err_sig, 0) + 1

    if deviation_attempts[err_sig] >= MAX_DEVIATION_ATTEMPTS:
        messages.append({
            "role": "user",
            "content": (
                f"This error has occurred {MAX_DEVIATION_ATTEMPTS} times. "
                "Per deviation rules: stop fixing this issue and call task_complete "
                "with your current progress. Include this error in pending_work."
            ),
        })
```

#### 4.3 Config key

**File:** `src/config_loader.py` — in `"agent"` dict

```python
"max_deviation_attempts": get_int("agent", "max_deviation_attempts", 3),
```

**Acceptance criteria:**
- Agent stops after 3 failed fix attempts for the same error
- Agent never modifies files it didn't originally touch (enforced by prompt)
- `max_deviation_attempts` configurable in config.ini

---

### Feature #14 — Context Window Utilization Tracking

**Source:** Both repos (context discipline as a first-class concern)
**Problem:** Neither user nor agent knows how full the context window is.
**Current state:** `context.py` estimates tokens and compresses at 70%, but never reports utilization.

#### 14.1 Add utilization reporting to context management

**File:** `src/agent/context.py` — in `manage_conversation_context()`

After computing `current_tokens` and `context_limit` (line ~158), add:

```python
utilization = current_tokens / context_limit if context_limit > 0 else 0.0
```

Return utilization alongside messages (change return type or add to a result object).

Simpler approach — inject utilization into agent messages periodically:

**File:** `src/agent/analyzer.py` — inside the agent loop, after context management

```python
# After manage_conversation_context call (~line 475)
from src.agent.context import get_messages_token_count, get_context_limit
current_tokens = get_messages_token_count(messages)
ctx_limit = get_context_limit(model_name)
utilization_pct = int(100 * current_tokens / ctx_limit) if ctx_limit else 0

# Warn at 60% and 80%
if utilization_pct >= 80 and turn > 0 and turn % 5 == 0:
    messages.append({
        "role": "user",
        "content": (
            f"Context window is {utilization_pct}% full. "
            "Prioritize completing the task. Use update_memory to save important "
            "findings before context compression drops older messages."
        ),
    })
elif utilization_pct >= 60 and turn > 0 and turn % 10 == 0:
    messages.append({
        "role": "user",
        "content": (
            f"Context window is {utilization_pct}% full. "
            "Consider using update_memory to persist key findings."
        ),
    })
```

#### 14.2 Show utilization in activity log

**File:** `src/agent/activity.py` — in `log_agent_activity()`

Add optional `context_pct` parameter:

```python
def log_agent_activity(turn, tool_name, args, result_summary, context_pct: int = 0):
    # ... existing code ...
    if context_pct > 0:
        msg += f" [ctx: {context_pct}%]"
```

**Acceptance criteria:**
- User sees `[ctx: 72%]` in activity log
- Agent gets nudged at 60% and warned at 80% context utilization
- No new config keys needed (always on)

---

### Feature #9 — Atomic Git Commits Per Task

**Source:** GSD (commits after each atomic plan execution)
**Problem:** Single commit at end; partial progress lost on failure.
**Current state:** `main.py` calls `stage_and_commit()` once after agent completes.

#### 9.1 Add `checkpoint_commit` tool

**File:** `src/agent/tools.py` — add new tool definition

```python
# In the tool definitions section
CHECKPOINT_COMMIT_TOOL = {
    "type": "function",
    "function": {
        "name": "checkpoint_commit",
        "description": "Create a git checkpoint commit for work done so far. Use after completing a logical unit of work (e.g., finished implementing a class, tests passing for a module). This preserves incremental progress.",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Short commit message describing what was accomplished",
                },
            },
            "required": ["message"],
        },
    },
}
```

**File:** `src/agent/tools.py` — in `execute_tool()`, add handler:

```python
if tool_name == "checkpoint_commit":
    msg = args.get("message", "checkpoint")
    try:
        import subprocess
        subprocess.run(["git", "add", "-A"], cwd=str(repo_root), capture_output=True)
        result_proc = subprocess.run(
            ["git", "commit", "-m", f"checkpoint: {msg}"],
            cwd=str(repo_root), capture_output=True, text=True,
        )
        if result_proc.returncode == 0:
            return f"Checkpoint committed: {msg}"
        else:
            return f"No changes to commit (or error): {result_proc.stderr[:200]}"
    except Exception as e:
        return f"Error creating checkpoint: {e}"
```

**File:** `src/agent/tools.py` — add to tool list builders:

```python
# In build_agent_tools(), include CHECKPOINT_COMMIT_TOOL
```

#### 9.2 Add checkpoint_commit to system prompt

**File:** `src/agent/analyzer.py` — in `_SYSTEM_PROMPT`, add under Execution tools:

```
- checkpoint_commit(message): Save a git checkpoint after completing a logical unit of work. Use between major steps to preserve progress.
```

Add to workflow section:
```
4b. **CHECKPOINT** — After tests pass for a logical unit, use checkpoint_commit to save progress.
```

#### 9.3 Config key to enable/disable

**File:** `src/config_loader.py` — in `"agent"` dict:

```python
"atomic_commits": get_bool("agent", "atomic_commits", False),  # opt-in
```

**File:** `src/agent/tools.py` — conditionally include tool:

```python
def build_agent_tools(agent_config=None, code_index=None):
    tools = [...]
    if (agent_config or {}).get("atomic_commits", False):
        tools.append(CHECKPOINT_COMMIT_TOOL)
    return tools
```

**Acceptance criteria:**
- Agent can call `checkpoint_commit` to save incremental progress
- Off by default (opt-in via `atomic_commits = true`)
- Checkpoint commits use prefix `checkpoint:` for easy identification
- Works in `--repo-path` (local) mode

---

## Sprint 2: Discuss & Verify (Week 2)

### Feature #3 — Discuss-Before-Plan Phase

**Source:** GSD (`discuss-phase.md` command)
**Problem:** Ambiguous requirements waste turns; agent guesses instead of asking.
**Current state:** No pre-execution clarification step.

#### 3.1 New function: `generate_discussion_with_agent()`

**File:** `src/agent/analyzer.py` — new function after `generate_answer_with_agent()`

```python
@dataclass
class DiscussResult:
    """Result from the discuss phase."""
    success: bool = False
    decisions: dict[str, str] = field(default_factory=dict)
    clarifications: list[str] = field(default_factory=list)
    summary: str = ""
    turns_used: int = 0
    usage_stats: "LLMUsageStats | None" = None


_DISCUSS_SYSTEM_PROMPT = """\
You are an expert software engineer in DISCUSS mode. Your job is to ask
clarifying questions about the requirements BEFORE any code is written.

## Read tools (explore the codebase)
- read_file, grep, list_dir, find_files

## Memory tools
- update_memory(key, content): Record decisions and clarifications.
- read_memory(): Read current notes.

## Completion
- task_complete(summary, decisions): Call when all ambiguities are resolved.
  decisions: dict mapping each question to the user's answer.

## Workflow
1. Read the requirements carefully.
2. Explore the codebase briefly to understand what exists.
3. Identify ambiguities, gray areas, and decisions that need user input.
4. Use update_memory to record each decision as it's made.
5. Call task_complete with a summary and the decisions dict.

## What to ask about
- Architecture choices (which pattern, where to put new code)
- Naming preferences (class names, endpoint paths, table names)
- Scope boundaries (what's included vs out of scope)
- Technology choices (which library, which approach)
- Edge cases (error handling, validation rules, limits)

## Rules
- Ask 3-7 focused questions. Do NOT ask obvious questions.
- Do NOT attempt to write code. This is discussion only.
- If the requirements are perfectly clear, call task_complete immediately."""


def generate_discussion_with_agent(
    requirements: str,
    repo_path: str,
    llm_config: dict,
    max_turns: int = 10,
    verbose: bool = False,
    consciousness: "ProjectConsciousness | None" = None,
    agent_config: Optional[dict] = None,
    config: Optional[dict] = None,
    repo_url: str = "",
    repo_knowledge: str = "",
    code_index: "CodeIndex | None" = None,
) -> DiscussResult:
    """Run the discuss phase: explore codebase → ask clarifying questions → record decisions."""
    # Implementation follows the same pattern as generate_answer_with_agent()
    # but uses _DISCUSS_SYSTEM_PROMPT and returns DiscussResult
    ...
```

The implementation mirrors `generate_answer_with_agent()` (lines 1080-1407) but:
- Uses `_DISCUSS_SYSTEM_PROMPT`
- Uses `build_ask_tools()` (read-only + memory + completion)
- Extracts `decisions` dict from `task_complete` args
- Returns `DiscussResult`

#### 3.2 CLI flag

**File:** `main.py` — add argument:

```python
parser.add_argument("--discuss", action="store_true",
                    help="Run discuss phase before agent/plan mode to clarify requirements")
parser.add_argument("--no-discuss", action="store_true",
                    help="Skip discuss phase (for CI/CD pipelines)")
```

#### 3.3 Wire discuss phase into main flow

**File:** `main.py` — before the agent mode block (~line 526), add:

```python
# Discuss phase (optional, before agent/plan mode)
discuss_decisions = ""
if args.discuss and not args.no_discuss and use_agent:
    from src.agent.analyzer import generate_discussion_with_agent, DiscussResult

    with spinner("Discussing requirements — clarifying ambiguities"):
        discuss_result = generate_discussion_with_agent(
            requirements, str(clone_path), llm_config=ai_cfg,
            verbose=ai_cfg.get("verbose", False),
            consciousness=consciousness,
            agent_config=agent_config, config=config,
            repo_url=repo_url, repo_knowledge=repo_knowledge,
            code_index=code_index,
        )

    if discuss_result.success and discuss_result.decisions:
        log_success(f"Discussion complete: {len(discuss_result.decisions)} decisions")
        # Format decisions as context for the main agent
        decision_lines = []
        for q, a in discuss_result.decisions.items():
            decision_lines.append(f"- **{q}**: {a}")
            print(f"  Decision: {q} → {a}")
        discuss_decisions = (
            "\n\n## Decisions from discussion phase\n"
            + "\n".join(decision_lines)
        )
        # Append to requirements
        requirements = requirements + discuss_decisions
    elif discuss_result.success:
        log_info("Requirements are clear — no discussion needed")
```

#### 3.4 Config key

**File:** `src/config_loader.py` — in `"agent"` dict:

```python
"discuss_max_turns": get_int("agent", "discuss_max_turns", 10),
```

**Acceptance criteria:**
- `--discuss` triggers a read-only phase that asks 3-7 clarifying questions
- Decisions are injected into requirements for the main agent
- Agent skips discussion if requirements are clear
- `--no-discuss` skips for CI/CD
- Off by default (explicit opt-in)

---

### Feature #2 — Goal-Backward Verification

**Source:** GSD (`gsd-verifier.md` — distrusts agent self-reports)
**Problem:** Agent reports `task_complete` but work is incomplete.
**Current state:** Post-edit verification checks syntax/imports/callers (`src/code_index/verifier.py`) but not requirement coverage.

#### 2.1 New function: `verify_requirements_met()`

**File:** `src/agent/verification.py` — **NEW FILE**

```python
"""
Goal-backward verification: check whether requirements were actually met.

Works backward from the stated requirements to verify that:
1. Each requirement bullet point has corresponding code changes
2. Each change has test coverage
3. Tests actually pass

This is distinct from the existing post-edit verification (syntax, imports,
callers) in src/code_index/verifier.py — that checks code correctness,
this checks requirement completeness.
"""

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RequirementVerification:
    """Verification result for a single requirement."""
    requirement: str
    implemented: bool = False
    evidence_file: str = ""
    tested: bool = False
    test_file: str = ""
    passing: bool = False
    notes: str = ""


@dataclass
class GoalVerificationResult:
    """Result from goal-backward verification."""
    requirements_checked: int = 0
    requirements_met: int = 0
    details: list[RequirementVerification] = field(default_factory=list)
    overall_pass: bool = False
    summary: str = ""

    def to_report(self) -> str:
        """Render as a markdown report."""
        lines = [f"## Goal Verification: {self.requirements_met}/{self.requirements_checked} requirements met\n"]
        for d in self.details:
            status = "PASS" if (d.implemented and d.tested and d.passing) else "FAIL"
            lines.append(f"- [{status}] {d.requirement}")
            if d.evidence_file:
                lines.append(f"  Implemented in: {d.evidence_file}")
            if d.test_file:
                lines.append(f"  Tested in: {d.test_file}")
            if d.notes:
                lines.append(f"  Notes: {d.notes}")
        return "\n".join(lines)


def extract_requirement_bullets(requirements: str) -> list[str]:
    """Extract individual requirement items from the requirements text."""
    bullets = []
    for line in requirements.splitlines():
        stripped = line.strip()
        # Match bullet points, numbered lists, or dashed items
        if re.match(r'^[-*+]\s+', stripped):
            bullets.append(re.sub(r'^[-*+]\s+', '', stripped).strip())
        elif re.match(r'^\d+[.)]\s+', stripped):
            bullets.append(re.sub(r'^\d+[.)]\s+', '', stripped).strip())
    # If no bullets found, treat the whole text as one requirement
    if not bullets:
        bullets = [requirements.strip()[:200]]
    return bullets


def verify_requirements_met(
    requirements: str,
    repo_path: str,
    files_changed: list[str],
    llm_config: dict,
    config: Optional[dict] = None,
    usage_stats: "Optional[LLMUsageStats]" = None,
) -> GoalVerificationResult:
    """Run goal-backward verification using a fast LLM call.

    Sends the requirements + list of changed files + summary of changes
    to a fast model and asks it to verify each requirement was met.
    """
    from src.llm_client import chat_completion
    from src.agent.context import _get_summary_model_config

    bullets = extract_requirement_bullets(requirements)
    if not bullets:
        return GoalVerificationResult(overall_pass=True, summary="No requirements to verify")

    # Read first 200 lines of each changed file for evidence
    file_summaries = []
    from pathlib import Path
    repo_root = Path(repo_path)
    for f in files_changed[:10]:
        fpath = repo_root / f
        if fpath.exists():
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
                # Just first 100 lines
                snippet = "\n".join(content.splitlines()[:100])
                file_summaries.append(f"### {f}\n```\n{snippet}\n```")
            except Exception:
                file_summaries.append(f"### {f}\n(could not read)")

    prompt = (
        "You are a verification agent. Check whether each requirement was implemented.\n\n"
        f"## Requirements\n"
        + "\n".join(f"- {b}" for b in bullets)
        + "\n\n## Files Changed\n"
        + "\n".join(f"- {f}" for f in files_changed)
        + "\n\n## File Contents (partial)\n"
        + "\n\n".join(file_summaries[:5])
        + "\n\n## Task\n"
        "For each requirement, respond with a JSON array:\n"
        '[{"requirement": "...", "implemented": true/false, "evidence_file": "...", '
        '"tested": true/false, "test_file": "...", "notes": "..."}]\n'
        "Be strict: mark as NOT implemented if you cannot find clear evidence."
    )

    summary_config = _get_summary_model_config(llm_config)
    try:
        response, _ = chat_completion(
            messages=[{"role": "user", "content": prompt}],
            config=summary_config,
            temperature=0.0,
            usage_stats=usage_stats,
            usage_category="verification",
        )

        # Parse JSON from response
        import json
        # Find JSON array in response
        start = response.find("[")
        end = response.rfind("]") + 1
        if start >= 0 and end > start:
            items = json.loads(response[start:end])
            details = []
            for item in items:
                details.append(RequirementVerification(
                    requirement=item.get("requirement", ""),
                    implemented=item.get("implemented", False),
                    evidence_file=item.get("evidence_file", ""),
                    tested=item.get("tested", False),
                    test_file=item.get("test_file", ""),
                    notes=item.get("notes", ""),
                ))
            met = sum(1 for d in details if d.implemented)
            return GoalVerificationResult(
                requirements_checked=len(details),
                requirements_met=met,
                details=details,
                overall_pass=(met == len(details)),
                summary=f"{met}/{len(details)} requirements verified as implemented",
            )
    except Exception:
        pass

    return GoalVerificationResult(
        requirements_checked=len(bullets),
        summary="Verification could not be completed",
    )
```

#### 2.2 Wire into agent success path

**File:** `src/agent/analyzer.py` — in the success branch (after `task_complete`, ~line 769)

```python
if task_complete_data:
    # Clear checkpoint on successful completion
    try:
        clear_checkpoint(config, repo_path, repo_url)
    except Exception:
        pass

    # Goal-backward verification (non-fatal)
    goal_verification = None
    try:
        from src.agent.verification import verify_requirements_met
        goal_verification = verify_requirements_met(
            requirements, repo_path, sorted(changes_tracker),
            llm_config, config=config, usage_stats=usage_stats,
        )
    except Exception:
        pass

    result_obj = AgentResult(
        success=True,
        files_changed=sorted(changes_tracker),
        summary=task_complete_data.get("summary", ""),
        turns_used=turn + 1,
        tests_passed=True,
        usage_stats=usage_stats,
        goal_verification=goal_verification,  # new field
    )
```

#### 2.3 Add field to AgentResult

**File:** `src/agent/analyzer.py` — in `AgentResult` dataclass:

```python
goal_verification: "GoalVerificationResult | None" = None
```

#### 2.4 Display verification in main.py

**File:** `main.py` — after agent success logging:

```python
if result.goal_verification:
    gv = result.goal_verification
    if gv.overall_pass:
        log_success(f"Goal verification: {gv.summary}")
    else:
        log_warning(f"Goal verification: {gv.summary}")
        print(gv.to_report())
```

**Acceptance criteria:**
- After `task_complete`, a fast LLM checks each requirement bullet against files changed
- User sees `Goal verification: 4/5 requirements verified` in output
- Non-fatal — agent result still returned even if verification fails
- Uses `usage_category="verification"` for budget tracking

---

### Feature #8 — Rich Session State for Resume

**Source:** GSD (`STATE.md` with position, decisions, blockers, next steps)
**Problem:** Our checkpoint saves `files_changed` + `working_memory` but loses reasoning context.
**Current state:** `Checkpoint` dataclass in `knowledge.py` (lines 455-471).

#### 8.1 Extend Checkpoint dataclass

**File:** `src/agent/knowledge.py` — add fields to `Checkpoint`:

```python
@dataclass
class Checkpoint:
    # ... existing fields ...
    decisions_made: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    tools_used_summary: dict[str, int] = field(default_factory=dict)  # tool_name → count
    last_tool_name: str = ""
    last_tool_result_summary: str = ""
```

#### 8.2 Populate new fields on checkpoint save

**File:** `src/agent/analyzer.py` — in the failure branch where `save_checkpoint` is called:

```python
# Build tools_used_summary from the messages history
tools_used_summary: dict[str, int] = {}
for m in messages:
    for tc in m.get("tool_calls", []):
        tn = tc.get("function", {}).get("name", "")
        if tn:
            tools_used_summary[tn] = tools_used_summary.get(tn, 0) + 1

checkpoint = save_checkpoint(
    config, repo_path, repo_url, requirements,
    sorted(changes_tracker), working_memory,
    turns_used=max_turns, max_turns=max_turns,
    summary=f"Agent used {max_turns} turns, changed {len(changes_tracker)} file(s).",
    pending_work="Agent ran out of turns before calling task_complete.",
    summarization_calls_used=usage_stats.calls_by_category("summarization") if usage_stats else 0,
    testing_turns_used=testing_turns_used,
    tools_used_summary=tools_used_summary,
)
```

#### 8.3 Richer `to_context_string()` on resume

**File:** `src/agent/knowledge.py` — update `Checkpoint.to_context_string()`:

Add sections for decisions, blockers, next steps, and tool usage:

```python
if self.blockers:
    lines.append("\n### Blockers encountered")
    for b in self.blockers:
        lines.append(f"  - {b}")

if self.next_steps:
    lines.append("\n### Suggested next steps")
    for s in self.next_steps:
        lines.append(f"  - {s}")

if self.tools_used_summary:
    lines.append("\n### Tool usage from previous run")
    for tool, count in sorted(self.tools_used_summary.items(), key=lambda x: -x[1]):
        lines.append(f"  - {tool}: {count} calls")
```

**Acceptance criteria:**
- Checkpoint includes tool usage counts, last tool, blockers
- Resume injects richer context about what was tried
- Backward compatible — old checkpoints without new fields still load

---

## Sprint 3: Multi-Agent Orchestration (Weeks 3-4)

### Feature #6 — Multi-Agent Orchestration with Handoffs

**Source:** everything-claude-code (`/orchestrate` command, structured handoff documents)
**Problem:** Single agent with one system prompt can't specialize.
**Current state:** One `generate_changes_with_agent()` function, one `_SYSTEM_PROMPT`.

#### 6.1 Agent definition format

**New directory:** `.code-autonomy/agents/`

Each agent is a Markdown file with YAML frontmatter:

```markdown
# .code-autonomy/agents/implementer.md
---
name: implementer
description: Implements code changes based on a plan
model_preference: balanced
tools:
  - read_file
  - write_file
  - edit_file
  - delete_file
  - run_command
  - grep
  - list_dir
  - find_files
  - update_memory
  - read_memory
  - task_complete
  - find_callers
  - impact_analysis
  - context_for_edit
  - checkpoint_commit
max_turns: 30
---
You are an expert software engineer. Implement the changes described
in the handoff document below. Follow existing code conventions.

After each file change, run relevant tests. If tests fail, fix the issue
(max 3 attempts per failure). If you cannot fix it, call task_complete
with the failure noted in pending_work.
```

**Default agents to ship:**
- `implementer.md` — writes code, runs tests
- `verifier.md` — goal-backward verification (read-only)
- `reviewer.md` — code quality review (read-only)
- `security-reviewer.md` — security review (read-only)
- `planner.md` — breaks requirement into sub-tasks (read-only)
- `researcher.md` — explores codebase for relevant patterns (read-only)

#### 6.2 Agent definition loader

**New file:** `src/agent/agent_defs.py`

```python
"""Load and parse agent definitions from Markdown files."""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class AgentDefinition:
    name: str = ""
    description: str = ""
    model_preference: str = "balanced"  # quality | balanced | budget
    tools: list[str] = field(default_factory=list)
    max_turns: int = 30
    system_prompt: str = ""
    receives_from: list[str] = field(default_factory=list)
    sends_to: list[str] = field(default_factory=list)


def load_agent_definition(path: Path) -> AgentDefinition:
    """Parse a Markdown agent definition file."""
    content = path.read_text(encoding="utf-8")

    # Extract YAML frontmatter
    fm_match = re.match(r'^---\s*\n(.*?)\n---\s*\n', content, re.DOTALL)
    if not fm_match:
        return AgentDefinition(name=path.stem, system_prompt=content)

    fm = yaml.safe_load(fm_match.group(1)) or {}
    body = content[fm_match.end():].strip()

    return AgentDefinition(
        name=fm.get("name", path.stem),
        description=fm.get("description", ""),
        model_preference=fm.get("model_preference", "balanced"),
        tools=fm.get("tools", []),
        max_turns=fm.get("max_turns", 30),
        system_prompt=body,
        receives_from=fm.get("receives_from", []),
        sends_to=fm.get("sends_to", []),
    )


def load_all_agent_definitions(
    repo_path: str = "",
    builtin_dir: str = "",
) -> dict[str, AgentDefinition]:
    """Load agent definitions from repo and built-in directories."""
    agents: dict[str, AgentDefinition] = {}

    # Built-in agents (shipped with code-autonomy)
    builtin = Path(builtin_dir) if builtin_dir else Path(__file__).parent.parent.parent / ".code-autonomy" / "agents"
    if builtin.is_dir():
        for md in sorted(builtin.glob("*.md")):
            agent = load_agent_definition(md)
            agents[agent.name] = agent

    # Repo-local agents (override built-in)
    if repo_path:
        repo_agents = Path(repo_path) / ".code-autonomy" / "agents"
        if repo_agents.is_dir():
            for md in sorted(repo_agents.glob("*.md")):
                agent = load_agent_definition(md)
                agents[agent.name] = agent

    return agents
```

#### 6.3 Orchestrator engine

**New file:** `src/agent/orchestrator.py`

```python
"""
Multi-agent orchestration engine.

Workflows:
  feature:  [researcher] → planner → [implementer] → verifier → reviewer
  bugfix:   [researcher] → implementer → verifier
  refactor: [researcher] → planner → [implementer] → reviewer
  security: [researcher] → implementer → verifier → security-reviewer

Agents in [] run in parallel. Others run sequentially.
Each agent gets a fresh context window + handoff document from predecessor.
"""

from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path


@dataclass
class HandoffDocument:
    """Structured document passed between agents."""
    from_agent: str
    to_agent: str
    requirement: str
    decisions: dict[str, str] = field(default_factory=dict)
    plan: str = ""
    files_changed: list[str] = field(default_factory=list)
    findings: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_string(self) -> str:
        lines = [f"## Handoff: {self.from_agent} → {self.to_agent}"]
        lines.append(f"\n### Requirement\n{self.requirement}")
        if self.decisions:
            lines.append("\n### Decisions")
            for k, v in self.decisions.items():
                lines.append(f"- **{k}**: {v}")
        if self.plan:
            lines.append(f"\n### Plan\n{self.plan}")
        if self.files_changed:
            lines.append(f"\n### Files Changed ({len(self.files_changed)})")
            for f in self.files_changed:
                lines.append(f"  - {f}")
        if self.findings:
            lines.append(f"\n### Findings\n{self.findings}")
        if self.warnings:
            lines.append("\n### Warnings")
            for w in self.warnings:
                lines.append(f"  - {w}")
        return "\n".join(lines)


WORKFLOW_PIPELINES = {
    "feature":  ["researcher", "planner", "implementer", "verifier", "reviewer"],
    "bugfix":   ["researcher", "implementer", "verifier"],
    "refactor": ["researcher", "planner", "implementer", "reviewer"],
    "security": ["researcher", "implementer", "verifier", "security-reviewer"],
}


@dataclass
class OrchestratorResult:
    """Result from multi-agent orchestration."""
    success: bool = False
    workflow: str = ""
    agents_run: list[str] = field(default_factory=list)
    files_changed: list[str] = field(default_factory=list)
    summary: str = ""
    verification_report: str = ""
    review_report: str = ""
    handoffs: list[HandoffDocument] = field(default_factory=list)


def run_orchestrated_workflow(
    workflow: str,
    requirements: str,
    repo_path: str,
    llm_config: dict,
    config: Optional[dict] = None,
    repo_url: str = "",
    **kwargs,
) -> OrchestratorResult:
    """Execute a multi-agent workflow pipeline.

    Each agent runs as a separate invocation of the agent loop
    with a fresh context window and its own system prompt + handoff.
    """
    from src.agent.agent_defs import load_all_agent_definitions
    from src.agent.analyzer import generate_changes_with_agent, generate_answer_with_agent

    pipeline = WORKFLOW_PIPELINES.get(workflow, WORKFLOW_PIPELINES["feature"])
    agents = load_all_agent_definitions(repo_path)

    result = OrchestratorResult(workflow=workflow)
    handoff = HandoffDocument(from_agent="user", to_agent=pipeline[0], requirement=requirements)

    for agent_name in pipeline:
        agent_def = agents.get(agent_name)
        if not agent_def:
            result.summary += f"\nSkipped {agent_name}: no definition found"
            continue

        result.agents_run.append(agent_name)

        # Build agent-specific config
        agent_cfg = dict((config or {}).get("agent", {}))
        agent_cfg["max_turns"] = agent_def.max_turns

        # Inject handoff into requirements
        agent_requirements = handoff.to_string() + "\n\n" + requirements

        # Route to appropriate function based on agent tools
        is_read_only = not any(t in agent_def.tools for t in ["write_file", "edit_file", "delete_file", "run_command"])

        if is_read_only:
            # Use ask mode (read-only)
            ask_result = generate_answer_with_agent(
                agent_requirements, repo_path, llm_config=llm_config,
                max_turns=agent_def.max_turns,
                agent_config=agent_cfg, config=config, repo_url=repo_url,
                **{k: v for k, v in kwargs.items() if k in ("consciousness", "repo_knowledge", "code_index")},
            )
            # Build handoff for next agent
            handoff = HandoffDocument(
                from_agent=agent_name,
                to_agent=pipeline[pipeline.index(agent_name) + 1] if pipeline.index(agent_name) + 1 < len(pipeline) else "done",
                requirement=requirements,
                findings=ask_result.answer if ask_result.success else "",
                warnings=[ask_result.summary] if not ask_result.success else [],
            )
            if agent_name == "verifier":
                result.verification_report = ask_result.answer
            elif agent_name in ("reviewer", "security-reviewer"):
                result.review_report += f"\n## {agent_name}\n{ask_result.answer}"
        else:
            # Use agent mode (read-write)
            agent_result = generate_changes_with_agent(
                agent_requirements, repo_path, llm_config=llm_config,
                max_turns=agent_def.max_turns,
                agent_config=agent_cfg, config=config, repo_url=repo_url,
                **{k: v for k, v in kwargs.items()
                   if k in ("reference_pr_content", "testing_strategy", "build_tool",
                            "consciousness", "framework_context", "repo_knowledge", "code_index")},
            )
            result.files_changed = agent_result.files_changed
            handoff = HandoffDocument(
                from_agent=agent_name,
                to_agent=pipeline[pipeline.index(agent_name) + 1] if pipeline.index(agent_name) + 1 < len(pipeline) else "done",
                requirement=requirements,
                files_changed=agent_result.files_changed,
                findings=agent_result.summary,
            )
            if not agent_result.success:
                result.summary = f"Pipeline stopped at {agent_name}: {agent_result.summary}"
                return result

        result.handoffs.append(handoff)

    result.success = True
    result.summary = f"Completed {workflow} workflow: {len(result.agents_run)} agents, {len(result.files_changed)} files changed"
    return result
```

#### 6.4 CLI flag

**File:** `main.py`:

```python
parser.add_argument("--orchestrate", "-o",
                    choices=["feature", "bugfix", "refactor", "security"],
                    help="Run multi-agent orchestrated workflow")
```

Wire into main flow as a new mode alongside `--agent` and `--plan`.

**Acceptance criteria:**
- `--orchestrate feature` runs researcher → planner → implementer → verifier → reviewer
- Each agent gets fresh context window with handoff document
- Agent definitions loaded from `.code-autonomy/agents/` (repo-local overrides built-in)
- User sees which agent is running and what it produced
- Falls back to single agent if agent definitions not found

---

### Feature #1 — Wave-Based Parallel Sub-Agent Execution

**Source:** GSD (dependency-based waves, parallel execution within waves)
**Problem:** Large requirements overwhelm single context window.
**Depends on:** Feature #6 (orchestration engine)

#### 1.1 Plan decomposition

**File:** `src/agent/orchestrator.py` — add plan decomposition

After the `planner` agent runs, parse its output into sub-plans with dependencies:

```python
@dataclass
class SubPlan:
    id: str
    description: str
    files: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)


def decompose_into_waves(sub_plans: list[SubPlan]) -> list[list[SubPlan]]:
    """Group sub-plans into dependency-ordered waves."""
    completed: set[str] = set()
    remaining = list(sub_plans)
    waves: list[list[SubPlan]] = []

    while remaining:
        # Find plans whose dependencies are all completed
        wave = [p for p in remaining if all(d in completed for d in p.depends_on)]
        if not wave:
            # Break circular dependencies — force remaining into one wave
            wave = remaining[:]
        waves.append(wave)
        for p in wave:
            completed.add(p.id)
            remaining.remove(p)

    return waves
```

#### 1.2 Parallel wave execution

**File:** `src/agent/orchestrator.py` — add parallel runner

```python
import concurrent.futures

def execute_waves(
    waves: list[list[SubPlan]],
    repo_path: str,
    llm_config: dict,
    config: Optional[dict] = None,
    max_parallel: int = 3,
    **kwargs,
) -> list[AgentResult]:
    """Execute waves sequentially; plans within a wave in parallel."""
    all_results = []

    for wave_idx, wave in enumerate(waves):
        if len(wave) == 1:
            # Single plan — run directly
            r = _run_sub_plan(wave[0], repo_path, llm_config, config, **kwargs)
            all_results.append(r)
        else:
            # Multiple plans — run in parallel
            with concurrent.futures.ProcessPoolExecutor(max_workers=max_parallel) as pool:
                futures = {
                    pool.submit(_run_sub_plan, plan, repo_path, llm_config, config, **kwargs): plan
                    for plan in wave
                }
                for future in concurrent.futures.as_completed(futures):
                    all_results.append(future.result())

    return all_results
```

**Note:** Parallel execution of agents writing to the same repo requires file-level
locking or ensuring plans touch different files. The planner must ensure non-overlapping
file assignments within a wave.

#### 1.3 Config

**File:** `src/config_loader.py`:

```python
"max_parallel_agents": get_int("agent", "max_parallel_agents", 3),
```

**Acceptance criteria:**
- Planner output is decomposed into sub-plans with dependency edges
- Independent sub-plans execute in parallel (separate processes)
- Dependent sub-plans wait for predecessors
- `max_parallel_agents` controls concurrency
- File conflicts detected before parallel execution

---

### Feature #13 — Specialized Reviewer Agents

**Source:** everything-claude-code (13 specialized agents)
**Depends on:** Feature #6 (orchestration engine — agents loaded from Markdown)

#### 13.1 Ship built-in agent definitions

**New files:**

`.code-autonomy/agents/reviewer.md`:
```markdown
---
name: reviewer
description: Reviews code changes for quality, style, and correctness
model_preference: balanced
tools: [read_file, grep, list_dir, find_files, find_callers, impact_analysis, describe_entity, update_memory, task_complete]
max_turns: 15
receives_from: [implementer, verifier]
---
You are an expert code reviewer. Review the changes listed in the handoff
document for: naming consistency, error handling, edge cases, code
duplication, and adherence to project conventions.

Report issues as: [CRITICAL], [WARNING], or [SUGGESTION].
Call task_complete with your review as the answer.
```

`.code-autonomy/agents/security-reviewer.md`:
```markdown
---
name: security-reviewer
description: Reviews code for security vulnerabilities
model_preference: quality
tools: [read_file, grep, list_dir, find_files, find_callers, find_dependents, update_memory, task_complete]
max_turns: 15
receives_from: [implementer]
---
You are a security specialist. Review the changes for:
- SQL injection, XSS, command injection
- Authentication/authorization bypasses
- Secrets or credentials in code
- Insecure deserialization
- Path traversal
- OWASP Top 10 vulnerabilities

Report findings as: [CRITICAL], [HIGH], [MEDIUM], [LOW].
Call task_complete with your security review as the answer.
```

`.code-autonomy/agents/researcher.md`:
```markdown
---
name: researcher
description: Explores codebase to understand patterns and conventions
model_preference: budget
tools: [read_file, grep, list_dir, find_files, find_callers, find_dependents, describe_entity, find_similar, update_memory, task_complete]
max_turns: 15
---
You are a codebase researcher. Explore the repository to understand:
- Project structure and conventions
- Existing patterns relevant to the requirements
- Test patterns and frameworks in use
- Potential files that will need changes

Call task_complete with a structured research summary.
```

`.code-autonomy/agents/planner.md`:
```markdown
---
name: planner
description: Decomposes requirements into executable sub-plans
model_preference: quality
tools: [read_file, grep, list_dir, find_files, find_callers, impact_analysis, context_for_edit, predict_breakage, update_memory, task_complete]
max_turns: 20
receives_from: [researcher]
---
You are a technical planner. Break the requirement into atomic sub-plans.

For each sub-plan, specify:
- ID (e.g., "plan-1")
- Description (one sentence)
- Files to create or modify
- Dependencies (which other plan IDs must complete first)

Output as a structured list. Call task_complete with the plan.
```

**Acceptance criteria:**
- 6 agent definitions ship as built-in
- Users can override by placing `.code-autonomy/agents/<name>.md` in their repo
- Agents used by orchestrator workflows

---

## Sprint 4: Hooks & Formatting (Week 5)

### Feature #7 — Pre/Post Tool Hooks

**Source:** everything-claude-code (`hooks.json` with PreToolUse, PostToolUse events)
**Problem:** Static allowlist/blocklist; no dynamic user-defined guardrails.
**Current state:** `command_allowlist_only` and `blocked_commands` in config.

#### 7.1 Hook execution engine

**New file:** `src/agent/hooks.py`

```python
"""
Pre/post tool hook system.

Hooks are shell commands or Python scripts that run before/after tool calls.
They receive JSON on stdin and return JSON on stdout.

Hook types:
  pre_tool_use:  Runs before tool execution. Can block (exit 2) or modify args.
  post_tool_use: Runs after tool execution. Can transform the result.

Config:
  [hooks]
  pre_tool_use = python hooks/pre_tool.py
  post_tool_use = python hooks/post_tool.py
"""

import json
import subprocess
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class HookResult:
    decision: str = "allow"   # "allow" | "block" | "modify"
    modified_args: Optional[dict] = None
    modified_result: Optional[str] = None
    message: str = ""


def run_hook(
    hook_command: str,
    hook_input: dict,
    timeout: int = 10,
) -> HookResult:
    """Execute a hook command, passing JSON on stdin, reading JSON from stdout."""
    if not hook_command:
        return HookResult(decision="allow")

    try:
        proc = subprocess.run(
            hook_command,
            shell=True,
            input=json.dumps(hook_input),
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        if proc.returncode == 2:
            # Exit code 2 = block
            message = proc.stdout.strip() or "Blocked by hook"
            return HookResult(decision="block", message=message)

        if proc.returncode != 0:
            logger.warning("Hook exited with code %d: %s", proc.returncode, proc.stderr[:200])
            return HookResult(decision="allow")

        # Parse JSON output
        if proc.stdout.strip():
            try:
                output = json.loads(proc.stdout)
                return HookResult(
                    decision=output.get("decision", "allow"),
                    modified_args=output.get("modified_args"),
                    modified_result=output.get("modified_result"),
                    message=output.get("message", ""),
                )
            except json.JSONDecodeError:
                pass

        return HookResult(decision="allow")

    except subprocess.TimeoutExpired:
        logger.warning("Hook timed out after %ds", timeout)
        return HookResult(decision="allow")
    except Exception as exc:
        logger.warning("Hook error: %s", exc)
        return HookResult(decision="allow")
```

#### 7.2 Wire hooks into tool execution

**File:** `src/agent/analyzer.py` — in the tool call processing loop

Before `execute_tool()` call:

```python
# Pre-tool hook
pre_hook_cmd = agent_cfg.get("pre_tool_use_hook", "")
if pre_hook_cmd:
    from src.agent.hooks import run_hook
    hook_result = run_hook(pre_hook_cmd, {
        "tool_name": name, "args": args, "turn": turn,
    })
    if hook_result.decision == "block":
        result = f"Blocked by hook: {hook_result.message}"
        # Skip tool execution, append result
        messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
        continue
    if hook_result.modified_args:
        args = hook_result.modified_args
```

After `execute_tool()` call:

```python
# Post-tool hook
post_hook_cmd = agent_cfg.get("post_tool_use_hook", "")
if post_hook_cmd:
    from src.agent.hooks import run_hook
    hook_result = run_hook(post_hook_cmd, {
        "tool_name": name, "args": args, "result": result[:5000], "turn": turn,
    })
    if hook_result.modified_result:
        result = hook_result.modified_result
```

#### 7.3 Config keys

**File:** `src/config_loader.py` — add `[hooks]` section:

```python
"hooks": {
    "pre_tool_use": get("hooks", "pre_tool_use", ""),
    "post_tool_use": get("hooks", "post_tool_use", ""),
    "pre_agent": get("hooks", "pre_agent", ""),
    "post_agent": get("hooks", "post_agent", ""),
},
```

Pass hook commands through `agent_config` dict in main.py.

**Acceptance criteria:**
- Users can define `pre_tool_use` / `post_tool_use` hooks in config.ini
- Hooks receive JSON on stdin, return JSON on stdout
- Exit code 2 blocks tool execution
- Hooks can modify args (pre) or result (post)
- Default: no hooks (backward compatible)

---

### Feature #15 — Auto-Format After Edit

**Source:** everything-claude-code (PostToolUse hook for prettier/black)
**Problem:** Agent-written code isn't auto-formatted.

#### 15.1 Built-in post-edit formatter

**File:** `src/agent/tools.py` — in `execute_tool()`, after write_file/edit_file

```python
if tool_name in ("write_file", "edit_file") and not result.startswith("Error:"):
    # Auto-format if formatter detected
    _auto_format(repo_root, args.get("path", ""))


def _auto_format(repo_root: Path, file_path: str) -> None:
    """Run auto-formatter if one is detected for the file type."""
    import subprocess
    full_path = repo_root / file_path

    if file_path.endswith(".py"):
        # Try black, then autopep8
        for fmt in ["black", "autopep8"]:
            try:
                subprocess.run([fmt, str(full_path)], capture_output=True, timeout=10)
                return
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue

    elif file_path.endswith((".js", ".ts", ".jsx", ".tsx", ".json", ".css")):
        # Try prettier
        try:
            subprocess.run(["npx", "prettier", "--write", str(full_path)],
                          capture_output=True, timeout=15, cwd=str(repo_root))
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    elif file_path.endswith(".go"):
        try:
            subprocess.run(["gofmt", "-w", str(full_path)], capture_output=True, timeout=10)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
```

#### 15.2 Config key

**File:** `src/config_loader.py`:

```python
"auto_format": get_bool("agent", "auto_format", False),  # opt-in
```

**Acceptance criteria:**
- When `auto_format = true`, agent-written Python/JS/Go files are auto-formatted
- Silently skipped if formatter not installed
- Off by default

---

### Feature #12 — TDD Workflow Mode

**Source:** Both repos (GSD `tdd="true"`, everything-claude-code TDD guide agent)
**Problem:** Agent writes code first, then tests. TDD would improve test quality.

#### 12.1 TDD system prompt variant

**File:** `src/agent/analyzer.py` — new prompt constant:

```python
_TDD_PROMPT_SECTION = """

## TDD Workflow (MUST follow this order)
You are working in TDD mode. For each piece of functionality:
1. **RED**: Write a failing test FIRST. Run it to confirm it fails.
2. **GREEN**: Write the minimum code to make the test pass. Run the test.
3. **REFACTOR**: Clean up the code while keeping tests green.
4. Repeat for each requirement.

Do NOT write implementation code before writing a test for it."""
```

#### 12.2 CLI flag and wiring

**File:** `main.py`:

```python
parser.add_argument("--tdd", action="store_true",
                    help="Use TDD workflow: write tests first, then implement")
```

**File:** `src/agent/analyzer.py` — add `tdd: bool = False` to `generate_changes_with_agent()`:

```python
if tdd:
    system_prompt += _TDD_PROMPT_SECTION
```

**Acceptance criteria:**
- `--tdd` forces test-first workflow via system prompt
- Agent writes test → runs (red) → implements → runs (green) → refactors
- Works with all testing strategies (pytest, JUnit, etc.)

---

## Sprint 5: Learning System (Week 6)

### Feature #5 — Continuous Learning / Instinct System

**Source:** everything-claude-code (instinct-based v2 with confidence scores)
**Problem:** Knowledge system records discoveries but not user corrections.

#### 5.1 Pattern dataclass

**File:** `src/agent/knowledge.py` — add after `Checkpoint` section:

```python
@dataclass
class LearnedPattern:
    """A behavioral pattern learned from agent runs and user corrections."""
    pattern_id: str = ""
    pattern_type: str = ""  # correction | preference | anti_pattern | workflow
    content: str = ""
    confidence: float = 0.3  # 0.0 to 1.0
    evidence_count: int = 0
    domain: str = ""  # python | java | testing | git | general
    created_at: str = ""
    last_reinforced: str = ""
    decay_rate: float = 0.05  # confidence drops per week without reinforcement

    def to_dict(self) -> dict:
        return { ... }

    @classmethod
    def from_dict(cls, data: dict) -> "LearnedPattern":
        return cls( ... )
```

#### 5.2 Pattern store

**File:** `src/agent/knowledge.py` — extend `KnowledgeEntry`:

```python
@dataclass
class KnowledgeEntry:
    # ... existing fields ...
    patterns: list[dict] = field(default_factory=list)  # list of LearnedPattern dicts
```

#### 5.3 Learning engine

**New file:** `src/agent/learning.py`

```python
"""
Continuous learning engine.

After each agent run:
1. Compare agent output vs final committed code (if available)
2. Detect corrections and preferences
3. Update pattern confidence scores
4. Inject high-confidence patterns into future runs
"""

def capture_corrections(
    repo_path: str,
    agent_files_changed: list[str],
) -> list[LearnedPattern]:
    """Compare agent's changes vs current git state to detect user corrections."""
    # git diff HEAD~1 for each file the agent changed
    # If user modified agent's output → that's a correction
    ...

def apply_confidence_decay(patterns: list[LearnedPattern]) -> list[LearnedPattern]:
    """Reduce confidence for patterns not recently reinforced."""
    ...

def get_active_patterns(
    config: dict,
    repo_path: str,
    repo_url: str,
    min_confidence: float = 0.5,
) -> list[LearnedPattern]:
    """Load patterns above confidence threshold for injection into agent prompt."""
    ...

def patterns_to_prompt_section(patterns: list[LearnedPattern]) -> str:
    """Format active patterns as a system prompt section."""
    if not patterns:
        return ""
    lines = ["\n## Learned patterns from previous runs"]
    for p in patterns:
        lines.append(f"- [{p.domain}] (confidence: {p.confidence:.1f}) {p.content}")
    return "\n".join(lines)
```

#### 5.4 Inject patterns into agent prompt

**File:** `src/agent/analyzer.py` — before agent loop starts:

```python
# Load learned patterns
try:
    from src.agent.learning import get_active_patterns, patterns_to_prompt_section
    active_patterns = get_active_patterns(config, repo_path, repo_url)
    patterns_section = patterns_to_prompt_section(active_patterns)
    if patterns_section:
        system_prompt += patterns_section
except Exception:
    pass
```

**Acceptance criteria:**
- Patterns stored in KnowledgeEntry (persisted per-repo)
- Confidence 0.0-1.0, decays weekly, increases with evidence
- Only patterns above 0.5 confidence injected into prompts
- User corrections captured by diffing agent output vs committed code

---

### Feature #18 — Pattern Export/Import Between Users

**Source:** everything-claude-code (instinct export/import)
**Depends on:** Feature #5

#### 18.1 CLI commands

**File:** `main.py`:

```python
parser.add_argument("--export-patterns", metavar="FILE",
                    help="Export learned patterns to a JSON file")
parser.add_argument("--import-patterns", metavar="FILE",
                    help="Import learned patterns from a JSON file")
```

#### 18.2 Export/import functions

**File:** `src/agent/learning.py`:

```python
def export_patterns(config, repo_path, repo_url, output_path):
    """Export patterns (content + confidence only, no code or conversations)."""
    ...

def import_patterns(config, repo_path, repo_url, input_path):
    """Import patterns, merging with existing (lower confidence for imported)."""
    ...
```

**Acceptance criteria:**
- `--export-patterns patterns.json` writes patterns (no code, no conversations)
- `--import-patterns patterns.json` merges into local knowledge (imported at 0.5x confidence)
- Patterns include domain tags for filtering

---

### Feature #11 — Model Profiles

**Source:** GSD (quality/balanced/budget per-agent model selection)
**Problem:** Exploration turns use same expensive model as implementation.

#### 11.1 Profile definitions

**File:** `src/config_loader.py` — add `[model_profiles]` section:

```python
"model_profiles": {
    "quality": get("model_profiles", "quality", ""),      # e.g., claude-3-opus
    "balanced": get("model_profiles", "balanced", ""),     # e.g., claude-sonnet-4-5
    "budget": get("model_profiles", "budget", ""),         # e.g., claude-3-5-haiku
},
```

#### 11.2 Model resolution for agents

**File:** `src/agent/orchestrator.py` — in agent execution:

```python
def resolve_model_config(llm_config: dict, model_preference: str, config: dict) -> dict:
    """Return llm_config with model overridden by profile preference."""
    profiles = config.get("model_profiles", {})
    model = profiles.get(model_preference, "")
    if model:
        cfg = dict(llm_config)
        cfg["model"] = model
        return cfg
    return llm_config
```

**Acceptance criteria:**
- Agent definitions specify `model_preference: quality|balanced|budget`
- Config maps profiles to actual model names
- Default: all agents use the main model (backward compatible)
- Researcher/reviewer agents can use cheaper models to reduce cost

---

## Sprint 6: UX & Distribution (Week 7)

### Feature #10 — Brownfield Codebase Mapping

**Source:** GSD (4 parallel agents produce ARCHITECTURE.md, CONVENTIONS.md, etc.)
**Problem:** `--init-knowledge` is shallow compared to multi-agent analysis.

#### 10.1 Enhanced knowledge generator

**File:** `src/agent/knowledge_generator.py` — extend `generate_knowledge_markdown()`

Use the orchestration engine (Feature #6) to run 4 research agents in parallel:
- Tech researcher: stack, frameworks, dependencies
- Architecture researcher: structure, patterns, entry points
- Quality researcher: conventions, testing, CI/CD
- Concerns researcher: tech debt, TODOs, known issues

Merge results into a comprehensive `.code-autonomy.md`.

**Acceptance criteria:**
- `--init-knowledge --deep` runs 4 parallel researchers
- Output is richer than current single-pass analysis
- Falls back to current behavior without `--deep`

---

### Feature #16 — Quick Mode for Ad-Hoc Tasks

**Source:** GSD (`/gsd:quick` — atomic commits, state tracking, no full research cycle)
**Problem:** Same overhead for small and large tasks.

#### 16.1 Quick mode flag

**File:** `main.py`:

```python
parser.add_argument("--quick", action="store_true",
                    help="Quick mode: skip research/planning, lower turn limit for small tasks")
```

#### 16.2 Implementation

When `--quick` is set:
- Set `max_turns = 15` (instead of 50)
- Skip consciousness building
- Skip code index building
- Skip knowledge loading
- Use a shorter system prompt focused on direct implementation

**File:** `src/agent/analyzer.py` — add quick mode prompt variant:

```python
_QUICK_SYSTEM_PROMPT = """\
You are an expert software engineer. Make the requested change directly.
Skip extensive exploration — focus on the specific change needed.
Tools: read_file, write_file, edit_file, run_command, task_complete.
Read the relevant file, make the change, run tests, call task_complete."""
```

**Acceptance criteria:**
- `--quick` reduces overhead for small changes
- Lower turn limit (15), no consciousness/index
- Fast feedback loop for typo fixes, small edits, etc.

---

### Feature #17 — Multi-Editor Support (VS Code)

**Source:** everything-claude-code (cross-editor configs)
**Problem:** CLI-only, invisible to IDE users.

This is a larger effort. Minimal viable approach:

#### 17.1 MCP Server (prerequisite for IDE integration)

**New file:** `src/mcp_server.py`

Expose code intelligence tools via MCP protocol. Any MCP-compatible editor
(Claude Code, VS Code, Cursor) can then use our tools.

See `ROADMAP.md` Phase 1 for full MCP server specification.

#### 17.2 VS Code extension (thin shell)

**New directory:** `vscode-extension/`

Minimal TypeScript extension that connects to our MCP server and:
- Registers a `@code-autonomy` chat participant
- Shows code intelligence results in VS Code panels
- Displays agent activity in a sidebar

**Acceptance criteria:**
- `python -m code_autonomy.mcp serve` exposes tools via stdio
- VS Code users can configure it as an MCP server
- Code intelligence available in any MCP-compatible editor

---

## Dependency Graph

```
Sprint 1 (standalone - no dependencies)
  #4  Deviation rules
  #14 Context utilization tracking
  #9  Atomic git commits

Sprint 2 (standalone - no dependencies)
  #3  Discuss phase
  #2  Goal-backward verification
  #8  Rich session state

Sprint 3 (depends on Sprint 1-2 for quality, but not hard dependency)
  #6  Multi-agent orchestration ←── foundation for #1, #13
  #1  Wave-based parallel execution ←── depends on #6
  #13 Specialized reviewer agents ←── depends on #6

Sprint 4 (standalone)
  #7  Pre/post tool hooks
  #15 Auto-format after edit
  #12 TDD workflow mode

Sprint 5 (standalone, benefits from multiple runs)
  #5  Continuous learning ←── foundation for #18
  #18 Pattern export/import ←── depends on #5
  #11 Model profiles ←── benefits from #6

Sprint 6 (depends on Sprint 3 for #10, standalone otherwise)
  #10 Brownfield codebase mapping ←── benefits from #6
  #16 Quick mode
  #17 Multi-editor support (MCP server)
```

---

## Test Plan

### Per-Feature Acceptance Tests

| # | Feature | Test |
|---|---------|------|
| 1 | Wave parallel | Run with 2 independent sub-plans → verify both execute, results merged |
| 2 | Goal verification | Agent completes → verification reports X/Y requirements met |
| 3 | Discuss phase | `--discuss` → agent asks questions → decisions injected into requirements |
| 4 | Deviation rules | Agent hits same error 3x → stops and reports instead of spiraling |
| 5 | Continuous learning | Run twice → second run has patterns from first in prompt |
| 6 | Orchestration | `--orchestrate feature` → runs 5 agents in sequence with handoffs |
| 7 | Hooks | Configure `pre_tool_use` hook that blocks `rm` → verify blocked |
| 8 | Rich state | Agent exhausts turns → checkpoint has tool counts, blockers |
| 9 | Atomic commits | Agent creates 3 files → 3 checkpoint commits in git log |
| 10 | Codebase mapping | `--init-knowledge --deep` → richer output than `--init-knowledge` |
| 11 | Model profiles | Configure budget profile → researcher agent uses cheaper model |
| 12 | TDD mode | `--tdd` → agent writes test before implementation (verify git log order) |
| 13 | Reviewer agents | `--orchestrate feature` → reviewer output in result |
| 14 | Context tracking | Activity log shows `[ctx: 72%]` |
| 15 | Auto-format | `auto_format = true` + write Python file → black formatted |
| 16 | Quick mode | `--quick` → completes in <15 turns, no consciousness built |
| 17 | MCP server | `python -m code_autonomy.mcp serve` → responds to MCP tool calls |
| 18 | Pattern export | `--export-patterns` → JSON file → `--import-patterns` → patterns in prompt |

### Regression Tests

- All existing 347 tests must pass after each sprint
- `pytest tests/ -v` run after every feature merge
- No existing CLI flags change behavior (backward compatible)
- Default config (no new keys set) behaves identically to current tool
