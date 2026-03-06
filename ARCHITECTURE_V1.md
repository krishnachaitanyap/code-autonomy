# OSS-v1: Architecting a Billion-Dollar Autonomous Engineering Platform

> **Thesis:** The $34B AI coding tools market in 2026 will support multiple billion-dollar
> companies. Cursor proved it ($1B ARR in 24 months) by owning the **interactive coding**
> experience. The unclaimed throne is **autonomous software delivery** — an AI-native SDLC
> platform that doesn't assist developers but *replaces entire workflows*. That's what we build.

---

## Table of Contents

1. [Market Reality](#1-market-reality)
2. [The Billion-Dollar Insight](#2-the-billion-dollar-insight)
3. [Product Vision](#3-product-vision)
4. [Platform Architecture](#4-platform-architecture)
5. [The Moat — 5 Layers Deep](#5-the-moat--5-layers-deep)
6. [Product Surface Areas](#6-product-surface-areas)
7. [Go-to-Market Strategy](#7-go-to-market-strategy)
8. [Business Model](#8-business-model)
9. [What We Must Build (and in What Order)](#9-what-we-must-build-and-in-what-order)
10. [Team & Hiring](#10-team--hiring)
11. [Fundraising Narrative](#11-fundraising-narrative)
12. [Risk Matrix](#12-risk-matrix)
13. [90-Day Sprint Plan](#13-90-day-sprint-plan)

---

## 1. Market Reality

### The Numbers

| Metric | Value | Source |
|--------|-------|--------|
| AI Code Tools market (2026) | $34.58B | Research & Markets |
| Projected market (2032) | $37.34B+ | SNS Insider |
| Cursor ARR (Nov 2025) | $1B+ | Sacra |
| Cursor valuation | $29.3B | Series D |
| OpenHands funding | $18.8M | Seed |
| Entire (ex-GitHub CEO) | $60M seed / $300M val | SiliconANGLE |
| Global developers | ~30M | a16z |
| Dev economic output | $3T/year | a16z |
| AI productivity multiplier | 2x minimum | a16z |

### Who's Winning and Why

| Company | Why they're winning | Revenue model |
|---------|-------------------|---------------|
| **Cursor** | Owned the IDE. Every keystroke goes through them. | $20/mo Pro, $40/mo Business |
| **GitHub Copilot** | Distribution. 150M+ devs already on GitHub. | $10-39/mo, enterprise contracts |
| **Claude Code** | Best reasoning model + terminal UX. | Usage-based via API |
| **OpenClaw** | 180K stars. Viral. General-purpose agent. | Open-source (no revenue yet) |

### What Nobody Has Built Yet

Every tool above is either:
- **Interactive** (Cursor, Copilot, Claude Code) — a human sits there and types
- **General-purpose** (OpenClaw) — broad but shallow on coding
- **Research** (SWE-Agent) — great benchmarks, not production-ready

**Nobody has built the autonomous engineering platform that enterprises can deploy
to handle their entire SDLC — from ticket to production — with zero human-in-the-loop
for routine work.** That's the trillion-dollar gap (a16z's words, not ours).

---

## 2. The Billion-Dollar Insight

### The Shift Happening Now

```
2023: AI helps you write code faster        (Copilot autocomplete)
2024: AI writes code for you                (Cursor Composer, Claude Code)
2025: AI handles coding tasks autonomously  (Copilot Coding Agent, Codex)
2026: AI manages software delivery          ← WE ARE HERE. NOBODY OWNS THIS.
2027: AI-native software factories          ← WHERE WE'RE GOING
```

### The Insight

**Developers don't want a faster IDE. Engineering leaders want fewer tickets in the backlog.**

The buyer isn't the developer — it's the VP of Engineering who has:
- 500 open Jira tickets
- 3-month sprint backlog
- 40% of eng time spent on maintenance/bugs
- Hiring freeze but growing feature demands

**Our product:** "Point it at your backlog. It closes tickets."

### Why Us

We have the only open-source codebase with **deep code intelligence** (AST symbol table,
call graph, dependency graph, semantic embeddings, impact analysis, breakage prediction).
Every other tool does `grep` + `read_file`. We understand code the way a senior engineer does.

This is the foundation everything else gets built on. Without code intelligence, autonomous
agents make changes that break things in unexpected places. With it, they don't.

---

## 3. Product Vision

### One-Liner

**The autonomous software engineering platform that turns tickets into tested, reviewed,
production-ready pull requests.**

### Three Products, One Platform

```
┌─────────────────────────────────────────────────────────────────────┐
│                    CODE-AUTONOMY PLATFORM                          │
├─────────────────────┬─────────────────────┬─────────────────────────┤
│                     │                     │                         │
│   OSS Engine        │   Cloud Platform    │   Enterprise            │
│   (Open-Source)     │   (SaaS)            │   (Self-Hosted)         │
│                     │                     │                         │
│  - Agent core       │  - Hosted agents    │  - On-prem deployment   │
│  - Code index       │  - Dashboard UI     │  - SSO / SAML          │
│  - MCP servers      │  - GitHub App       │  - Audit logs          │
│  - CLI tool         │  - Slack bot        │  - SOC 2 / HIPAA       │
│  - Plugin SDK       │  - Usage analytics  │  - Air-gapped mode     │
│                     │  - Team management  │  - Custom models       │
│  FREE               │  $49/dev/mo         │  $199/dev/mo           │
│                     │                     │  (min 50 seats)        │
└─────────────────────┴─────────────────────┴─────────────────────────┘
```

---

## 4. Platform Architecture

### System Architecture

```
                          ┌──────────────────────┐
                          │    TRIGGER LAYER      │
                          │  GitHub Webhooks      │
                          │  Jira Webhooks        │
                          │  Slack Commands        │
                          │  Sentry Alerts        │
                          │  Cron / Scheduler     │
                          │  CLI / API            │
                          └──────────┬─────────────┘
                                     │
                          ┌──────────▼─────────────┐
                          │   ORCHESTRATOR          │
                          │                         │
                          │  Task Queue (Redis)     │
                          │  Agent Pool Manager     │
                          │  Budget Controller      │
                          │  State Machine          │
                          └──────────┬──────────────┘
                                     │
              ┌──────────────────────┼──────────────────────┐
              │                      │                      │
    ┌─────────▼────────┐  ┌─────────▼────────┐  ┌─────────▼────────┐
    │  RESEARCHER       │  │  PLANNER          │  │  IMPLEMENTER     │
    │  Agent            │  │  Agent            │  │  Agent           │
    │                   │  │                   │  │                  │
    │  - Explore code   │  │  - Decompose task │  │  - Write code    │
    │  - Read docs      │  │  - Design changes │  │  - Run tests     │
    │  - Analyze impact │  │  - Risk assess    │  │  - Fix failures  │
    │  - Find patterns  │  │  - Create plan    │  │  - Commit        │
    └─────────┬─────────┘  └─────────┬─────────┘  └─────────┬────────┘
              │                      │                      │
              └──────────────────────┼──────────────────────┘
                                     │
              ┌──────────────────────┼──────────────────────┐
              │                      │                      │
    ┌─────────▼────────┐  ┌─────────▼────────┐  ┌─────────▼────────┐
    │  VERIFIER         │  │  REVIEWER         │  │  SECURITY        │
    │  Agent            │  │  Agent            │  │  Agent           │
    │                   │  │                   │  │                  │
    │  - Goal-backward  │  │  - Code quality   │  │  - OWASP scan    │
    │  - Req coverage   │  │  - Style check    │  │  - Secret detect │
    │  - Test coverage  │  │  - Best practices │  │  - Vuln analysis │
    │  - Impact verify  │  │  - PR description │  │  - Dep audit     │
    └──────────────────┘  └──────────────────┘  └──────────────────┘
                                     │
                          ┌──────────▼──────────────┐
                          │   CODE INTELLIGENCE      │
                          │   (Our Moat)             │
                          │                          │
                          │  Symbol Table            │
                          │  Call Graph              │
                          │  Dependency Graph        │
                          │  Semantic Embeddings     │
                          │  Impact Analysis         │
                          │  Breakage Prediction     │
                          │  Pattern Memory          │
                          └──────────┬───────────────┘
                                     │
                          ┌──────────▼───────────────┐
                          │   EXECUTION LAYER         │
                          │                           │
                          │  Docker Sandbox           │
                          │  Git Operations           │
                          │  Test Runner              │
                          │  Build System             │
                          │  PR Creation              │
                          └───────────────────────────┘
```

### Data Flow: Ticket → Production-Ready PR

```
1. TRIGGER:   Jira ticket "PROJ-1234" assigned to bot
                    │
2. DISCUSS:   Agent asks clarifying questions via Jira comment
              (or auto-proceeds if requirements are clear)
                    │
3. RESEARCH:  Researcher agent explores codebase using code index
              Produces: affected_files, patterns, risks, context
                    │
4. PLAN:      Planner agent creates implementation plan
              Plan reviewed against deviation rules
              Optional: human approval gate
                    │
5. IMPLEMENT: Implementer agent writes code in Docker sandbox
              Each file change: edit → verify → test → commit
              Atomic commits per logical unit
                    │
6. VERIFY:    Verifier checks each requirement bullet
              Distrusts agent self-report
              Runs: syntax, imports, callers, tests, coverage
                    │
7. REVIEW:    Reviewer agent checks quality, style, patterns
              Security agent scans for vulnerabilities
                    │
8. DELIVER:   PR created with:
              - Linked ticket
              - Implementation summary
              - Test results
              - Security scan results
              - Confidence score
              - "Ready for human review" or "Needs attention"
                    │
9. LEARN:     Outcome (merged/rejected/modified) fed back
              Updates pattern memory for future tasks
```

---

## 5. The Moat — 5 Layers Deep

### Layer 1: Code Intelligence (HAVE TODAY)

```
Us:     AST parser → Symbol table → Call graph → Embeddings → Impact analysis
Others: grep + read_file
```

This is 6-12 months of work that nobody else has done. It powers:
- `find_callers` — who calls this function?
- `impact_analysis` — what breaks if I change this?
- `predict_breakage` — risk score before any edit
- `context_for_edit` — Graph-RAG context for the LLM
- `find_similar` — semantic code search

**Why it matters:** Without this, autonomous agents break things. With it, they don't.

### Layer 2: Verification Pipeline (HAVE TODAY)

```
Edit → Syntax check → Import check → Caller check → Test run → Repair loop
```

Our post-edit verifier catches issues *before* committing. Others commit first,
then find out tests fail.

### Layer 3: Multi-Agent Orchestration (BUILD IN 90 DAYS)

```
Single LLM call  →  DAG of specialized agents with handoff documents
```

Not just "run 3 agents in parallel" — a real pipeline where each agent has a
specific role, specific tools, and specific success criteria.

### Layer 4: Event-Driven Autonomy (BUILD IN 90 DAYS)

```
Manual CLI invocation  →  Webhooks, cron, alert-triggered execution
```

The platform watches your repo, your issue tracker, your error monitoring.
When something happens, it acts.

### Layer 5: Learning Loop (BUILD IN 6 MONTHS)

```
Static system prompt  →  Evolving behavioral rules from outcomes
```

Every PR that gets merged teaches the system what works. Every rejection teaches
what doesn't. Over time, the system gets better at *your* codebase.

**Combined moat:** Code intelligence + verification + orchestration + autonomy + learning.
Any competitor would need to replicate all 5 layers. That's 18+ months of work.

---

## 6. Product Surface Areas

### 6.1 GitHub App (PRIMARY DISTRIBUTION)

```
Install on repo → Assign issues to @code-autonomy → Get PRs back
```

This is the primary product. It works like GitHub Copilot Coding Agent but with:
- Deep code intelligence (not just grep)
- Multi-agent pipeline (not single-agent)
- Verification gate (not just "tests pass")
- Works with any LLM (not locked to one provider)

**User flow:**
1. Install GitHub App on repository
2. Label an issue with `code-autonomy` or assign to bot
3. Agent researches, plans, implements, verifies
4. PR appears with full context, test results, confidence score
5. Human reviews and merges (or requests changes)
6. System learns from the outcome

### 6.2 Slack/Teams Bot (ENTERPRISE INTERFACE)

```
@autonomy fix the auth timeout bug in user-service
@autonomy what would break if we upgrade Spring Boot to 3.4?
@autonomy implement PROJ-1234
```

Enterprise teams live in Slack. The bot:
- Accepts tasks via natural language
- Reports progress in threads
- Asks clarifying questions
- Delivers PR links when done
- Streams activity logs

### 6.3 Web Dashboard (MANAGEMENT LAYER)

```
┌─────────────────────────────────────────────────────────────┐
│  CODE-AUTONOMY DASHBOARD                                     │
├──────────────┬──────────────┬───────────────┬────────────────┤
│  Active Runs │  Queue       │  Analytics    │  Settings      │
│  ──────────  │  ──────────  │  ─────────── │  ──────────    │
│  3 running   │  12 pending  │  This week:   │  Models        │
│  PROJ-1234   │  PROJ-1240   │  47 PRs       │  Repos         │
│  ├─ Research │  PROJ-1241   │  89% merged   │  Team          │
│  PROJ-1237   │  PROJ-1242   │  $2.3K LLM    │  Budgets       │
│  ├─ Testing  │  ...         │  342 tickets  │  Policies      │
│  PROJ-1239   │              │  closed       │  Webhooks      │
│  ├─ Review   │              │               │  Audit log     │
└──────────────┴──────────────┴───────────────┴────────────────┘
```

### 6.4 MCP Server (ECOSYSTEM PLAY)

Expose our code intelligence as MCP tools that any client can consume:

```json
{
  "tools": [
    "code-autonomy/find_callers",
    "code-autonomy/impact_analysis",
    "code-autonomy/predict_breakage",
    "code-autonomy/find_similar",
    "code-autonomy/context_for_edit",
    "code-autonomy/describe_entity"
  ]
}
```

This means Claude Code, OpenClaw, Cursor, and every MCP-compatible tool can use
our code intelligence. We become infrastructure.

### 6.5 CLI (DEVELOPER EXPERIENCE)

Keep and enhance the current CLI for power users:

```bash
# Current (keep these)
autonomy agent --repo-path . --requirement "Add retry logic to API client"
autonomy plan --repo-path . --requirement "Migrate to async/await"
autonomy ask --repo-path . --question "How does auth work?"

# New
autonomy serve                      # Start as MCP server
autonomy watch                      # Event-driven mode (watch for triggers)
autonomy dashboard                  # Launch local web UI
autonomy install github-app         # Setup GitHub App integration
autonomy install slack-bot          # Setup Slack bot
```

---

## 7. Go-to-Market Strategy

### Phase 1: Open-Source Traction (Months 1-3)

**Goal:** 10K GitHub stars, 500 weekly active CLI users

| Action | Details |
|--------|---------|
| Open-source the core engine | Agent loop, code index, tools, CLI — Apache 2.0 |
| MCP server release | Let Claude Code / OpenClaw users consume our code intelligence |
| Launch on Hacker News | "We built AST-level code intelligence for AI agents" |
| Developer content | Blog posts: "Why grep isn't enough for AI agents", "How we predict breakage" |
| Community | Discord server, GitHub Discussions, contributor guide |
| Benchmarks | Run on SWE-Bench, publish results vs OpenHands / SWE-Agent |

**Why open-source first:** Cursor proved that developer adoption is bottom-up.
Open-source creates trust, contributions, and distribution that no marketing budget can buy.

### Phase 2: GitHub App Launch (Months 3-6)

**Goal:** 200 repos installed, 50 paying teams

| Action | Details |
|--------|---------|
| GitHub App (free tier) | 10 tasks/month free, install in < 2 minutes |
| "Assign issue to bot" workflow | The killer feature: label an issue, get a PR |
| Cloud-hosted agents | No setup required — we run the agents |
| Usage-based pricing | $0.50/task for Pro, $1.50/task for Enterprise |
| Content: case studies | "How Team X closed 40 tickets in one week" |
| Integrations | Jira, Linear, Sentry webhook triggers |

### Phase 3: Enterprise (Months 6-12)

**Goal:** 10 enterprise contracts, $2M ARR

| Action | Details |
|--------|---------|
| Self-hosted deployment | Helm chart, Docker Compose, air-gapped mode |
| SSO / SAML / SCIM | Table stakes for enterprise |
| SOC 2 Type II | Start audit at month 4, complete by month 8 |
| Audit logging | Every agent action logged, queryable, exportable |
| Policy engine | "Never auto-merge", "require human review for security-critical files" |
| Custom model support | Bring-your-own LLM (Azure OpenAI, Bedrock, on-prem) |
| Enterprise sales team | Hire 2 AEs, target VP Eng at 200-2000 person companies |

### Phase 4: Platform (Months 12-18)

**Goal:** Ecosystem, $20M ARR

| Action | Details |
|--------|---------|
| Plugin marketplace | Community-built agents, tools, integrations |
| Learning engine GA | Cross-repo pattern learning, team-specific tuning |
| Multi-repo orchestration | "Update this library across all 30 microservices" |
| AI-native CI/CD | Agent manages the entire pipeline, not just code |
| Partner program | SI partners (Accenture, Deloitte, Infosys) |

---

## 8. Business Model

### Revenue Streams

```
                        Revenue Projections (Conservative)
Year 1                  Year 2                  Year 3
──────────              ──────────              ──────────
OSS: $0                 OSS: $0                 OSS: $0
Cloud: $500K            Cloud: $8M              Cloud: $40M
Enterprise: $1.5M       Enterprise: $15M        Enterprise: $80M
────────────            ────────────            ────────────
Total: $2M              Total: $23M             Total: $120M
```

### Pricing

| Tier | Price | Includes |
|------|-------|----------|
| **Community (OSS)** | Free | CLI, code index, MCP server, single-agent, BYOK |
| **Pro (Cloud)** | $49/dev/mo | GitHub App, Slack bot, dashboard, 100 tasks/mo, multi-agent |
| **Team** | $99/dev/mo | Unlimited tasks, priority queue, learning engine, analytics |
| **Enterprise** | $199/dev/mo (min 50) | Self-hosted, SSO, audit, SOC 2, custom models, SLA |

### Unit Economics

| Metric | Value | Notes |
|--------|-------|-------|
| LLM cost per task | $0.30-2.00 | Depends on complexity, model used |
| Avg revenue per task | $1.50 | Blended across tiers |
| Gross margin | 60-70% | After LLM + compute costs |
| CAC (developer) | ~$0 | Open-source, word-of-mouth |
| CAC (enterprise) | $15-25K | Sales-led, 6-month cycle |
| LTV (Pro) | $1,200 | 24-month avg retention |
| LTV (Enterprise) | $120K | Per seat, 50+ seats, 36-month |

### Path to $1B ARR

```
$1B ARR requires ONE of:
  - 850K Pro subscribers at $99/mo
  - 42K Enterprise seats at $199/mo across 200 companies
  - Mix: 200K Pro + 30K Enterprise seats

Cursor got to $1B in 24 months with 360K paying users.
Our TAM is the same 30M developers. We need 1-3% penetration.
```

---

## 9. What We Must Build (and in What Order)

### MUST HAVE for Launch (Weeks 1-12)

| # | Feature | Why it's blocking | Effort |
|---|---------|-------------------|--------|
| 1 | **Docker sandbox** | Can't run untrusted code on host. Table-stakes security. | 2 weeks |
| 2 | **Multi-agent orchestration** | Single agent can't handle complex tasks reliably. | 3 weeks |
| 3 | **Event triggers (webhooks)** | Without this we're just a CLI tool. Need "assign issue → get PR". | 2 weeks |
| 4 | **GitHub App** | Primary distribution channel. Install in 2 clicks. | 3 weeks |
| 5 | **Web dashboard (basic)** | Need visibility into running agents, queue, results. | 2 weeks |
| 6 | **MCP server** | Expose code intelligence to ecosystem. Network effects. | 1 week |
| 7 | **Goal-backward verification** | Autonomous agents must prove they completed the task. | 1 week |
| 8 | **Deviation rules** | Prevent agent from spiraling. Already designed. | 3 days |

### MUST HAVE for Enterprise (Weeks 12-24)

| # | Feature | Why | Effort |
|---|---------|-----|--------|
| 9 | SSO / SAML | Enterprise won't buy without it | 2 weeks |
| 10 | Audit logging | Compliance requirement | 1 week |
| 11 | Policy engine | "Never push to main", "require review for X" | 2 weeks |
| 12 | Self-hosted deployment | Helm chart + Docker Compose | 2 weeks |
| 13 | Slack/Teams bot | Enterprise interface | 2 weeks |
| 14 | Usage analytics & billing | Need to charge money | 2 weeks |
| 15 | Learning engine v1 | Key differentiator: gets better over time | 3 weeks |

### NICE TO HAVE (Weeks 24+)

| # | Feature | Why |
|---|---------|-----|
| 16 | Plugin/skills marketplace | Ecosystem play |
| 17 | Multi-repo orchestration | Enterprise unlock |
| 18 | VS Code extension | Developer convenience |
| 19 | Jira/Linear native integration | Enterprise workflow |
| 20 | Custom model fine-tuning | Enterprise differentiation |

---

## 10. Team & Hiring

### Founding Team (4-6 people)

| Role | Focus | Why critical |
|------|-------|-------------|
| **CEO / Product** | Vision, GTM, fundraising | Someone has to sell it |
| **CTO / Infra** | Platform, scaling, Docker, orchestration | The hard engineering |
| **Lead Agent Engineer** | Agent loop, multi-agent, LLM integration | Core product |
| **Code Intelligence Lead** | AST, graphs, embeddings, MCP server | Our moat |
| **Full-stack Engineer** | Dashboard, GitHub App, Slack bot | Surface area |
| **DevRel / Community** | Open-source, content, developer adoption | Distribution |

### First 10 Hires (After Seed)

| Role | When |
|------|------|
| 2 Agent Engineers | Month 3 |
| 1 Security Engineer | Month 4 (SOC 2, sandbox hardening) |
| 2 Enterprise AEs | Month 6 |
| 1 Solutions Engineer | Month 6 |
| 1 Designer | Month 4 (dashboard, landing page) |

---

## 11. Fundraising Narrative

### The Pitch (30 seconds)

> "Cursor is a $29B company because they made developers 2x faster.
> We make engineering teams 10x more productive by autonomously closing tickets.
> We have the only open-source code intelligence engine — AST-level understanding
> of codebases — that makes autonomous agents actually reliable.
> We're building the platform that turns your Jira backlog into merged PRs."

### Seed Round

| Metric | Target |
|--------|--------|
| Raise | $5-8M |
| Valuation | $30-50M |
| Use of funds | 12-18 months runway, team of 8 |
| Key milestones | Open-source launch (10K stars), GitHub App (200 repos), 10 design partners |

### Series A (Month 12-15)

| Metric | Target |
|--------|--------|
| Raise | $20-30M |
| Valuation | $150-250M |
| Trigger | $2M ARR, 10 enterprise customers, 50K GitHub stars |
| Use of funds | Enterprise sales, SOC 2, scale engineering |

### Comparable Valuations

| Company | Stage | Valuation | Revenue | Multiple |
|---------|-------|-----------|---------|----------|
| Cursor (Anysphere) | Series D | $29.3B | $1B ARR | 29x |
| Entire | Seed | $300M | Pre-revenue | — |
| OpenHands | Seed | ~$100M est | Pre-revenue | — |
| Devin (Cognition) | Series B | $2B | ~$10M ARR | 200x |

The market is paying 30-200x revenue multiples for AI coding companies.
Even conservative 20x on $2M ARR = $40M valuation at Series A.

---

## 12. Risk Matrix

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| **LLM costs eat margins** | High | High | Multi-model routing (cheap for exploration, expensive for writing). Budget controls. Model profiles. |
| **Agents produce bad code** | Medium | Critical | Verification pipeline (our moat). Goal-backward checking. Human approval gates. Confidence scoring. |
| **Security incident** | Medium | Critical | Docker sandbox from day 1. Secret scanning. SOC 2 early. Bug bounty program. |
| **Big tech clones us** | High | Medium | Speed + community + code intelligence moat. Open-source creates switching costs (contributions, customizations). |
| **Enterprise sales cycle too long** | High | Medium | Product-led growth via GitHub App. Bottom-up adoption. Free tier creates urgency when usage spikes. |
| **Open-source contributors don't come** | Medium | Medium | DevRel from day 1. Good docs. Easy contributor experience. Bounty program for high-value features. |
| **Model capabilities plateau** | Low | High | Architecture is model-agnostic. Better code intelligence compensates for weaker models. |

---

## 13. 90-Day Sprint Plan

### Days 1-30: Foundation

```
Week 1:  Docker sandbox execution environment
         ├─ Dockerized agent runner (mount repo, network isolation)
         ├─ Secure command execution inside container
         └─ Test: agent runs full cycle in sandbox

Week 2:  MCP server for code intelligence
         ├─ Expose find_callers, impact_analysis, predict_breakage as MCP tools
         ├─ MCP transport (stdio + HTTP)
         └─ Test: Claude Code consumes our MCP server

Week 3:  Multi-agent orchestration (core)
         ├─ Agent definition format (YAML frontmatter + system prompt)
         ├─ DAG executor (sequential + parallel phases)
         ├─ Handoff document protocol between agents
         └─ Test: researcher → planner → implementer pipeline

Week 4:  Agent loop hardening
         ├─ Deviation rules (from roadmap_existing_git_repos.md Sprint 1)
         ├─ Goal-backward verification
         ├─ Atomic commits per task
         └─ Test: agent respects deviation rules, verifier catches incomplete work
```

### Days 31-60: Product

```
Week 5:  Event trigger system
         ├─ Webhook receiver (FastAPI)
         ├─ GitHub webhook handler (issue assigned, issue labeled)
         ├─ Task queue (Redis / in-memory for OSS)
         └─ Test: assign issue → agent starts

Week 6:  GitHub App
         ├─ OAuth App registration
         ├─ Installation webhook handler
         ├─ Issue → agent → PR pipeline
         └─ Test: install on test repo, assign issue, get PR

Week 7:  Web dashboard (v1)
         ├─ FastAPI backend + React frontend
         ├─ Active runs, queue, results views
         ├─ Real-time agent log streaming
         └─ Test: watch agent work in browser

Week 8:  Slack bot (v1)
         ├─ Slack App with slash commands
         ├─ Thread-based progress reporting
         ├─ Clarification questions in-thread
         └─ Test: /autonomy fix bug → PR link in thread
```

### Days 61-90: Launch

```
Week 9:  Open-source preparation
         ├─ Clean up repo, docs, README, CONTRIBUTING.md
         ├─ Apache 2.0 license (core), BSL (enterprise features)
         ├─ GitHub Actions CI/CD
         └─ Docker Hub image

Week 10: Launch preparation
         ├─ Landing page (codecautonomy.dev or similar)
         ├─ Blog post: "Why we built code intelligence for AI agents"
         ├─ Demo video: "From Jira ticket to merged PR in 5 minutes"
         └─ SWE-Bench benchmark results

Week 11: Launch
         ├─ Hacker News Show HN
         ├─ Twitter/X launch thread
         ├─ Reddit r/programming, r/MachineLearning
         ├─ Discord server open
         └─ Product Hunt launch

Week 12: Post-launch
         ├─ Triage community feedback
         ├─ Fix top 10 reported issues
         ├─ Onboard 5 design partner companies
         └─ Begin enterprise feature development
```

---

## Summary: Why This Wins

| Question | Answer |
|----------|--------|
| **Why now?** | LLMs just got good enough for autonomous coding. The market shifted from "assist" to "autonomy" in 2025-2026. First-mover in autonomous SDLC platform. |
| **Why us?** | Only open-source tool with AST-level code intelligence. 6-12 month moat. Already have working agent loop, verification pipeline, multi-provider support. |
| **Why open-source?** | Distribution. Trust. Contributions. Cursor proved bottom-up works. OpenClaw proved open-source creates viral adoption. Enterprise buys from trusted open-source. |
| **What's the wedge?** | GitHub App: "Assign issue to bot, get PR back." Zero setup. Instant value. |
| **What's the platform?** | Code intelligence as infrastructure (MCP). Multi-agent orchestration. Event-driven autonomy. Learning loop. Plugin ecosystem. |
| **What's the exit?** | $1B+ revenue company or acquisition by GitHub/Microsoft, Atlassian, JetBrains, or cloud provider. |

---

*This is not a roadmap of features. This is an architecture for a company.*

Sources:
- [AI Code Tools Market — Research & Markets](https://www.researchandmarkets.com/report/ai-code-tools)
- [AI Code Tools Market to Hit $37.34B — Yahoo Finance](https://finance.yahoo.com/news/ai-code-tools-market-hit-133000576.html)
- [Cursor Hit $1B ARR — SaaStr](https://www.saastr.com/cursor-hit-1b-arr-in-17-months-the-fastest-b2b-to-scale-ever-and-its-not-even-close/)
- [Cursor Revenue & Valuation — Sacra](https://sacra.com/c/cursor/)
- [The Trillion Dollar AI Dev Stack — a16z](https://a16z.com/the-trillion-dollar-ai-software-development-stack/)
- [Entire Raises $60M — SiliconANGLE](https://siliconangle.com/2026/02/10/entire-launches-60m-build-ai-focused-code-management-platform/)
- [Agentic SDLC — PwC](https://www.pwc.com/m1/en/publications/2026/docs/future-of-solutions-dev-and-delivery-in-the-rise-of-gen-ai.pdf)
- [2026: AI-Native Software Engineering — Xebia](https://xebia.com/news/2026-the-year-software-engineering-will-become-ai-native/)
- [OpenHands vs SWE-Agent — LocalAIMaster](https://localaimaster.com/blog/openhands-vs-swe-agent)
- [Open Source Monetization — Reo.dev](https://www.reo.dev/blog/monetize-open-source-software)
- [OpenClaw GitHub](https://github.com/openclaw/openclaw)
