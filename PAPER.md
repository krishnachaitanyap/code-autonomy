# Code Autonomy: An Architecture for LLM-Driven Autonomous Software Engineering

**White Paper v1.0 — February 2026**

---

## Abstract

Code Autonomy is an autonomous software engineering system that leverages large language models (LLMs) to analyze, plan, and implement code changes across entire repositories. The system addresses the fundamental challenge of enabling an LLM agent to navigate, understand, and modify codebases of arbitrary scale — including repositories with 18,000+ files — within the finite context window of current language models. This paper describes the system's multi-layered architecture: a **project consciousness** module for lightweight repository understanding, a **code index** providing precision graph-based intelligence, a **tool-driven agent loop** for iterative code modification, and **resiliency primitives** ensuring reliable operation against external API failures. We detail key design decisions including single-pass parallel file scanning, AST-based symbol extraction, import-resolved dependency graphs, semantic entity embeddings, and adaptive context management. The system achieves sub-second query times over in-memory indexes while maintaining backward compatibility across all components.

---

## 1. Introduction

### 1.1 Problem Statement

Modern software repositories present a scale challenge for LLM-based code generation. A typical enterprise codebase contains thousands of files, tens of thousands of symbols, and complex cross-file dependency chains. LLMs, despite context windows reaching 200K tokens (Anthropic Claude) or 1M tokens (Google Gemini), cannot ingest an entire repository. The agent must selectively discover, read, and modify only the relevant subset of files — a task requiring deep structural understanding of the codebase.

Prior approaches fall into two categories: (1) **retrieval-augmented generation** (RAG), which embeds code chunks and retrieves by similarity, and (2) **agentic tool-use**, where the LLM iteratively reads and modifies files via function calls. Both have limitations: RAG lacks structural awareness (it cannot answer "who calls this function?"), while naive agentic approaches waste LLM turns on exploration, often exhausting their turn budget before completing the task.

### 1.2 Contribution

Code Autonomy introduces a **hybrid architecture** that combines:

1. **Structural code intelligence** — AST-parsed symbol tables, import-resolved dependency graphs, and class hierarchies that answer relational queries in O(1) time
2. **Semantic search** — per-entity embeddings enabling "find similar code" queries
3. **Adaptive context management** — token-budget-aware rendering and progressive compression
4. **Parallel indexing** — `ThreadPoolExecutor`-based file scanning that reads and parses 18K files in a single pass

The system exposes these capabilities as **7 specialized tools** that the LLM agent calls on demand, keeping the context window focused on the task at hand rather than flooding it with the full codebase.

### 1.3 System Overview

```
                    ┌──────────────────────────────────┐
                    │         User Requirement          │
                    └──────────────┬───────────────────┘
                                   │
                    ┌──────────────▼───────────────────┐
                    │     Smart Initial Context         │
                    │  (identifier extraction + grep)   │
                    │  src/agent/context.py:200-270     │
                    └──────────────┬───────────────────┘
                                   │
          ┌────────────────────────▼────────────────────────┐
          │              Agent Loop (max 50 turns)          │
          │           src/agent/analyzer.py:448-714         │
          │                                                 │
          │  ┌─────────┐  ┌─────────┐  ┌────────────────┐  │
          │  │  Read    │  │  Write  │  │  Code Index    │  │
          │  │  Tools   │  │  Tools  │  │  Tools (×7)    │  │
          │  └────┬────┘  └────┬────┘  └───────┬────────┘  │
          │       │            │               │            │
          │       ▼            ▼               ▼            │
          │   Disk I/O     Disk I/O     In-Memory Index     │
          └─────────────────────────────────────────────────┘
                                   │
                    ┌──────────────▼───────────────────┐
                    │    Post-Edit Verification Gate    │
                    │  src/code_index/verifier.py:83    │
                    └──────────────────────────────────┘
```

**Figure 1.** High-level data flow from user requirement through agent execution to verification.

---

## 2. Architecture

### 2.1 Component Overview

The system comprises six major subsystems, each implemented as a self-contained Python module:

| Subsystem | Location | Purpose | Lines of Code |
|-----------|----------|---------|---------------|
| Project Consciousness | `src/consciousness/core.py` | Lightweight repository overview | ~800 |
| Code Index | `src/code_index/` (10 files) | Precision graph-based intelligence | ~2,300 |
| Agent Loop | `src/agent/analyzer.py` | LLM-driven iterative execution | ~1,100 |
| Tool System | `src/agent/tools.py` | File I/O + code intelligence tools | ~700 |
| Context Management | `src/agent/context.py` | Token-aware compression | ~270 |
| Resiliency | `src/resiliency.py` + `src/llm_client.py` | Circuit breaker + rate limiting | ~520 |

The total system is approximately **52 Python source files** and **~8,000 lines of code**, excluding tests.

### 2.2 Two-Tier Intelligence Model

A central design principle is the separation of **broad awareness** from **precision queries**:

**Tier 1 — Project Consciousness** provides a compact overview (~15K tokens) injected into the agent's initial prompt. It includes the directory tree, detected conventions (language, build tool, test framework), scored code samples, and top function/class signatures [`src/consciousness/core.py:373-395`]. This gives the agent enough context to formulate a plan without consuming its turn budget on exploration.

**Tier 2 — Code Index** provides precision on-demand intelligence via 7 specialized tools. The agent queries the in-memory index during execution: "Who calls `authenticate()`?", "What files import `src/auth/service.py`?", "What would break if I change this function's signature?" These queries resolve in <10ms against pre-built graph structures [`src/code_index/tools.py:143-170`].

This two-tier model ensures the agent receives **just enough context upfront** to orient itself, then **pulls precise details on demand** as it works — avoiding the common failure mode of context window saturation.

---

## 3. Project Consciousness

### 3.1 Single-Pass Repository Indexing

The consciousness module builds a `ProjectConsciousness` dataclass by walking the repository exactly once via `os.walk()` with in-place directory pruning [`src/consciousness/core.py:66-103`]:

```python
for dirpath, dirnames, filenames in os.walk(repo_path):
    dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
```

Directories such as `.git`, `node_modules`, `__pycache__`, `venv`, and `build` are pruned at the `dirnames` level, preventing descent into irrelevant subtrees [`src/constants.py:12-15`]. During this single walk, the system simultaneously collects:

- **Directory structure** — a recursive tree with depth limiting
- **Convention detection** — language, build tool, test framework inferred from file extensions and marker files (e.g., `pom.xml` → Maven, `pytest.ini` → pytest)
- **Code signatures** — extracted via `ast.parse()` for Python files, falling back to regex patterns for other languages [`src/consciousness/core.py:110-226`]
- **Scored code samples** — files ranked by an informativeness heuristic

### 3.2 Score-Based Code Sampling

Not all files are equally informative. The system scores each file using domain-specific heuristics [`src/consciousness/core.py:262-297`]:

| Criterion | Score Delta | Rationale |
|-----------|-------------|-----------|
| Entry point (main/app) | +20 | High-level architecture |
| Rich file (3+ signatures) | +30 | Core business logic |
| Model/schema file | +10 | Domain understanding |
| Test file | -10 | Lower information density |
| Boilerplate (`__init__`, `setup`) | -15 | Minimal unique content |

The top-N files by score are included as representative samples, ensuring the LLM sees core business logic rather than configuration boilerplate.

### 3.3 Token-Budget-Aware Rendering

The consciousness renders to a context string via `to_context_string()` [`src/consciousness/core.py:399-487`], which progressively trims content in tiers to fit within the model's context limit:

- **Tier 1** (full budget): All sections — structure, signatures, samples
- **Tier 2**: Reduced samples (max 10 files)
- **Tier 3**: Signatures only, no samples
- **Tier 4**: Structure only, reduced depth
- **Fallback**: Header-only (never fails)

This ensures the system degrades gracefully across different LLM context sizes without hard failures.

### 3.4 Git-Aware Incremental Rebuild

For cached consciousness data, the system uses `git log --since=<timestamp>` to identify changed files [`src/consciousness/core.py:641-667`]. If fewer than 30% of files changed, an incremental update is performed [`src/consciousness/core.py:670-744`]:

- **Structure**: Always rebuilt (cheap operation)
- **Signatures**: Only re-extracted for changed files; unchanged files retain cached data
- **Samples**: Re-scored against the combined pool of old and new samples

This reduces rebuild time from ~12s to ~3s for typical small changes on a 2,000-file repository.

---

## 4. Code Index

### 4.1 Architecture Overview

The Code Index is a composite dataclass `CodeIndex` [`src/code_index/storage.py:31-43`] containing five sub-indexes built in a 6-phase pipeline:

```
Phase 0: scan_repo_files()     → file_cache {path: (content, AST)}
Phase 1: build_symbol_table()  → SymbolTable (all functions, classes, methods)
Phase 2: resolve_imports()     → {file: {local_name: target_FQN}}
Phase 3: build_dependency_graph() → DependencyGraph (bidirectional call graph)
Phase 4: build_class_hierarchy()  → ClassHierarchy (parent-child relationships)
Phase 5: EntityEmbeddings.build() → Semantic vectors (optional)
```

### 4.2 Single-Pass Parallel File Scanning

The critical performance innovation is Phase 0: a single `os.walk()` pass that reads and parses all `.py` files using a `ThreadPoolExecutor` with 8 workers [`src/code_index/storage.py:58-94`]:

```python
def scan_repo_files(repo_path: str, max_workers: int = 8)
    -> dict[str, tuple[str, ast.Module | None]]:
```

Each worker executes `_read_and_parse()` [`src/code_index/storage.py:45-55`], which reads file content and calls `ast.parse()`. Files with syntax errors store content but `None` for the AST — downstream stages skip them gracefully.

The cache is a plain `dict[str, tuple[str, ast.Module | None]]` keyed by relative path. This dict is then split into `file_contents` and `file_asts` and passed to all 5 subsequent phases, eliminating redundant disk I/O entirely.

**Before optimization**: 4 full passes over all files (read + parse in each of build_symbol_table, resolve_imports, extract_python_calls, and EntityEmbeddings.build). For a 16K-file repository, this represented ~128 seconds of redundant I/O.

**After optimization**: 1 parallel pass. For the same repository, Phase 0 completes in ~4-6 seconds.

### 4.3 Symbol Table

The `SymbolTable` [`src/code_index/symbol_table.py:42-129`] maintains four hash-map indexes over `SymbolEntry` objects:

```python
_by_fqn:  dict[str, SymbolEntry]        # O(1) FQN lookup
_by_name: dict[str, list[SymbolEntry]]   # O(1) name lookup
_by_file: dict[str, list[SymbolEntry]]   # O(1) file lookup
_by_type: dict[str, list[SymbolEntry]]   # O(1) type lookup
```

Each `SymbolEntry` [`src/code_index/symbol_table.py:23-39`] captures:
- Fully qualified name (FQN): `"src/agent/analyzer.py::generate_changes_with_agent"`
- Symbol type: `function`, `class`, `method`, or `async function`
- Line range: `(line_start, line_end)` for precise source location
- Signature: Full reconstructed signature with decorators and type annotations
- Metadata: Docstring summary, parent class, base classes, parameters, return type

AST extraction [`src/code_index/symbol_table.py:160-261`] walks the parsed tree using `ast.walk()`, extracting classes (with their methods as nested entities) and module-level functions. A deduplication set `_method_locations: set[tuple[int, str]]` prevents methods from being recorded both as class children and as standalone functions.

### 4.4 Import Resolution

The import resolver [`src/code_index/import_resolver.py:46-127`] maps local import names to in-repository FQNs. For each file, it walks only module-level AST nodes (`tree.body`), handling:

- **Absolute imports**: `from src.agent.tools import run_grep` → resolves to `src/agent/tools.py::run_grep`
- **Relative imports**: `from . import utils` → resolved via `_resolve_relative_import()` which navigates the directory hierarchy based on the dot level [`src/code_index/import_resolver.py:28-43`]
- **Module imports**: `import src.agent.tools` → maps to the module file itself

Module paths are converted to file candidates via `_module_to_file_candidates()` [`src/code_index/import_resolver.py:15-25`]: `"src.agent.tools"` → `["src/agent/tools.py", "src/agent/tools/__init__.py"]`. Only in-repository modules are resolved; stdlib and third-party imports are silently skipped.

### 4.5 Dependency Graph

The `DependencyGraph` [`src/code_index/graph_builder.py:16-54`] provides **bidirectional** call graphs at both symbol and file granularity:

```python
forward:         {caller_fqn: {callee_fqns}}     # "who does X call?"
reverse:         {callee_fqn: {caller_fqns}}      # "who calls X?"
file_imports:    {file: {imported_files}}           # "what does this file use?"
file_dependents: {file: {files_importing_it}}       # "what depends on this file?"
```

Construction proceeds in five steps [`src/code_index/graph_builder.py:57-152`]:

1. **Raw call graph extraction** — The `_PythonCallVisitor` AST visitor [`src/context/call_graph/python_extractor.py:48-92`] walks each file's AST, tracking the current function/class scope and recording `(caller, callee)` pairs for every `ast.Call` node.

2. **Import-based callee resolution** — Raw callees are local names (e.g., `run_grep`). The resolver maps these through the import map to FQNs (e.g., `src/agent/tools.py::run_grep`) using a three-step fallback: import map → direct FQN match → same-file lookup [`src/code_index/graph_builder.py:86-119`].

3. **Reverse graph construction** — Inversion of the forward graph in a single pass [`src/code_index/graph_builder.py:121-125`].

4. **File-level maps** — Aggregated from the import map by extracting file paths from FQNs [`src/code_index/graph_builder.py:127-145`].

### 4.6 Class Hierarchy

The `ClassHierarchy` [`src/code_index/hierarchy.py:13-71`] resolves base class names to FQNs using a three-level strategy [`src/code_index/hierarchy.py:113-136`]:

1. **Import map lookup** — The base class name appears in the file's import map
2. **Same-file lookup** — The base class is defined in the same file
3. **Global name lookup** — Exactly one class with that name exists in the repository (disambiguated)

Traversal methods `get_ancestors()` and `get_descendants()` perform BFS with cycle protection (via `visited: set`) and configurable depth limits (default 10) [`src/code_index/hierarchy.py:26-58`].

### 4.7 Entity Embeddings

The `EntityEmbeddings` module [`src/code_index/entity_embeddings.py:24-202`] provides semantic search over all symbols. Each entity is chunked as:

```
signature + docstring_summary + body[:500]
```

Chunks are embedded via OpenAI's `text-embedding-3-small` model (1536 dimensions, $0.02/1M tokens) through LiteLLM, batched at 2048 texts per API call [`src/code_index/entity_embeddings.py:166-202`]. Each chunk is also hashed with SHA-256 (first 16 hex chars) for future incremental re-embedding [`src/code_index/entity_embeddings.py:90`].

Semantic search uses cosine similarity via NumPy:

```python
scores = np.dot(doc_norms, q_norm)
top_indices = np.argsort(scores)[::-1][:top_k]
```

Results below a 0.1 similarity threshold are filtered [`src/code_index/entity_embeddings.py:110-142`].

**Design decision**: Embeddings are best-effort. If no API key is available, the build continues without them — the remaining 6 tools function normally [`src/code_index/storage.py:146-153`].

### 4.8 Caching Strategy

The code index uses a **JSON + Pickle hybrid** cache [`src/code_index/storage.py:108-140`]:

- **Metadata, symbol table, graphs, hierarchy** → JSON (human-readable, debuggable)
- **Embedding vectors** → Pickle (100x smaller than JSON for NumPy arrays)

Cache writes are **atomic**: a temporary file is written first, then renamed via `Path.replace()` to prevent corruption on crash [`src/code_index/storage.py:124-131`].

Cache expiry defaults to 24 hours, configurable via `[code_index] max_age_hours` [`src/config_loader.py:167-170`]. On cache hit, startup time drops from ~70-140s to <1s.

---

## 5. Code Index Tools

The code index exposes **7 specialized tools** to the agent, each designed for a specific query pattern [`src/code_index/tools.py:15-136`]:

### 5.1 Tool Catalog

| Tool | Input | Query Type | Complexity |
|------|-------|------------|------------|
| `find_callers` | symbol name | Reverse graph lookup | O(1) |
| `find_dependents` | file path | File-level reverse map | O(1) |
| `impact_analysis` | file path | Multi-section blast radius | O(symbols) |
| `describe_entity` | symbol name | Full symbol detail | O(1) + O(callers) |
| `find_similar` | natural language query | Cosine similarity search | O(n) |
| `context_for_edit` | file + symbol + intent | Pre-edit context assembly | O(callers + callees) |
| `predict_breakage` | file + changes description | Risk assessment | O(symbols + callers) |

### 5.2 Tool Design Rationale

A key design decision was to provide **7 single-purpose tools** rather than one generic "query the index" tool. LLMs select tools more accurately when each has a clear, narrow description [`src/code_index/tools.py:15-136`]. For example, the agent consistently chooses `find_callers` when it needs to understand who uses a function, rather than formulating a generic graph query.

### 5.3 Key Tool Implementations

**`context_for_edit`** [`src/code_index/tools.py:349-454`] is the most sophisticated tool, assembling an 8-section pre-edit briefing:

1. Symbols in the target file (or filtered by symbol name)
2. All callers (reverse graph)
3. All callees (forward graph)
4. File-level dependents
5. Class hierarchy (parents and children)
6. Related test files (pattern-matched: `test_{module}.py`, `{module}_test.py`)
7. Semantically similar code (if `intent` parameter provided)

This tool eliminates the agent's need to spend 5-10 turns manually exploring dependencies before making an edit.

**`predict_breakage`** [`src/code_index/tools.py:457-559`] performs risk analysis with a three-tier classification:

- **HIGH**: >5 callers or has child classes that may override
- **MEDIUM**: 1-5 callers
- **LOW**: No external callers

It additionally warns about child class interface breakage [`src/code_index/tools.py:475-482`] and flags missing test coverage.

### 5.4 Tool Registration and Dispatch

Tools are **conditionally added** to the agent's tool list only when a code index is available [`src/agent/tools.py:481-494`]:

```python
if code_index is not None:
    from src.code_index import CODE_INDEX_TOOLS
    tools.extend(CODE_INDEX_TOOLS)
```

Dispatch uses a simple if-else router [`src/code_index/tools.py:143-170`] for debuggability over dict-based or dynamic routing.

---

## 6. Agent Loop

### 6.1 Three Execution Modes

The system supports three modes, each with tailored tool sets and turn budgets [`src/agent/analyzer.py`]:

| Mode | Function | Max Turns | Tools | Purpose |
|------|----------|-----------|-------|---------|
| Agent | `generate_changes_with_agent()` | 50 | Read + Write + Exec + Memory + Code Index | Full implementation |
| Plan | `generate_plan_with_agent()` | 30 | Read + Memory + Code Index | Read-only exploration |
| Ask | `answer_question_with_agent()` | 20 | Read + Memory + Code Index | Question answering |

### 6.2 Agent Loop Structure

Each iteration of the agent loop [`src/agent/analyzer.py:448-714`] consists of:

1. **Context management** — Check token usage against model limit; compress if >70% capacity
2. **LLM call** — Send conversation history + tool definitions to the configured LLM
3. **Tool execution** — Process each tool call from the LLM response
4. **Stuck detection** — After 3 consecutive identical errors, inject a recovery message
5. **Working memory injection** — Persist agent notes across context truncation

The agent signals completion by calling `task_complete` [`src/agent/tools.py:506-523`], which triggers the exit from the loop.

### 6.3 Smart Initial Context

Before entering the loop, the system builds a focused initial context from the user's requirements [`src/agent/context.py:200-270`]:

1. **Identifier extraction** — CamelCase and snake_case terms are extracted from requirements text
2. **Targeted grep** — Each identifier is searched in the codebase (top 5 matches per pattern, max 10 patterns)
3. **Signature matching** — Consciousness signatures matching the identifiers are listed
4. **File path extraction** — Explicit file paths in the requirements are included

This produces a ~2-5K character focused summary rather than a generic 25K codebase dump.

### 6.4 Working Memory

The `WorkingMemory` class [`src/agent/knowledge.py:37-72`] provides an in-process key-value store that the agent can write to during execution via the `update_memory` tool. Crucially, working memory survives context compression — it is injected into the system prompt dynamically [`src/agent/analyzer.py:686`], ensuring the agent's notes persist even when older conversation turns are dropped.

After task completion, working memory is merged into persistent `KnowledgeEntry` storage [`src/agent/knowledge.py:116-147`], enabling cross-session learning.

---

## 7. Context Management

### 7.1 The Context Window Challenge

For a 50-turn agent session, conversation history grows linearly. Tool outputs can be large — a grep over 18K files may return 100KB of results. Without management, the context window fills within 15-20 turns, leaving insufficient space for the LLM to reason.

### 7.2 Token Estimation

Token counts are estimated at ~4 characters per token [`src/agent/context.py:37-39`], applied to message content and tool call arguments. Model-specific context limits are maintained in a lookup table [`src/agent/context.py:21-32`] with a 80% safety margin:

| Model | Raw Limit | Usable (80%) |
|-------|-----------|-------------|
| GPT-4o | 128K | 102K |
| Claude 3.5 Sonnet | 200K | 160K |
| Gemini 1.5 Pro | 1M | 800K |

### 7.3 Intelligent Summarization

When tool output exceeds 15,000 characters, `summarize_large_output()` [`src/agent/context.py:84-127`] uses a fast/cheap LLM (GPT-4o-mini, Claude Haiku, or Gemini Flash) to produce a condensed version that preserves:

- Error messages and tracebacks
- File paths and line numbers
- Function/class names
- Test pass/fail counts

The summary replaces the original output in the conversation history: `"[Summarized from 45000 chars]\n<condensed version>"`.

**Trade-off**: Each summarization call is an additional LLM invocation not counted against `max_turns`. In pathological cases with many large tool outputs, 15-25 hidden summarization calls can consume significant budget. When `smart_summarization=False`, the system falls back to simple truncation [`src/agent/context.py:178-179`].

### 7.4 Conversation Compression

When conversation tokens exceed 70% of the model's limit, `manage_conversation_context()` [`src/agent/context.py:138-193`] applies a two-phase strategy:

**Phase 1 — Summarize middle messages**: The first 2 messages (system + initial user) and last 12 messages are protected. All `tool` result messages in the middle section exceeding 2KB are summarized (or truncated if `smart_summarization=False`).

**Phase 2 — Drop oldest messages**: If still over 80% capacity after summarization, the oldest middle messages are dropped in pairs (assistant + tool response) until the threshold is met.

---

## 8. Post-Edit Verification

### 8.1 Verification Gate

After the agent completes its changes, a 4-step verification gate runs [`src/code_index/verifier.py:83-117`]:

1. **Syntax check** — `py_compile.compile()` on each changed file [`src/code_index/verifier.py:120-129`]
2. **Import check** — AST walk to verify that imported in-repo modules exist [`src/code_index/verifier.py:132-159`]
3. **Scoped tests** — Pattern-matched `pytest -x -q` on test files corresponding to changed modules [`src/code_index/verifier.py:162-201`]
4. **Caller check** — Re-extracts symbols from changed files and compares signatures against the index; warns if a removed or changed symbol has callers [`src/code_index/verifier.py:204-245`]

### 8.2 Repair Loop

If verification fails, the system generates a structured repair prompt [`src/code_index/verifier.py:248-311`] and spawns a repair agent with `max_turns=20` [`main.py:567-615`]. Only one repair attempt is made to prevent infinite loops.

**Design decision**: Caller signature mismatches produce warnings, not errors. This allows intentional breaking changes while providing visibility into impact.

---

## 9. Resiliency

### 9.1 Circuit Breaker

The `CircuitBreaker` [`src/resiliency.py:35-101`] implements the standard three-state pattern:

- **CLOSED** — Normal operation; failures counted
- **OPEN** — All calls rejected (fail-fast) for `recovery_timeout` seconds (default: 60s)
- **HALF_OPEN** — One probe call allowed after timeout

The circuit opens after `failure_threshold` (default: 5) consecutive LLM API failures. All state mutations are protected by `threading.Lock` for thread safety [`src/resiliency.py:52`].

### 9.2 Token Bucket Rate Limiter

The `TokenBucketRateLimiter` [`src/resiliency.py:103-162`] prevents API rate limit exhaustion:

- **Capacity**: 10 tokens (default)
- **Refill rate**: 1 token/second (default)
- **Behavior**: `acquire()` blocks until a token is available, with configurable timeout

### 9.3 Retry Logic

The LLM client implements exponential backoff retry [`src/llm_client.py:331-357`]:

- **Max retries**: 3
- **Base delay**: 2 seconds, multiplied by 2^attempt
- **Retryable errors**: Rate limits (429), timeouts, server errors (500/502/503), overloaded responses [`src/llm_client.py:133-139`]

### 9.4 Multi-Provider Support

The `chat_completion()` function [`src/llm_client.py:197-359`] routes to provider-specific backends:

| Provider | Backend | Authentication |
|----------|---------|----------------|
| OpenAI | LiteLLM | API key (env: `OPENAI_API_KEY`) |
| Anthropic | LiteLLM | API key (env: `ANTHROPIC_API_KEY`) |
| Google/Gemini | LiteLLM | API key (env: `GEMINI_API_KEY`) |
| Azure OpenAI | Custom client | Certificate or API key |
| AWS Bedrock | cdao SDK | IAM role / SigV4 |

---

## 10. Configuration

The system is configured via `config.ini`, parsed by `load_config()` [`src/config_loader.py:13-171`]. Eleven sections control all aspects of behavior:

| Section | Key Parameters | Defaults |
|---------|---------------|----------|
| `[repository]` | platform, repo_url, base_branch | github, main |
| `[ai]` | provider, model, api_key | openai, gpt-4o |
| `[agent]` | max_turns, plan_max_turns, smart_summarization | 50, 30, true |
| `[consciousness]` | backend, cache_dir, max_age_hours | file, .consciousness, 24 |
| `[code_index]` | cache_dir, max_age_hours | .code-index, 24 |
| `[context]` | use_pipeline, grep_enricher, call_graph_enricher | true, true, false |
| `[testing]` | run_tests, test_timeout, testing_strategy | true, 60, auto |
| `[knowledge]` | backend, storage_dir | file, ~/.code-autonomy/knowledge |
| `[tracing]` | enabled, storage_dir | false, .traces |
| `[workflow]` | work_dir, cleanup_after_pr | ./workspace, true |

All parameters support environment variable resolution for secrets [`src/config_loader.py:50-76`].

---

## 11. Testing

The system includes a comprehensive test suite of **347 tests** across 20 test files:

| Test File | Coverage Area | Tests |
|-----------|--------------|-------|
| `test_code_index_symbol_table.py` | Symbol extraction, AST parsing | ~40 |
| `test_code_index_imports.py` | Import resolution, relative imports | ~30 |
| `test_code_index_graph.py` | Dependency graph, bidirectional edges | ~25 |
| `test_code_index_tools.py` | All 7 code index tools | ~35 |
| `test_code_index_verifier.py` | Verification gate, repair suggestions | ~20 |
| `test_consciousness.py` | Consciousness build, incremental update | ~30 |
| `test_agent_tools.py` | Read/write/exec tools, path safety | ~40 |
| `test_agent_context.py` | Token counting, summarization, compression | ~25 |
| `test_resiliency.py` | Circuit breaker, rate limiter | ~20 |
| `test_llm_client.py` | Multi-provider routing, retry logic | ~25 |
| Other test files | Config loading, tracing, validation | ~57 |

Tests use pytest with fixtures, mocking (`unittest.mock`), and temporary directories. The full suite runs in ~14 seconds.

---

## 12. Performance Characteristics

### 12.1 Index Build Times

Measured on typical Python repositories:

| Phase | 500 files | 2,000 files | 18,000 files |
|-------|-----------|-------------|--------------|
| Phase 0: Parallel scan (8 workers) | 0.5s | 2s | 20-40s |
| Phase 1: Symbol table | 1s | 3s | 10-15s |
| Phase 2: Import resolution | 0.3s | 1s | 5-10s |
| Phase 3: Dependency graph | 0.5s | 1.5s | 10-15s |
| Phase 4: Class hierarchy | 0.1s | 0.3s | 2-5s |
| Phase 5: Embeddings (API) | 5s | 15s | 30-60s |
| **Total** | **~7s** | **~22s** | **~80-145s** |
| **Cached load** | **0.15s** | **0.5s** | **<2s** |

### 12.2 Query Performance

All code index tool queries operate on in-memory data structures:

| Query | Data Structure | Time |
|-------|---------------|------|
| Find callers | Hash map (reverse graph) | <1ms |
| Find dependents | Hash map (file_dependents) | <1ms |
| Describe entity | Hash map (symbol table) | <1ms |
| Find similar | NumPy cosine similarity | 10-50ms |
| Impact analysis | Multi-map traversal | 10-50ms |
| Context for edit | Multi-map + optional similarity | 5-20ms |
| Predict breakage | Multi-map + caller counting | 10-50ms |

### 12.3 Agent Turn Budget

Typical allocation for a 50-turn agent session:

| Activity | Turns | Percentage |
|----------|-------|------------|
| Initial exploration (grep, list_dir, read_file) | 5-10 | 10-20% |
| Code index queries | 3-5 | 6-10% |
| Implementation (edit_file, write_file) | 15-20 | 30-40% |
| Testing (run_command) | 5-10 | 10-20% |
| Fix-retry cycles | 5-10 | 10-20% |
| Context management overhead | 0 (hidden) | — |

---

## 13. Design Decisions and Trade-Offs

### 13.1 All Parameters Optional with None Defaults

Every new parameter added to existing functions defaults to `None`, preserving full backward compatibility. Existing callers require zero changes, and all 347 existing tests pass without modification.

### 13.2 AST-Only Python Analysis

The system uses Python's `ast` module exclusively rather than tree-sitter or Language Server Protocol. This limits analysis to Python but provides deep integration (accurate line numbers, type annotations, decorator extraction) with zero external dependencies.

### 13.3 Plain Dict Cache Over Custom Classes

The file cache uses `dict[str, tuple[str, ast.Module | None]]` rather than a dedicated `FileCache` class. This simplicity makes the interface transparent: downstream consumers receive exactly what they need (content strings and AST modules) without learning a new API.

### 13.4 Warning-Level Signature Checks

The verifier warns on signature mismatches rather than failing the build. This avoids blocking intentional breaking changes while providing visibility into potential impact.

### 13.5 7 Tools vs. 1 Generic Query Tool

Providing 7 purpose-built tools (rather than one `query_index(query_type, params)` tool) improves LLM tool selection accuracy. Each tool's description directly maps to a developer's intent: "find who calls X" vs. "analyze impact of changing Y".

---

## 14. Limitations and Future Work

### 14.1 Current Limitations

1. **Python-only deep analysis** — AST parsing is limited to Python. Java call graph extraction exists [`src/context/call_graph/__init__.py:19-25`] but is optional and less comprehensive.

2. **No incremental code index rebuild** — Unlike consciousness (which supports git-aware incremental updates), the code index performs a full rebuild when the cache expires.

3. **Hidden LLM call overhead** — Smart summarization consumes LLM calls not reflected in `max_turns`, potentially consuming 15-25 hidden calls per session.

4. **No global call budget** — `max_turns` only counts main loop iterations. Summarization, compression, and verification repair calls are uncapped.

5. **Single-process architecture** — All data resides in one process's memory. Repositories exceeding available RAM (~50K+ files) may require architectural changes.

### 14.2 Future Directions

1. **Incremental code index** — Git-aware partial updates, re-scanning only changed files and patching affected graph edges.

2. **Tiered summarization** — Replace LLM-based summarization with structured regex extraction for common patterns (test output, stack traces), reserving LLM calls for genuinely complex outputs.

3. **Pre-computed edit context** — Proactively assemble the `context_for_edit` output before the agent loop starts, using identifier extraction from the requirement to predict which files will be modified.

4. **Multi-language support** — Extend AST-based analysis to TypeScript/JavaScript (via tree-sitter), Java (via Eclipse JDT), and Go (via go/ast).

5. **Distributed indexing** — Shard the code index by module/package for repositories exceeding 100K files, with a coordinator that merges cross-shard queries.

6. **Global LLM call budget** — A session-wide counter across all LLM calls (main loop + summarization + compression) with configurable limits.

---

## 15. Conclusion

Code Autonomy demonstrates that LLM-driven software engineering at scale requires more than a capable language model — it requires a purpose-built intelligence layer that bridges the gap between a multi-thousand-file repository and the LLM's finite attention. The two-tier architecture (consciousness for breadth, code index for depth), combined with parallel I/O, in-memory graph queries, and adaptive context management, enables autonomous code modification across repositories of 18K+ files within a 50-turn agent budget.

The system's key insight is that **the agent should never spend turns discovering information that can be pre-computed**. Symbol tables, dependency graphs, class hierarchies, and semantic embeddings transform O(n) exploration into O(1) queries — and the 7 purpose-built tools make this intelligence accessible to the LLM in the language it understands: natural-language-described function calls.

---

## Appendix A: Source Code References

All citations reference the repository at `github.com/[org]/code-autonomy` on branch `feature/add-ask-mode`.

| Component | File | Key Lines |
|-----------|------|-----------|
| CodeIndex dataclass | `src/code_index/storage.py` | 31-43 |
| scan_repo_files (parallel I/O) | `src/code_index/storage.py` | 58-94 |
| build_code_index orchestrator | `src/code_index/storage.py` | 97-165 |
| Cache save/load | `src/code_index/storage.py` | 108-240 |
| SymbolEntry dataclass | `src/code_index/symbol_table.py` | 23-39 |
| SymbolTable class | `src/code_index/symbol_table.py` | 42-129 |
| AST symbol extraction | `src/code_index/symbol_table.py` | 160-261 |
| build_symbol_table | `src/code_index/symbol_table.py` | 264-302 |
| Import resolution | `src/code_index/import_resolver.py` | 46-127 |
| Relative import handling | `src/code_index/import_resolver.py` | 28-43 |
| DependencyGraph dataclass | `src/code_index/graph_builder.py` | 16-54 |
| build_dependency_graph | `src/code_index/graph_builder.py` | 57-152 |
| ClassHierarchy | `src/code_index/hierarchy.py` | 13-71 |
| build_class_hierarchy | `src/code_index/hierarchy.py` | 74-110 |
| EntityEmbeddings | `src/code_index/entity_embeddings.py` | 24-202 |
| Embedding build pipeline | `src/code_index/entity_embeddings.py` | 38-108 |
| Cosine similarity search | `src/code_index/entity_embeddings.py` | 110-142 |
| Code index tools (7) | `src/code_index/tools.py` | 15-559 |
| Tool dispatcher | `src/code_index/tools.py` | 143-170 |
| context_for_edit | `src/code_index/tools.py` | 349-454 |
| predict_breakage | `src/code_index/tools.py` | 457-559 |
| Verification gate | `src/code_index/verifier.py` | 83-117 |
| Repair suggestions | `src/code_index/verifier.py` | 248-311 |
| Python call graph visitor | `src/context/call_graph/python_extractor.py` | 48-92 |
| build_call_graph | `src/context/call_graph/__init__.py` | 11-27 |
| ProjectConsciousness | `src/consciousness/core.py` | 373-395 |
| build_consciousness | `src/consciousness/core.py` | 509-575 |
| Score-based sampling | `src/consciousness/core.py` | 262-297 |
| Token-aware rendering | `src/consciousness/core.py` | 399-487 |
| Incremental rebuild | `src/consciousness/core.py` | 641-744 |
| Agent loop (main) | `src/agent/analyzer.py` | 448-714 |
| generate_changes_with_agent | `src/agent/analyzer.py` | 366-412 |
| generate_plan_with_agent | `src/agent/analyzer.py` | 777+ |
| answer_question_with_agent | `src/agent/analyzer.py` | 1091+ |
| Smart initial context | `src/agent/context.py` | 200-270 |
| Summarize large output | `src/agent/context.py` | 84-127 |
| Context compression | `src/agent/context.py` | 138-193 |
| Token counting | `src/agent/context.py` | 37-60 |
| Agent tools (read/write/exec) | `src/agent/tools.py` | 1-523 |
| Tool registration | `src/agent/tools.py` | 481-494 |
| Tool dispatch | `src/agent/tools.py` | 530-631 |
| Working memory | `src/agent/knowledge.py` | 37-72 |
| Knowledge persistence | `src/agent/knowledge.py` | 79-172 |
| Repo knowledge files | `src/agent/knowledge.py` | 355-442 |
| LLM client (multi-provider) | `src/llm_client.py` | 197-359 |
| Retry logic | `src/llm_client.py` | 331-357 |
| Usage tracking | `src/llm_client.py` | 23-51 |
| Circuit breaker | `src/resiliency.py` | 35-101 |
| Token bucket rate limiter | `src/resiliency.py` | 103-162 |
| Configuration loader | `src/config_loader.py` | 13-171 |
| Constants (SKIP_DIRS, extensions) | `src/constants.py` | 6-15 |
| Context enricher pipeline | `src/context/pipeline.py` | 12-52 |
| Grep enricher | `src/context/enrichers/grep_enricher.py` | 35-77 |
| CLI entry point | `main.py` | 1-709 |

## Appendix B: Dependencies

### Standard Library
- `ast` — Python AST parsing (all code analysis)
- `concurrent.futures` — ThreadPoolExecutor for parallel I/O
- `json` — Cache serialization
- `pickle` — Embedding vector storage
- `hashlib` — SHA-256 content hashing
- `subprocess` — Test execution and command running
- `configparser` — Configuration file parsing
- `threading` — Lock-based concurrency control

### Third-Party
- **LiteLLM** — Unified LLM API across providers (OpenAI, Anthropic, Google, Azure)
- **NumPy** — Vector operations for cosine similarity search
- **GitPython** — Git log parsing for incremental rebuild
- **pytest** — Test execution (both internal tests and user code verification)
- **Rich** (optional) — Terminal UI formatting

### Internal Modules
- `src.constants` — SKIP_DIRS, CODE_EXTENSIONS, SEARCH_EXTENSIONS
- `src.consciousness.core` — AST helper functions shared with symbol table
- `src.agent.knowledge` — compute_repo_id, WorkingMemory
- `src.llm_client` — Unified chat_completion API
- `src.resiliency` — CircuitBreaker, TokenBucketRateLimiter
