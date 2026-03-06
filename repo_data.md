Feature Gap Analysis: What Code-Autonomy Needs

  After reviewing both repos against our codebase, here's what's worth adopting — organized by priority.

  ---
  HIGH PRIORITY — Clear gaps that would solve real problems
  ┌─────┬──────────────────────┬────────────────────────┬───────────────────────────────────┬───────────────────────────────────────┐
  │  #  │       Feature        │         Source         │           What we lack            │            Why it matters             │
  ├─────┼──────────────────────┼────────────────────────┼───────────────────────────────────┼───────────────────────────────────────┤
  │     │                      │                        │ Our agent loop is single-threaded │ Our agent exhausts its context window │
  │     │ Wave-based parallel  │                        │  — one LLM call at a time. GSD    │  on large tasks. Parallel sub-agents  │
  │ 1   │ sub-agent execution  │ GSD                    │ spawns independent plans in       │ with clean windows would let us       │
  │     │                      │                        │ parallel, each with a fresh       │ tackle bigger requirements without    │
  │     │                      │                        │ context window.                   │ context rot.                          │
  ├─────┼──────────────────────┼────────────────────────┼───────────────────────────────────┼───────────────────────────────────────┤
  │     │                      │                        │ Our post-edit verification only   │                                       │
  │     │                      │                        │ checks syntax, imports, and       │ Our agent can report "task_complete"  │
  │     │ Goal-backward        │                        │ caller signatures. GSD's verifier │ after 50 turns with partial work. A   │
  │ 2   │ verification         │ GSD                    │  explicitly distrusts the agent's │ verifier that checks outcomes against │
  │     │                      │                        │  self-reported summary and checks │  requirements would catch incomplete  │
  │     │                      │                        │  whether the requirement was      │ implementations.                      │
  │     │                      │                        │ actually met.                     │                                       │
  ├─────┼──────────────────────┼────────────────────────┼───────────────────────────────────┼───────────────────────────────────────┤
  │     │                      │                        │ We go straight from requirements  │ Ambiguous requirements cause wasted   │
  │     │ Discuss-before-plan  │                        │ to agent execution. No structured │ turns. A structured discussion phase  │
  │ 3   │ phase                │ GSD                    │  step to capture user             │ (even optional) would front-load      │
  │     │                      │                        │ preferences, ambiguities, or gray │ decisions and reduce rework.          │
  │     │                      │                        │  areas.                           │                                       │
  ├─────┼──────────────────────┼────────────────────────┼───────────────────────────────────┼───────────────────────────────────────┤
  │     │                      │                        │ Our stuck detection only catches  │ A common failure mode: agent finds a  │
  │     │                      │                        │ 3x same error. No rule to prevent │ test failure, starts "fixing"         │
  │     │ Deviation rules with │                        │  the agent from spiraling into    │ unrelated code, burns 20 turns, and   │
  │ 4   │  scope boundaries    │ GSD                    │ fixing unrelated issues or making │ never returns to the original task.   │
  │     │                      │                        │  architectural changes without    │ Scoped deviation rules (auto-fix      │
  │     │                      │                        │ asking.                           │ direct bugs, stop for architectural   │
  │     │                      │                        │                                   │ changes) would prevent this.          │
  ├─────┼──────────────────────┼────────────────────────┼───────────────────────────────────┼───────────────────────────────────────┤
  │     │                      │                        │ We save knowledge per-repo        │ Our knowledge system records what the │
  │     │                      │                        │ (project overview, patterns, file │  agent discovered, not what the user  │
  │ 5   │ Continuous learning  │ everything-claude-code │  notes) but don't learn from user │ corrected. A feedback loop that       │
  │     │ / instinct system    │                        │  corrections or repeated patterns │ captures corrections and evolves them │
  │     │                      │                        │  across sessions.                 │  into behavioral rules would improve  │
  │     │                      │                        │                                   │ over time.                            │
  ├─────┼──────────────────────┼────────────────────────┼───────────────────────────────────┼───────────────────────────────────────┤
  │     │                      │                        │                                   │ A security reviewer or code reviewer  │
  │     │                      │                        │ We have one agent loop with one   │ agent running as a post-step would    │
  │     │ Multi-agent          │                        │ system prompt. No way to chain    │ catch issues our single               │
  │ 6   │ orchestration with   │ everything-claude-code │ specialized agents (planner →     │ general-purpose agent misses. The     │
  │     │ handoffs             │                        │ implementer → reviewer →          │ /orchestrate pattern of structured    │
  │     │                      │                        │ security).                        │ handoff documents between agents is   │
  │     │                      │                        │                                   │ compelling.                           │
  └─────┴──────────────────────┴────────────────────────┴───────────────────────────────────┴───────────────────────────────────────┘
  ---
  MEDIUM PRIORITY — Would improve quality and UX
  ┌─────┬────────────────────────────┬────────────────────────┬────────────────────────────────┬────────────────────────────────────┐
  │  #  │          Feature           │         Source         │          What we lack          │           Why it matters           │
  ├─────┼────────────────────────────┼────────────────────────┼────────────────────────────────┼────────────────────────────────────┤
  │     │                            │                        │ No hook system. Users can't    │ Our command_allowlist_only and     │
  │     │                            │                        │ inject custom logic            │ blocked_commands are static        │
  │ 7   │ Pre/post tool hooks        │ everything-claude-code │ before/after tool calls (e.g., │ config. Hooks would let users add  │
  │     │                            │                        │  auto-format after edit, warn  │ dynamic guardrails without         │
  │     │                            │                        │ before git push, block         │ modifying our code.                │
  │     │                            │                        │ dangerous commands).           │                                    │
  ├─────┼────────────────────────────┼────────────────────────┼────────────────────────────────┼────────────────────────────────────┤
  │     │                            │                        │ Our --resume restores          │ Our checkpoint saves files_changed │
  │     │                            │                        │ checkpoint data but not        │  and working_memory but loses the  │
  │ 8   │ Session pause/resume with  │ GSD                    │ conversational state. GSD      │ agent's reasoning context. A       │
  │     │ state file                 │                        │ writes a full STATE.md with    │ richer state file would make       │
  │     │                            │                        │ current position, decisions,   │ resume more effective.             │
  │     │                            │                        │ blockers, and next steps.      │                                    │
  ├─────┼────────────────────────────┼────────────────────────┼────────────────────────────────┼────────────────────────────────────┤
  │     │                            │                        │                                │ If the agent changes 10 files and  │
  │     │                            │                        │ We do one commit at the end    │ then fails on the 11th, we have no │
  │ 9   │ Atomic git commits per     │ GSD                    │ (stage_and_commit). GSD        │  partial commit. Atomic commits    │
  │     │ task                       │                        │ commits after each atomic plan │ would preserve incremental         │
  │     │                            │                        │  is executed.                  │ progress and make rollback         │
  │     │                            │                        │                                │ granular.                          │
  ├─────┼────────────────────────────┼────────────────────────┼────────────────────────────────┼────────────────────────────────────┤
  │     │                            │                        │ Our consciousness system       │ Our --init-knowledge generates a   │
  │     │                            │                        │ indexes structure/conventions  │ .code-autonomy.md but it's shallow │
  │     │ Codebase mapping for       │                        │ but doesn't produce            │  compared to GSD's                 │
  │ 10  │ brownfield projects        │ GSD                    │ human-readable architecture    │ 4-parallel-agent codebase mapping  │
  │     │                            │                        │ docs (ARCHITECTURE.md,         │ that produces separate docs for    │
  │     │                            │                        │ CONVENTIONS.md, CONCERNS.md).  │ stack, architecture, quality, and  │
  │     │                            │                        │                                │ concerns.                          │
  ├─────┼────────────────────────────┼────────────────────────┼────────────────────────────────┼────────────────────────────────────┤
  │     │                            │                        │ We use one model for the main  │ Exploration turns don't need       │
  │     │ Model profiles             │                        │ loop and auto-select a cheaper │ Opus-level reasoning. A budget     │
  │ 11  │ (quality/balanced/budget)  │ GSD                    │  model for summarization. No   │ profile using Haiku for read tools │
  │     │                            │                        │ per-task model selection.      │  and Sonnet for writes would cut   │
  │     │                            │                        │                                │ costs 5-10x on exploratory phases. │
  ├─────┼────────────────────────────┼────────────────────────┼────────────────────────────────┼────────────────────────────────────┤
  │     │                            │                        │                                │ A TDD mode (write test → run (red) │
  │     │                            │                        │ No explicit TDD support. Our   │  → implement → run (green) →       │
  │ 12  │ TDD workflow mode          │ both repos             │ agent writes code first, then  │ refactor) would produce            │
  │     │                            │                        │ runs tests.                    │ better-tested code, especially for │
  │     │                            │                        │                                │  Java projects where our testing   │
  │     │                            │                        │                                │ strategies already exist.          │
  └─────┴────────────────────────────┴────────────────────────┴────────────────────────────────┴────────────────────────────────────┘
  ---
  LOWER PRIORITY — Nice to have, less urgent
  #: 13
  Feature: Specialized reviewer agents (security, code quality, database)
  Source: everything-claude-code
  What we lack: We have no post-implementation review step.
  ────────────────────────────────────────
  #: 14
  Feature: Context window utilization tracking
  Source: both repos
  What we lack: We estimate tokens but don't expose utilization % to the user or agent.
  ────────────────────────────────────────
  #: 15
  Feature: Auto-format after edit hooks (prettier, black)
  Source: everything-claude-code
  What we lack: Agent-written code isn't auto-formatted.
  ────────────────────────────────────────
  #: 16
  Feature: Quick mode for ad-hoc tasks
  Source: GSD
  What we lack: Our agent mode has the same overhead for small and large tasks.
  ────────────────────────────────────────
  #: 17
  Feature: Multi-editor support (Cursor, VS Code)
  Source: everything-claude-code
  What we lack: We're CLI-only.
  ────────────────────────────────────────
  #: 18
  Feature: Instinct export/import between users
  Source: everything-claude-code
  What we lack: No way to share learned patterns across team members.
  ---
  What we already have that they DON'T

  Worth noting — our tool has features neither repo offers:
  Feature: Code index with symbol table + dependency graph + embeddings
  Details: Neither repo has AST-based code intelligence. They rely on grep/read_file. Our find_callers, impact_analysis,
    predict_breakage tools are unique.
  ────────────────────────────────────────
  Feature: Post-edit verification gate with repair loop
  Details: Our verifier checks syntax, imports, and caller compatibility, then auto-generates a repair prompt. GSD verifies at the
    requirement level but doesn't do static analysis.
  ────────────────────────────────────────
  Feature: Circuit breaker + rate limiter
  Details: Neither repo has resilience primitives for LLM API calls.
  ────────────────────────────────────────
  Feature: Execution tracing (APO-compatible)
  Details: Our span-based tracing with reward signals is designed for future RL training. Neither repo captures this.
  ────────────────────────────────────────
  Feature: GCC (Git Context Controller)
  Details: Structured versioned memory with branch/merge semantics for reasoning.
  ────────────────────────────────────────
  Feature: Multi-provider LLM support
  Details: We support OpenAI, Anthropic, Gemini, Bedrock, and Azure. Both other repos are Claude Code-only.
  ---
  Recommended implementation order

  If I were to prioritize what to build next:

  1. Deviation rules (#4) — Cheapest to implement, biggest impact on turn waste
  2. Goal-backward verification (#2) — Extends our existing verifier
  3. Multi-agent orchestration (#6) — Unlocks reviewer/security agents
  4. Wave-based parallel execution (#1) — Biggest architectural change but highest payoff for large tasks
  5. Pre/post tool hooks (#7) — Extensibility that compounds over time
  6. Discuss phase (#3) — Simple to add as a pre-agent step