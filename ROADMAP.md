# Code-Autonomy Platform Roadmap

> **Goal:** Transform from a batch CLI tool into an open, self-hosted AI engineering
> platform that competes with Claude Code, Cursor, and GitHub Copilot — not by
> cloning them, but by being the thing none of them can be: open, self-hosted,
> any-provider, and interoperable with everything.

---

## Table of Contents

1. [Competitive Landscape](#1-competitive-landscape)
2. [Our Position & Moat](#2-our-position--moat)
3. [External Repo Review](#3-external-repo-review)
4. [Feature Gap Analysis](#4-feature-gap-analysis)
5. [Transformation Phases](#5-transformation-phases)
6. [Detailed Implementation Plan](#6-detailed-implementation-plan)
7. [Architecture After Transformation](#7-architecture-after-transformation)
8. [Success Metrics](#8-success-metrics)
9. [Risk & Mitigation](#9-risk--mitigation)

---

## 1. Competitive Landscape

### 1.1 Commercial Tools (Feb 2026)

| Tool | Category | Key Strengths | Weaknesses |
|------|----------|---------------|------------|
| **Claude Code** | CLI agent (Anthropic) | Agent Teams (parallel sub-agents), hooks system, MCP server/client, `/teleport` cross-device, extended thinking, auto-memory | Claude-only, SaaS, no self-hosting, no AST code intelligence, no formal verification |
| **Cursor 2.0** | AI IDE | 8 parallel background agents, browser tool for UI testing, Composer RL-trained model, YOLO mode, inline completions | SaaS, proprietary IDE, $20-40/mo, no autonomous PR pipeline, no code intelligence API |
| **GitHub Copilot** | IDE plugin + cloud agent | Coding agent (assign issue → get PR), runs in GitHub Actions, multi-model support, massive ecosystem | GitHub-locked, no self-hosting, no AST intelligence, no verification beyond tests/linters |

### 1.2 Open-Source Tools

| Tool | Category | Key Strengths | Weaknesses |
|------|----------|---------------|------------|
| **OpenHands** | Autonomous agent | Web UI, multi-agent, sandboxed execution, enterprise-ready | No code intelligence, no persistent knowledge, complex setup |
| **SWE-Agent** | Research agent | Agent-Computer Interface, strong benchmarks | Research-focused, minimal UX, no persistence, no verification |
| **Aider** | CLI pair programmer | Git-aware, multi-model, VS Code extension available | Single-agent, no code intelligence, no orchestration |
| **Kilo Code** | VS Code extension | Open-source, VS Code + JetBrains, MCP support | No autonomous pipeline, no code intelligence, no verification |

### 1.3 Where Code-Autonomy Sits Today

**Category:** Batch autonomous engineering pipeline (CLI)
**Direct competitors:** Copilot Coding Agent, Devin, SWE-Agent, OpenHands
**NOT competing with:** Claude Code, Cursor, Copilot as interactive pair programmers

---

## 2. Our Position & Moat

### 2.1 Current Advantages (already built)

| Advantage | Detail | Competitor Gap |
|-----------|--------|----------------|
| **AST-based code intelligence** | Symbol table + dependency graph + class hierarchy + entity embeddings + 7 tools (find_callers, impact_analysis, predict_breakage, etc.) | None of the commercial tools expose AST-level code intelligence as tools |
| **Post-edit verification with auto-repair** | Syntax check → import verification → caller signature check → scoped test discovery → repair prompt generation | No commercial tool has formal verification beyond running tests |
| **Multi-provider LLM support** | OpenAI, Anthropic, Gemini, AWS Bedrock, Azure OpenAI via LiteLLM + native Bedrock client | Claude Code = Claude only. Cursor/Copilot = limited model set |
| **Self-hosted / air-gapped** | Runs on any infrastructure, no SaaS dependency | All commercial tools require cloud connectivity |
| **Execution tracing (APO-compatible)** | Span-based tracing with per-action reward signals, designed for RL training | No commercial tool exposes agent traces with reward signals |
| **End-to-end pipeline** | Clone → branch → consciousness → code index → agent → test → commit → push → PR in one command | Copilot Coding Agent is closest but requires GitHub infrastructure |
| **Resilience primitives** | Circuit breaker + token bucket rate limiter + exponential backoff retry | Not exposed in commercial tools (handled by their infrastructure) |
| **Free and open** | No per-seat cost, no usage metering | $10-100/mo per seat for commercial tools |

### 2.2 Current Weaknesses

| Weakness | Impact | Addressable? |
|----------|--------|-------------|
| No IDE integration | Invisible to developers who live in VS Code/JetBrains | Yes — via MCP server + thin VS Code extension |
| No MCP ecosystem | Can't use external tools (GitHub, databases, browsers) | Yes — add MCP client |
| Single-threaded agent | Context rot on large tasks, no parallel execution | Yes — multi-agent orchestration |
| No real-time interaction | Batch mode only, user waits for completion | Partially — VS Code sidebar can stream activity |
| No inline completions | Not a keystroke-level tool | No — different category, not our fight |
| No webhook/bot mode | Can't be triggered from GitHub issues | Yes — lightweight daemon |
| No learning from corrections | Knowledge system records discoveries, not user feedback | Yes — continuous learning engine |

### 2.3 Strategic Positioning

```
The moat is: OPEN + SELF-HOSTED + ANY-PROVIDER + BEST CODE INTELLIGENCE + MCP INTEROPERABLE

No commercial tool can offer all five simultaneously because their business
models require lock-in. We can.
```

**For individual developers:** An MCP server that gives Claude Code / Cursor / VS Code
code intelligence superpowers they can't get anywhere else.

**For teams:** A self-hosted autonomous engineering platform — assign issues, get verified
PRs back, with team-wide learned patterns.

**For enterprises:** The only option that runs on their infrastructure, with their LLM
contracts (Bedrock/Azure), behind their firewall, with full observability.

---

## 3. External Repo Review

### 3.1 everything-claude-code

- **Repo:** https://github.com/affaan-m/everything-claude-code
- **What it is:** A comprehensive configuration toolkit for Claude Code (not a standalone tool). 42K+ stars, 10+ months of production use by an Anthropic hackathon winner.
- **Architecture:** Everything is Markdown — agents, skills, commands, rules, hooks. Layered composition: Rules → Skills → Commands → Agents → Hooks → MCPs → Learning.

**Key features to adopt:**

| Feature | Description | Priority | Effort |
|---------|-------------|----------|--------|
| **Continuous learning (instinct system v2)** | Self-improving feedback loop: hooks capture observations → pattern detection → instincts with confidence scores → evolution into skills/agents. Confidence increases with repeated observation, decays with inactivity or user corrections. Instincts exportable between users. | High | 2 weeks |
| **Multi-agent orchestration with handoffs** | `/orchestrate` chains agents (planner → TDD → reviewer → security) with structured handoff documents. 4 preset workflows (feature, bugfix, refactor, security) + custom sequences. | High | 2 weeks |
| **Specialized reviewer agents** | 13 agents: architect, TDD guide, code reviewer, security reviewer, build error resolver, refactor cleaner, doc updater, plus language-specific reviewers (Go, Python, database). Each has scoped tool permissions and model preference. | Medium | 1 week (agent definitions are Markdown) |
| **Pre/post tool hooks** | Event-driven automation on Claude Code lifecycle: PreToolUse (block/allow), PostToolUse (auto-format, lint), PreCompact (save state), SessionStart/End. | Medium | 1.5 weeks |
| **Context window discipline** | Strategic compaction, pre-compact hooks, session state preservation, explicit MCP budget guidance. Keeps orchestrator at 30-40% context utilization. | Medium | Embedded in orchestration design |
| **Slash commands** | 30+ quick commands: `/plan`, `/verify`, `/code-review`, `/build-fix`, `/tdd`, `/learn`, `/evolve`. Thin wrappers invoking skills/agents. | Low | 1 week |
| **Model profiles** | Per-agent model selection: quality (Opus), balanced (Sonnet), budget (Haiku). Different agents use different model tiers based on task complexity. | Low | 0.5 weeks |

**Features NOT to adopt:**
- MCP server configurations (Firecrawl, Supabase, etc.) — too specific to individual workflows
- Cross-tool portability (Cursor, OpenCode configs) — we'll solve this via MCP server instead
- Plugin manifest format — premature until we have a plugin ecosystem
- i18n — premature

### 3.2 get-shit-done (GSD)

- **Repo:** https://github.com/gsd-build/get-shit-done
- **What it is:** A spec-driven, multi-agent development system for Claude Code. Addresses "context rot" by spawning fresh sub-agents with clean 200K context windows per plan.
- **Architecture:** Zero-code (pure prompt engineering in Markdown + XML). 11 agents, wave-based parallel execution, file-based state in `.planning/` directory.

**Key features to adopt:**

| Feature | Description | Priority | Effort |
|---------|-------------|----------|--------|
| **Wave-based parallel sub-agent execution** | Plans grouped into dependency waves. Independent plans execute in parallel (each with fresh context window). Waves execute sequentially when dependent. DAG-based build system for code generation. | High | 2 weeks |
| **Goal-backward verification** | Verifier explicitly distrusts agent's self-reported summary. Works backward from requirements to check if outcomes were achieved, not just tasks completed. "SUMMARYs document what Claude SAID it did. You verify what ACTUALLY exists." | High | 1 week |
| **Discuss-before-plan phase** | Captures user preferences and "gray areas" before research or planning. Produces `CONTEXT.md` that feeds planner (locked decisions) and researcher (what to investigate). Prevents "AI built something, but not the way I wanted." | High | 0.5 weeks |
| **Deviation rules with scope boundaries** | 4 explicit rules: (1) auto-fix direct bugs, (2) auto-add missing critical functionality, (3) auto-fix blockers, (4) STOP for architectural changes. 3-attempt limit per deviation. Scope boundary: "Only auto-fix issues DIRECTLY caused by the current task's changes." | High | 0.5 weeks |
| **Brownfield codebase mapping** | 4 parallel agents analyze existing codebase: tech (stack/integrations), architecture (structure/patterns), quality (conventions/testing), concerns (tech debt/issues). Produces 7 docs consumed by planner/executor. | Medium | 1 week |
| **Session pause/resume with STATE.md** | Rich state file with current position, decisions made, blockers, next steps, and session handoff info. More than just checkpoint data. | Medium | 0.5 weeks |
| **Atomic git commits per task** | Commit after each atomic plan execution (not one commit at end). Enables granular rollback and preserves incremental progress. | Medium | 0.5 weeks |
| **TDD workflow mode** | Plans specify `tdd="true"` for Red-Green-Refactor execution order. Write test → run (red) → implement → run (green) → refactor. | Medium | 0.5 weeks |
| **Quick mode** | Ad-hoc tasks with agent guarantees (atomic commits, state tracking) but without full research/plan/verify cycle. Low overhead for small changes. | Low | 0.5 weeks |

**Features NOT to adopt:**
- `.planning/` directory structure — we'll use our existing knowledge/checkpoint system instead
- XML prompt structures — our Python-based approach is more maintainable
- npm distribution — we're Python-native
- `gsd-tools.cjs` utility — replicate functionality in Python

---

## 4. Feature Gap Analysis

### 4.1 Features to Build (from external repos + competitive analysis)

| # | Feature | Source | Priority | Effort | Depends On |
|---|---------|--------|----------|--------|------------|
| 1 | MCP Server (expose our tools) | Competitive analysis | **Critical** | 1.5 weeks | — |
| 2 | MCP Client (use external tools) | Competitive analysis | **Critical** | 1 week | — |
| 3 | Deviation rules with scope boundaries | GSD | **High** | 0.5 weeks | — |
| 4 | Goal-backward verification | GSD | **High** | 1 week | — |
| 5 | Discuss-before-plan phase | GSD | **High** | 0.5 weeks | — |
| 6 | Multi-agent orchestration engine | Both repos | **High** | 2 weeks | #1 (for agent isolation) |
| 7 | Wave-based parallel execution | GSD | **High** | 2 weeks | #6 |
| 8 | Specialized agent definitions | everything-claude-code | **High** | 1 week | #6 |
| 9 | Pre/post tool hooks | everything-claude-code | **Medium** | 1.5 weeks | — |
| 10 | Continuous learning engine | everything-claude-code | **Medium** | 2 weeks | — |
| 11 | GitHub/GitLab bot mode | Competitive (Copilot) | **Medium** | 1.5 weeks | — |
| 12 | VS Code extension (thin shell) | Competitive (Cursor) | **Medium** | 2 weeks | #1 |
| 13 | Brownfield codebase mapping | GSD | **Medium** | 1 week | — |
| 14 | Session state (rich STATE.md) | GSD | **Medium** | 0.5 weeks | — |
| 15 | Atomic git commits per task | GSD | **Medium** | 0.5 weeks | — |
| 16 | TDD workflow mode | Both repos | **Medium** | 0.5 weeks | — |
| 17 | Model profiles (quality/balanced/budget) | everything-claude-code | **Low** | 0.5 weeks | — |
| 18 | Quick mode (low-overhead tasks) | GSD | **Low** | 0.5 weeks | — |
| 19 | Slash commands framework | everything-claude-code | **Low** | 1 week | #6 |
| 20 | Agent definition marketplace/sharing | everything-claude-code | **Low** | 1 week | #8 |

### 4.2 Features We Already Have (no action needed)

- AST-based code intelligence (symbol table, dependency graph, hierarchy, embeddings)
- Post-edit verification with auto-repair loop
- Multi-provider LLM support (5 providers)
- Execution tracing with reward signals
- Circuit breaker + rate limiter + retry
- Working memory + persistent knowledge + GCC
- Plan mode with approval workflow
- Ask mode for Q&A
- Turn budgets (summarization + testing) — just shipped
- Checkpointing + resume — just shipped
- Project consciousness (structure, conventions, samples)
- Reference PR as template
- Framework repo as read-only context
- Testing strategies (BDD, contract, integration, unit, e2e, SOAP)

---

## 5. Transformation Phases

### Phase 0: Immediate Wins (Week 1)
**Goal:** Ship the highest-impact, lowest-effort features that improve agent quality today.

| Item | File(s) | Effort |
|------|---------|--------|
| Deviation rules with scope boundaries | `src/agent/analyzer.py` | 2 days |
| Discuss-before-plan phase | `src/agent/analyzer.py`, `main.py` | 2 days |
| Atomic git commits per task | `src/agent/tools.py`, `src/agent/analyzer.py` | 1 day |

**Deviation rules** — Add to the agent system prompt and enforce in the tool execution loop:
```
DEVIATION RULES:
Rule 1: Auto-fix bugs DIRECTLY caused by your current changes (max 3 attempts)
Rule 2: Auto-add missing functionality that is EXPLICITLY required
Rule 3: Auto-fix build/test blockers caused by your changes (max 3 attempts)
Rule 4: STOP and report if you encounter architectural changes needed
SCOPE: Only fix issues directly caused by the current task's changes.
       Do NOT fix pre-existing issues, refactor unrelated code, or change
       architecture without explicit approval.
```

**Discuss phase** — New `--discuss` flag or auto-triggered when requirements contain
ambiguous language:
- `generate_discussion_with_agent()` function (read-only, ask clarifying questions)
- Output: structured decisions file that feeds into the main agent context
- Can be skipped with `--no-discuss` for CI/CD pipelines

**Atomic commits** — Add `gcc_commit` equivalent that auto-commits after each
successful edit+test cycle in agent mode.

### Phase 1: MCP Integration (Weeks 2-3)
**Goal:** Make our code intelligence available inside every IDE. Make our agent extensible.

#### 1A: MCP Server — Expose Our Tools

**New file:** `src/mcp_server.py`

Expose our code intelligence as MCP tools using the [Python MCP SDK](https://github.com/modelcontextprotocol/python-sdk):

```
MCP Tools:
  code_autonomy.find_callers(symbol_name) → callers list
  code_autonomy.find_dependents(file_path) → dependent files
  code_autonomy.impact_analysis(file_path) → full impact report
  code_autonomy.predict_breakage(file_path, changes_description) → risk report
  code_autonomy.describe_entity(symbol_name) → full description
  code_autonomy.find_similar(query, top_k) → semantic matches
  code_autonomy.context_for_edit(file_path, symbol_name) → pre-edit context
  code_autonomy.verify_changes(file_paths) → verification report
  code_autonomy.get_knowledge(repo_path) → persistent knowledge
  code_autonomy.run_autonomous(requirement, repo_path) → trigger full pipeline

MCP Resources:
  project://consciousness → project structure and conventions
  project://knowledge → learned patterns from prior runs
  project://code-index-stats → symbol count, file count, graph stats

Transport:
  stdio (local, for Claude Code / VS Code)
  HTTP/SSE (remote, for team server)
```

**CLI entry point:**
```bash
# Run as MCP server (stdio for local IDE integration)
python -m code_autonomy.mcp serve

# Run as HTTP server (for team/remote access)
python -m code_autonomy.mcp serve --transport http --port 8080
```

**Config for Claude Code users:**
```json
{
  "mcpServers": {
    "code-autonomy": {
      "command": "python",
      "args": ["-m", "code_autonomy.mcp", "serve"],
      "env": { "OPENAI_API_KEY": "..." }
    }
  }
}
```

#### 1B: MCP Client — Use External Tools

**New file:** `src/mcp_client.py`

Add MCP client to the agent tool set so our agent can call external MCP servers:

```
Config (config.ini):
  [mcp]
  servers = github,postgres,browser

  [mcp.github]
  command = npx
  args = -y @modelcontextprotocol/server-github
  env_GITHUB_TOKEN = ${GITHUB_TOKEN}

  [mcp.postgres]
  command = npx
  args = -y @modelcontextprotocol/server-postgres
  env_DATABASE_URL = ${DATABASE_URL}
```

**Agent tool:**
```
mcp_call(server, tool, arguments) → result
```

The agent discovers available MCP tools at startup and can use them alongside built-in tools.

### Phase 2: Multi-Agent Orchestration (Weeks 4-5)
**Goal:** Break the single-agent bottleneck. Enable parallel execution with specialized agents.

#### 2A: Orchestration Engine

**New files:**
- `src/agent/orchestrator.py` — DAG-based orchestration engine
- `src/agent/agent_defs.py` — agent definition loader (from Markdown)
- `.code-autonomy/agents/` — default agent definitions

**Orchestration flow:**
```
1. Parse requirement → identify workflow type (feature/bugfix/refactor/security)
2. Load agent pipeline for workflow type
3. Execute agents in dependency order:
   - Independent agents run in PARALLEL (separate processes, fresh context)
   - Dependent agents run SEQUENTIALLY (receive handoff docs from predecessors)
4. Collect results, merge handoff documents
5. Return OrchestratorResult
```

**Agent definition format** (Markdown with YAML frontmatter):
```markdown
# .code-autonomy/agents/implementer.md
---
name: implementer
model_preference: balanced    # quality | balanced | budget
tools: [read_file, write_file, edit_file, delete_file, run_command,
        grep, list_dir, find_files, update_memory, task_complete,
        find_callers, impact_analysis, context_for_edit]
max_turns: 30
receives_from: [planner]
sends_to: [verifier]
---
You are an expert software engineer. Implement the changes described
in the plan handoff document. Follow existing code conventions.
After each file change, run relevant tests.
```

**Default agent pipeline for `feature` workflow:**
```
discuss → [researcher_1, researcher_2, researcher_3, researcher_4] → planner
    → [implementer_wave_1, implementer_wave_2] → verifier → reviewer
```

**Handoff document format:**
```markdown
## Handoff: planner → implementer
### Requirement
Add password reset endpoint
### Decisions (from discuss phase)
- Use email-based reset (not SMS)
- Token expires in 1 hour
- Rate limit: 3 requests per hour per email
### Plan
1. Create src/auth/reset.py with ResetService class
2. Add POST /auth/reset-password route
3. Add tests for happy path + rate limiting + expired token
### Files to modify
- src/auth/routes.py (add new route)
- src/auth/models.py (add ResetToken model)
### Files to create
- src/auth/reset.py
- tests/test_reset.py
```

#### 2B: Wave-Based Parallel Execution

**In `src/agent/orchestrator.py`:**

```
Plan decomposition:
  Plan 1: Create ResetToken model (no dependencies)
  Plan 2: Create ResetService (depends on Plan 1)
  Plan 3: Add route handler (depends on Plan 2)
  Plan 4: Write tests (depends on Plans 1-3)

Wave execution:
  Wave 1: [Plan 1]           ← runs alone (dependency root)
  Wave 2: [Plan 2]           ← depends on wave 1
  Wave 3: [Plan 3]           ← depends on wave 2
  Wave 4: [Plan 4]           ← depends on wave 3
```

Each plan in a wave spawns a fresh agent process (clean context window).
Independent plans within a wave run in parallel via `multiprocessing` or `asyncio`.

#### 2C: Goal-Backward Verification Agent

**New agent definition:** `.code-autonomy/agents/verifier.md`

Extends our existing `post_edit_verification_gate` with requirement-level checking:

```
Verification levels:
  Level 1: Syntax check (py_compile) ← already have
  Level 2: Import resolution ← already have
  Level 3: Caller signature compatibility ← already have
  Level 4: Scoped test execution ← already have
  Level 5: Goal-backward requirement check ← NEW
    - For each requirement bullet point:
      - Does the code implement it? (search for evidence)
      - Does a test cover it? (search for test)
      - Does it work? (run specific test)
    - Produce verification matrix:
      | Requirement | Implemented? | Tested? | Passing? |
```

### Phase 3: Learning & Hooks (Weeks 6-7)
**Goal:** Make the agent better with every run. Let users customize behavior.

#### 3A: Pre/Post Tool Hooks

**New file:** `src/agent/hooks.py`

```
Hook types:
  PreToolUse   — runs before tool execution, can block/modify
  PostToolUse  — runs after tool execution, can transform output
  PreAgent     — runs before agent loop starts
  PostAgent    — runs after agent loop completes
  PreCommit    — runs before git commit

Hook definition (config.ini):
  [hooks]
  pre_tool_use = python scripts/hooks/pre_tool.py
  post_tool_use = python scripts/hooks/post_tool.py

Hook contract:
  stdin: JSON {tool_name, args, result?}
  stdout: JSON {decision: "allow"|"block"|"modify", modified_args?, message?}
  exit code 0: allow, exit code 2: block
```

**Built-in hooks:**
- Block dangerous commands (rm -rf, git push --force) — replaces static blocklist
- Auto-format after edit (detect prettier/black/gofmt, run after write_file/edit_file)
- Warn before git push
- Rate limit run_command calls

#### 3B: Continuous Learning Engine

**New file:** `src/agent/learning.py`
**Extended:** `src/agent/knowledge.py`

```
Learning pipeline:
  1. CAPTURE: After each agent run, compare:
     - Files agent changed vs files user actually committed (git diff)
     - Agent's proposed code vs user's final code
     - Tools that failed repeatedly
     - Patterns in successful runs

  2. DETECT: Identify patterns:
     - User corrections (agent wrote X, user changed to Y)
     - Repeated tool sequences (always grep before edit)
     - Style preferences (naming, imports, structure)
     - Error patterns (same mistake across runs)

  3. STORE: Create Pattern entries:
     - pattern_type: "correction" | "preference" | "anti_pattern" | "workflow"
     - content: description of the pattern
     - confidence: 0.0-1.0 (increases with repetition, decays with time)
     - evidence: list of run IDs where pattern was observed
     - domain: "python" | "java" | "testing" | "git" | etc.

  4. APPLY: On next run, inject high-confidence patterns into system prompt:
     "Based on previous runs in this repo:
      - Always use constructor injection (confidence: 0.9)
      - Prefer pytest parametrize over separate test functions (confidence: 0.7)
      - Import order: stdlib, third-party, local (confidence: 0.85)"

  5. EVOLVE: Periodically consolidate patterns:
     - Cluster related patterns into rules
     - Promote high-confidence rules to .code-autonomy.md
     - Archive low-confidence patterns that haven't been reinforced
```

**Storage:** New `patterns` field in `KnowledgeEntry`:
```python
@dataclass
class Pattern:
    pattern_type: str        # correction, preference, anti_pattern, workflow
    content: str             # what the pattern says
    confidence: float        # 0.0 to 1.0
    evidence: list[str]      # run IDs where observed
    domain: str              # python, java, testing, git, etc.
    created_at: str
    last_seen: str
    decay_rate: float = 0.05 # confidence drops per week without reinforcement
```

### Phase 4: Distribution & Integration (Weeks 8-10)
**Goal:** Make code-autonomy accessible from everywhere — IDE, GitHub, CI/CD.

#### 4A: VS Code Extension (Thin Shell)

**New directory:** `vscode-extension/`

Built on [VS Code AI extensibility API](https://code.visualstudio.com/api/extension-guides/ai/ai-extensibility-overview),
connects to our MCP server (Phase 1):

```
Features:
  - Chat participant: @code-autonomy in VS Code chat
  - Sidebar: real-time agent activity stream (from execution tracing)
  - Diagnostics: verification results as editor warnings/errors
  - Code lens: "Impact: 5 callers" shown above functions
  - Commands: "Code-Autonomy: Run Agent", "Code-Autonomy: Verify File"

Architecture:
  VS Code Extension (TypeScript)
      ↓ MCP protocol (stdio)
  code-autonomy MCP server (Python, runs locally)
      ↓ calls
  Code index, knowledge, agent loop, verification
```

The extension is intentionally thin — all intelligence lives in the Python backend.
The extension only handles UI rendering and MCP communication.

#### 4B: GitHub/GitLab Bot Mode

**New file:** `src/bot/daemon.py`, `src/bot/webhook.py`

```
Trigger options:
  1. Webhook listener (receives GitHub/GitLab events)
  2. Polling mode (checks for assigned issues periodically)
  3. CLI mode: `python -m code_autonomy.bot --repo owner/repo`

Flow:
  GitHub Issue #42 assigned to @code-autonomy-bot
      ↓
  Webhook → daemon receives event
      ↓
  Clone repo → run agent pipeline → create PR
      ↓
  Post comment on issue:
    "Created PR #43.
     Files changed: 3
     Verification: syntax ✓ | imports ✓ | callers ✓ | tests ✓
     Impact: 0 breaking changes predicted
     Turns used: 23/50 | Tokens: 45,230"
      ↓
  Post verification report on PR as review comment
```

**Config:**
```ini
[bot]
mode = webhook          # webhook | poll | manual
listen_port = 8081
poll_interval = 60      # seconds (for poll mode)
assignee = code-autonomy-bot
auto_merge = false      # never auto-merge by default
max_concurrent = 3      # max parallel agent runs
```

#### 4C: CI/CD Integration

**New file:** `.github/actions/code-autonomy/action.yml`

GitHub Action that runs code-autonomy as a CI step:

```yaml
# .github/workflows/auto-implement.yml
name: Auto-implement
on:
  issues:
    types: [assigned]
jobs:
  implement:
    if: github.event.assignee.login == 'code-autonomy-bot'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: code-autonomy/action@v1
        with:
          requirement: ${{ github.event.issue.body }}
          provider: anthropic
          model: claude-sonnet-4-5
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
```

---

## 6. Detailed Implementation Plan

### 6.1 File-Level Changes Per Phase

#### Phase 0: Immediate Wins

| File | Changes |
|------|---------|
| `src/agent/analyzer.py` | Add deviation rules to system prompt; add scope boundary enforcement in tool loop; add discuss phase function `generate_discussion_with_agent()` |
| `src/agent/tools.py` | Add `atomic_commit` tool; track commit points after successful edit+test |
| `main.py` | Add `--discuss` flag; add `--no-discuss` flag; wire discuss phase before agent/plan mode |
| `src/agent/analyzer.py` (system prompt) | Append deviation rules section to `_SYSTEM_PROMPT` |

#### Phase 1: MCP Integration

| File | Changes |
|------|---------|
| `src/mcp_server.py` | **NEW** — MCP server using `mcp` Python SDK, exposes code intelligence tools |
| `src/mcp_client.py` | **NEW** — MCP client, discovers and invokes external MCP server tools |
| `src/agent/tools.py` | Add `mcp_call` tool definition and execution |
| `src/config_loader.py` | Add `[mcp]` config section for server definitions |
| `main.py` | Add `mcp serve` subcommand |
| `setup.py` / `pyproject.toml` | Add `mcp` dependency |

#### Phase 2: Multi-Agent Orchestration

| File | Changes |
|------|---------|
| `src/agent/orchestrator.py` | **NEW** — DAG orchestration engine, workflow definitions, wave executor |
| `src/agent/agent_defs.py` | **NEW** — Markdown agent definition parser, default agents loader |
| `src/agent/handoff.py` | **NEW** — Handoff document generation and parsing |
| `src/agent/analyzer.py` | Extract agent loop into reusable `run_single_agent()` function |
| `.code-autonomy/agents/*.md` | **NEW** — Default agent definitions (implementer, verifier, reviewer, security, planner, researcher, discuss) |
| `main.py` | Add `--orchestrate` flag, wire orchestration pipeline |
| `src/agent/context.py` | Add goal-backward verification to `summarize_large_output` |

#### Phase 3: Learning & Hooks

| File | Changes |
|------|---------|
| `src/agent/hooks.py` | **NEW** — Hook registration, execution, stdin/stdout contract |
| `src/agent/learning.py` | **NEW** — Pattern detection, confidence scoring, decay, evolution |
| `src/agent/knowledge.py` | Add `Pattern` dataclass, extend `KnowledgeEntry` with patterns field |
| `src/agent/analyzer.py` | Inject hook calls around tool execution; inject learned patterns into system prompt |
| `src/config_loader.py` | Add `[hooks]` config section |

#### Phase 4: Distribution

| File | Changes |
|------|---------|
| `vscode-extension/` | **NEW** — VS Code extension (TypeScript, ~500 lines) |
| `src/bot/daemon.py` | **NEW** — Webhook listener / poller daemon |
| `src/bot/webhook.py` | **NEW** — GitHub/GitLab webhook handlers |
| `.github/actions/code-autonomy/` | **NEW** — GitHub Action definition |
| `src/config_loader.py` | Add `[bot]` config section |
| `main.py` | Add `bot` subcommand |

### 6.2 Timeline

```
Week 1:    Phase 0 — Deviation rules, discuss phase, atomic commits
Week 2-3:  Phase 1 — MCP server + MCP client
Week 4-5:  Phase 2 — Orchestration engine + parallel execution + verification agent
Week 6-7:  Phase 3 — Hooks system + continuous learning
Week 8-9:  Phase 4A — VS Code extension
Week 9-10: Phase 4B — GitHub bot mode + CI/CD action
```

### 6.3 Dependency Graph

```
Phase 0 (no deps)
    │
    ├── Phase 1A: MCP Server (no deps)
    │       │
    │       └── Phase 4A: VS Code Extension (needs MCP server)
    │
    ├── Phase 1B: MCP Client (no deps)
    │       │
    │       └── Phase 2: Orchestration (benefits from MCP client for external tools)
    │               │
    │               └── Phase 2B: Wave Execution (needs orchestration)
    │
    ├── Phase 3A: Hooks (no deps)
    │
    ├── Phase 3B: Learning (no deps, but benefits from multiple runs)
    │
    └── Phase 4B: Bot Mode (no deps, benefits from orchestration)
```

---

## 7. Architecture After Transformation

```
┌─────────────────────────────────────────────────────────────┐
│                    CODE-AUTONOMY PLATFORM                    │
│                                                             │
│  INTERFACES                                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐ │
│  │ CLI      │  │ VS Code  │  │ GitHub   │  │ MCP Server │ │
│  │ (batch)  │  │ Extension│  │ Bot      │  │ (any IDE)  │ │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └─────┬──────┘ │
│       └──────────────┴─────────────┴──────────────┘         │
│                          │                                   │
│  ORCHESTRATION                                              │
│  ┌───────────────────────┴───────────────────────┐          │
│  │              Orchestration Engine              │          │
│  │  ┌────────┐  ┌─────────┐  ┌────────────────┐ │          │
│  │  │Discuss │  │Planner  │  │Wave Executor   │ │          │
│  │  │Phase   │  │(DAG)    │  │(parallel agents│ │          │
│  │  └────────┘  └─────────┘  └────────────────┘ │          │
│  └───────────────────────────────────────────────┘          │
│                          │                                   │
│  AGENTS (parallel, fresh context each)                      │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐      │
│  │Implement │ │ Verify   │ │ Review   │ │ Security │      │
│  │Agent     │ │ Agent    │ │ Agent    │ │ Agent    │      │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘      │
│       │              │             │             │           │
│  CORE ENGINE                                                │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  ┌───────────┐ ┌──────────┐ ┌──────────────────────┐│   │
│  │  │Code Index │ │Knowledge │ │Verification          ││   │
│  │  │AST+graph  │ │memory +  │ │syntax+imports+callers││   │
│  │  │+embeddings│ │learning  │ │+goals (backward)     ││   │
│  │  └───────────┘ └──────────┘ └──────────────────────┘│   │
│  │  ┌───────────┐ ┌──────────┐ ┌──────────────────────┐│   │
│  │  │LLM Client │ │Tracing   │ │Resilience            ││   │
│  │  │5 providers│ │APO-ready │ │breaker+rate+retry    ││   │
│  │  └───────────┘ └──────────┘ └──────────────────────┘│   │
│  │  ┌───────────┐ ┌──────────┐                         │   │
│  │  │Hooks      │ │MCP Client│→ GitHub, Slack, DB,     │   │
│  │  │pre/post   │ │          │  browser, deploy, ...   │   │
│  │  └───────────┘ └──────────┘                         │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 8. Success Metrics

### 8.1 Technical Metrics

| Metric | Current | Phase 0 Target | Phase 2 Target | Phase 4 Target |
|--------|---------|----------------|----------------|----------------|
| Agent success rate (task_complete) | ~60% | 75% | 85% | 90% |
| Avg turns to completion | ~35/50 | ~28/50 | ~20/50 | ~18/50 |
| Wasted turns (deviation spirals) | ~15% | ~5% | ~3% | ~2% |
| Requirement coverage (verified) | Not measured | Not measured | 80% | 90% |
| Context window utilization at completion | ~95% (exhausted) | ~80% | ~50% (per agent) | ~50% |

### 8.2 Distribution Metrics

| Metric | Phase 1 Target | Phase 4 Target |
|--------|----------------|----------------|
| MCP server usable from Claude Code | Yes | Yes |
| MCP server usable from Cursor | Yes | Yes |
| VS Code extension published | No | Yes |
| GitHub Action published | No | Yes |
| PyPI package published | No | Yes |

### 8.3 Competitive Parity Checklist

| Feature | Claude Code | Cursor | Copilot | Target Phase |
|---------|:-:|:-:|:-:|---|
| Multi-agent parallel | Yes | Yes | No | Phase 2 |
| IDE integration | Yes | Yes | Yes | Phase 4A |
| Hooks/extensibility | Yes | Yes | Partial | Phase 3A |
| MCP client | Yes | Yes | Yes | Phase 1B |
| MCP server | Yes | No | No | Phase 1A |
| Async/background work | Yes | Yes | Yes | Phase 4B |
| Issue → PR pipeline | No | No | Yes | Phase 4B |
| Code intelligence | No | No | No | **Already have** |
| Formal verification | No | No | No | **Already have** |
| Self-hosted | No | No | No | **Already have** |
| Any LLM provider | No | Partial | Partial | **Already have** |
| Execution tracing | No | No | No | **Already have** |
| Learning from corrections | Partial | No | No | Phase 3B |

---

## 9. Risk & Mitigation

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| MCP protocol changes (still evolving) | MCP server/client breaks | Medium | Pin SDK version; abstract transport layer; monitor MCP spec releases |
| Multi-agent coordination complexity | Agents produce conflicting changes | High | Handoff documents enforce boundaries; file-level locking in wave executor; merge conflict detection before commit |
| Context window size varies by model | Wave execution assumes large context | Medium | Model profiles define per-model turn limits; auto-detect context size from model name |
| Learning system learns wrong patterns | Bad patterns reduce agent quality | Medium | Confidence decay (patterns expire without reinforcement); user can delete patterns; minimum 3 observations before applying |
| VS Code extension maintenance burden | TypeScript + Python dual codebase | Medium | Keep extension thin (MCP passthrough only); no business logic in TypeScript |
| Bot mode security (arbitrary code execution) | Agent runs untrusted code from issues | High | Sandboxed execution (Docker/nsjail); command allowlist enforced; never auto-merge; human review required |
| Commercial tools copy our features | Code intelligence, verification adopted by Claude Code/Cursor | Low (short term) | Our moat is the combination (open + self-hosted + any-provider); individual features can be copied but the platform can't |
| Scope creep across 10 weeks | Phases slip, quality drops | High | Each phase ships independently; Phase 0 and 1 are highest priority; Phases 3-4 can be cut without losing core value |

---

## Appendix: Reference Links

- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [MCP Specification](https://modelcontextprotocol.io/docs/develop/build-server)
- [VS Code AI Extensibility API](https://code.visualstudio.com/api/extension-guides/ai/ai-extensibility-overview)
- [Claude Agent SDK](https://platform.claude.com/docs/en/agent-sdk/overview)
- [Claude Code Hooks Reference](https://code.claude.com/docs/en/hooks)
- [everything-claude-code](https://github.com/affaan-m/everything-claude-code)
- [get-shit-done](https://github.com/gsd-build/get-shit-done)
- [OpenHands](https://github.com/All-Hands-AI/OpenHands)
- [SWE-Agent](https://github.com/princeton-nlp/SWE-agent)
- [Kilo Code](https://kilo.ai/)
- [Aider](https://github.com/paul-gauthier/aider)
