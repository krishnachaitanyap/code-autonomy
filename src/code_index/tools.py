"""
Code index agent tools: 5 new tools for the agent to query the code index.

Uses ``_tool()`` from ``src/agent/tools`` for schema construction.
"""

import os
import subprocess

from src.agent.tools import _tool
from src.code_index.storage import CodeIndex


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

_FIND_CALLERS_SCHEMA = _tool(
    "find_callers",
    "Find all callers of a function, method, or class. Returns a list of "
    "caller FQNs with file:line information. Use this to understand who "
    "depends on a symbol before modifying it.",
    {
        "symbol_name": {
            "type": "string",
            "description": "Symbol name or FQN (e.g., 'chat_completion' or 'src/llm_client.py::chat_completion')",
        },
    },
    required=["symbol_name"],
)

_FIND_DEPENDENTS_SCHEMA = _tool(
    "find_dependents",
    "Find all files that import from a given file. Use this to understand "
    "the blast radius of changes to a module.",
    {
        "file_path": {
            "type": "string",
            "description": "Relative file path (e.g., 'src/llm_client.py')",
        },
    },
    required=["file_path"],
)

_IMPACT_ANALYSIS_SCHEMA = _tool(
    "impact_analysis",
    "Comprehensive impact analysis for a file: callers of its symbols, "
    "files that depend on it, and related test files. Use before making "
    "changes to understand what might break.",
    {
        "file_path": {
            "type": "string",
            "description": "Relative file path to analyze (e.g., 'src/agent/tools.py')",
        },
    },
    required=["file_path"],
)

_DESCRIBE_ENTITY_SCHEMA = _tool(
    "describe_entity",
    "Get a detailed description of a symbol: full signature, docstring, "
    "callers, callees, class hierarchy (if applicable). Use to understand "
    "what a function/class does and how it's connected.",
    {
        "symbol_name": {
            "type": "string",
            "description": "Symbol name or FQN (e.g., 'WorkingMemory' or 'src/agent/knowledge.py::WorkingMemory')",
        },
    },
    required=["symbol_name"],
)

_FIND_SIMILAR_SCHEMA = _tool(
    "find_similar",
    "Semantic search across all code entities (functions, classes, methods). "
    "Finds symbols whose signature/docstring/body are most similar to the "
    "query text. Use to discover related code.",
    {
        "query": {
            "type": "string",
            "description": "Natural language query or code snippet to search for",
        },
        "top_k": {
            "type": "integer",
            "description": "Number of results to return (default 5)",
        },
    },
    required=["query"],
)

_CONTEXT_FOR_EDIT_SCHEMA = _tool(
    "context_for_edit",
    "Pre-edit context assembly: callers, callees, dependents, class hierarchy, "
    "tests, and optionally similar code. Use BEFORE editing a file to understand "
    "the minimum sufficient context for a safe change.",
    {
        "file_path": {
            "type": "string",
            "description": "Relative file path to get context for (e.g., 'src/llm_client.py')",
        },
        "symbol_name": {
            "type": "string",
            "description": "Optional: narrow focus to a specific symbol in the file",
        },
        "intent": {
            "type": "string",
            "description": "Optional: what you intend to change (used for semantic search of related code)",
        },
    },
    required=["file_path"],
)

_PREDICT_BREAKAGE_SCHEMA = _tool(
    "predict_breakage",
    "Risk report: predict what callers, children, and dependents will break "
    "if a file is changed. Returns per-symbol risk levels (HIGH/MEDIUM/LOW) "
    "and specific warnings. Use BEFORE making changes.",
    {
        "file_path": {
            "type": "string",
            "description": "Relative file path to analyze (e.g., 'src/agent/tools.py')",
        },
        "changes_description": {
            "type": "string",
            "description": "Optional: description of planned changes (used for semantic search of related code that may also need changes)",
        },
    },
    required=["file_path"],
)

_FIND_ALL_USAGES_SCHEMA = _tool(
    "find_all_usages",
    "Find ALL files that use a property, field, config key, or symbol. "
    "Returns ranked results: HIGH (AST-confirmed), MEDIUM (grep code), LOW (grep comments). "
    "Use for bulk updates across the codebase.",
    {
        "name": {
            "type": "string",
            "description": "Property, field, or config key name to search for (e.g., 'timeout', 'max_retries')",
        },
        "include_grep": {
            "type": "boolean",
            "description": "Also run grep fallback to find non-AST usages (default true)",
        },
    },
    required=["name"],
)

CODE_INDEX_TOOLS = [
    _FIND_CALLERS_SCHEMA,
    _FIND_DEPENDENTS_SCHEMA,
    _IMPACT_ANALYSIS_SCHEMA,
    _DESCRIBE_ENTITY_SCHEMA,
    _FIND_SIMILAR_SCHEMA,
    _CONTEXT_FOR_EDIT_SCHEMA,
    _PREDICT_BREAKAGE_SCHEMA,
    _FIND_ALL_USAGES_SCHEMA,
]


# ---------------------------------------------------------------------------
# Tool executor
# ---------------------------------------------------------------------------

def execute_code_index_tool(
    code_index: CodeIndex,
    tool_name: str,
    args: dict,
) -> str:
    """Execute a code index tool and return the result string."""
    if tool_name == "find_callers":
        return _find_callers(code_index, args.get("symbol_name", ""))
    if tool_name == "find_dependents":
        return _find_dependents(code_index, args.get("file_path", ""))
    if tool_name == "impact_analysis":
        return _impact_analysis(code_index, args.get("file_path", ""))
    if tool_name == "describe_entity":
        return _describe_entity(code_index, args.get("symbol_name", ""))
    if tool_name == "find_similar":
        return _find_similar(code_index, args.get("query", ""), args.get("top_k", 5))
    if tool_name == "context_for_edit":
        return _context_for_edit(
            code_index, args.get("file_path", ""),
            args.get("symbol_name"), args.get("intent"),
        )
    if tool_name == "predict_breakage":
        return _predict_breakage(
            code_index, args.get("file_path", ""),
            args.get("changes_description"),
        )
    if tool_name == "find_all_usages":
        return _find_all_usages(
            code_index, args.get("name", ""),
            args.get("include_grep", True),
        )
    return f"Unknown code_index tool: {tool_name}"


CODE_INDEX_TOOL_NAMES = {
    "find_callers", "find_dependents", "impact_analysis",
    "describe_entity", "find_similar", "context_for_edit",
    "predict_breakage", "find_all_usages",
}


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def _resolve_symbol(code_index: CodeIndex, symbol_name: str) -> list:
    """Resolve a symbol name or FQN to SymbolEntry list."""
    st = code_index.symbol_table
    # Try exact FQN first
    entry = st.get_by_fqn(symbol_name)
    if entry:
        return [entry]
    # Try by name
    return st.get_by_name(symbol_name)


def _find_callers(code_index: CodeIndex, symbol_name: str) -> str:
    entries = _resolve_symbol(code_index, symbol_name)
    if not entries:
        return f"Symbol not found: {symbol_name}"

    lines = []
    for entry in entries:
        callers = code_index.dependency_graph.get_callers(entry.fqn)
        if callers:
            lines.append(f"## Callers of {entry.fqn}")
            for caller_fqn in sorted(callers):
                caller_entry = code_index.symbol_table.get_by_fqn(caller_fqn)
                if caller_entry:
                    lines.append(f"  - {caller_fqn} ({caller_entry.file_path}:{caller_entry.line_start})")
                else:
                    lines.append(f"  - {caller_fqn}")
        else:
            lines.append(f"No callers found for {entry.fqn}")

    return "\n".join(lines) if lines else f"No callers found for {symbol_name}"


def _find_dependents(code_index: CodeIndex, file_path: str) -> str:
    dependents = code_index.dependency_graph.get_file_dependents(file_path)
    if not dependents:
        return f"No files depend on {file_path}"

    lines = [f"## Files that import from {file_path}"]
    for dep in sorted(dependents):
        lines.append(f"  - {dep}")
    return "\n".join(lines)


def _impact_analysis(code_index: CodeIndex, file_path: str) -> str:
    lines = [f"## Impact Analysis: {file_path}"]

    # 1. Symbols in this file
    symbols = code_index.symbol_table.get_by_file(file_path)
    if symbols:
        lines.append(f"\n### Symbols ({len(symbols)})")
        for sym in symbols:
            lines.append(f"  - {sym.symbol_type} {sym.name} (line {sym.line_start})")

    # 2. File dependents
    dependents = code_index.dependency_graph.get_file_dependents(file_path)
    if dependents:
        lines.append(f"\n### Dependent files ({len(dependents)})")
        for dep in sorted(dependents):
            lines.append(f"  - {dep}")

    # 3. Callers of all symbols in this file
    all_callers: set[str] = set()
    for sym in symbols:
        callers = code_index.dependency_graph.get_callers(sym.fqn)
        all_callers.update(callers)
    if all_callers:
        lines.append(f"\n### External callers ({len(all_callers)})")
        for caller in sorted(all_callers):
            caller_entry = code_index.symbol_table.get_by_fqn(caller)
            if caller_entry:
                lines.append(f"  - {caller} ({caller_entry.file_path}:{caller_entry.line_start})")
            else:
                lines.append(f"  - {caller}")

    # 4. Related test files
    module_name = file_path.split("/")[-1].replace(".py", "")
    test_patterns = {f"test_{module_name}.py", f"{module_name}_test.py"}
    related_tests = [
        f for f in code_index.symbol_table.all_files
        if f.split("/")[-1] in test_patterns
    ]
    if related_tests:
        lines.append(f"\n### Related test files ({len(related_tests)})")
        for t in sorted(related_tests):
            lines.append(f"  - {t}")

    return "\n".join(lines)


def _describe_entity(code_index: CodeIndex, symbol_name: str) -> str:
    entries = _resolve_symbol(code_index, symbol_name)
    if not entries:
        return f"Symbol not found: {symbol_name}"

    lines = []
    for entry in entries:
        lines.append(f"## {entry.fqn}")
        lines.append(f"Type: {entry.symbol_type}")
        lines.append(f"File: {entry.file_path}:{entry.line_start}-{entry.line_end}")
        lines.append(f"Signature:\n  {entry.signature}")
        if entry.docstring_summary:
            lines.append(f"Docstring: {entry.docstring_summary}")
        if entry.parent_class:
            lines.append(f"Parent class: {entry.parent_class}")

        # Callers
        callers = code_index.dependency_graph.get_callers(entry.fqn)
        if callers:
            lines.append(f"Callers ({len(callers)}):")
            for c in sorted(callers)[:10]:
                lines.append(f"  - {c}")
            if len(callers) > 10:
                lines.append(f"  ... and {len(callers) - 10} more")

        # Callees
        callees = code_index.dependency_graph.get_callees(entry.fqn)
        if callees:
            lines.append(f"Callees ({len(callees)}):")
            for c in sorted(callees)[:10]:
                lines.append(f"  - {c}")
            if len(callees) > 10:
                lines.append(f"  ... and {len(callees) - 10} more")

        # Class hierarchy
        if entry.symbol_type == "class":
            parents = code_index.class_hierarchy.get_parents(entry.fqn)
            children = code_index.class_hierarchy.get_children(entry.fqn)
            if parents:
                lines.append(f"Parent classes: {', '.join(parents)}")
            if children:
                lines.append(f"Child classes: {', '.join(children)}")

        lines.append("")  # blank line between entries

    return "\n".join(lines)


def _find_similar(code_index: CodeIndex, query: str, top_k: int = 5) -> str:
    results = code_index.embeddings.find_similar(query, top_k=top_k)
    if not results:
        return "No similar entities found (embeddings may not be available)"

    lines = [f"## Similar entities for: {query[:60]}"]
    for fqn, score in results:
        entry = code_index.symbol_table.get_by_fqn(fqn)
        if entry:
            lines.append(
                f"  - {fqn} (score: {score:.3f}) — {entry.symbol_type} "
                f"at {entry.file_path}:{entry.line_start}"
            )
        else:
            lines.append(f"  - {fqn} (score: {score:.3f})")
    return "\n".join(lines)


def _find_test_files(code_index: CodeIndex, file_path: str) -> list[str]:
    """Find test files related to a source file."""
    module_name = file_path.split("/")[-1].replace(".py", "")
    test_patterns = {f"test_{module_name}.py", f"{module_name}_test.py"}
    return [
        f for f in code_index.symbol_table.all_files
        if f.split("/")[-1] in test_patterns
    ]


def _context_for_edit(
    code_index: CodeIndex,
    file_path: str,
    symbol_name: str | None = None,
    intent: str | None = None,
) -> str:
    """Assemble minimum sufficient context before editing a file."""
    lines = [f"## Pre-edit Context: {file_path}"]

    # 1. Get all symbols in the file
    all_symbols = code_index.symbol_table.get_by_file(file_path)
    if not all_symbols:
        return f"No symbols found in {file_path}"

    # 2. Narrow focus if symbol_name provided
    if symbol_name:
        focus = [s for s in all_symbols if s.name == symbol_name or s.fqn == symbol_name]
        if not focus:
            # Try resolving across the index
            focus = _resolve_symbol(code_index, symbol_name)
            focus = [s for s in focus if s.file_path == file_path]
        if not focus:
            lines.append(f"\nSymbol '{symbol_name}' not found in {file_path}, showing all symbols.")
            focus = all_symbols
    else:
        focus = all_symbols

    # Section: Symbols
    lines.append(f"\n### Symbols ({len(focus)})")
    for sym in focus:
        lines.append(f"  - {sym.symbol_type} {sym.name} (line {sym.line_start}-{sym.line_end}): {sym.signature}")

    # Section: Callers (reverse graph)
    all_callers: list[str] = []
    for sym in focus:
        callers = code_index.dependency_graph.get_callers(sym.fqn)
        for caller_fqn in sorted(callers):
            caller_entry = code_index.symbol_table.get_by_fqn(caller_fqn)
            if caller_entry:
                all_callers.append(f"{caller_fqn} ({caller_entry.file_path}:{caller_entry.line_start})")
            else:
                all_callers.append(caller_fqn)
    if all_callers:
        lines.append(f"\n### Callers ({len(all_callers)})")
        for c in all_callers:
            lines.append(f"  - {c}")

    # Section: Callees (forward graph)
    all_callees: list[str] = []
    for sym in focus:
        callees = code_index.dependency_graph.get_callees(sym.fqn)
        for callee_fqn in sorted(callees):
            callee_entry = code_index.symbol_table.get_by_fqn(callee_fqn)
            if callee_entry:
                all_callees.append(f"{callee_fqn} ({callee_entry.file_path}:{callee_entry.line_start})")
            else:
                all_callees.append(callee_fqn)
    if all_callees:
        lines.append(f"\n### Callees ({len(all_callees)})")
        for c in all_callees:
            lines.append(f"  - {c}")

    # Section: Dependents (who imports this file)
    dependents = code_index.dependency_graph.get_file_dependents(file_path)
    if dependents:
        lines.append(f"\n### Dependents ({len(dependents)})")
        for dep in sorted(dependents):
            lines.append(f"  - {dep}")

    # Section: Class hierarchy
    hierarchy_lines: list[str] = []
    for sym in focus:
        if sym.symbol_type == "class":
            parents = code_index.class_hierarchy.get_parents(sym.fqn)
            children = code_index.class_hierarchy.get_children(sym.fqn)
            if parents or children:
                parts = [f"  - {sym.name}"]
                if parents:
                    parts.append(f"parents: {', '.join(parents)}")
                if children:
                    parts.append(f"children: {', '.join(children)}")
                hierarchy_lines.append(" | ".join(parts))
    if hierarchy_lines:
        lines.append(f"\n### Hierarchy")
        lines.extend(hierarchy_lines)

    # Section: Test files
    test_files = _find_test_files(code_index, file_path)
    if test_files:
        lines.append(f"\n### Tests ({len(test_files)})")
        for t in sorted(test_files):
            lines.append(f"  - {t}")

    # Section: Similar code (if intent provided)
    if intent:
        similar_results = code_index.embeddings.find_similar(intent, top_k=5)
        if similar_results:
            lines.append(f"\n### Similar Code")
            for fqn, score in similar_results:
                entry = code_index.symbol_table.get_by_fqn(fqn)
                if entry:
                    lines.append(f"  - {fqn} (score: {score:.3f}) at {entry.file_path}:{entry.line_start}")
                else:
                    lines.append(f"  - {fqn} (score: {score:.3f})")

    return "\n".join(lines)


def _predict_breakage(
    code_index: CodeIndex,
    file_path: str,
    changes_description: str | None = None,
) -> str:
    """Predict what will break if a file is changed, with risk levels."""
    symbols = code_index.symbol_table.get_by_file(file_path)
    if not symbols:
        return f"No symbols found in {file_path}"

    risk_entries: list[tuple[str, str, str, int]] = []  # (risk, fqn, type, caller_count)
    warnings: list[str] = []

    for sym in symbols:
        callers = code_index.dependency_graph.get_callers(sym.fqn)
        caller_count = len(callers)

        has_children = False
        if sym.symbol_type == "class":
            children = code_index.class_hierarchy.get_children(sym.fqn)
            has_children = bool(children)
            if has_children:
                warnings.append(
                    f"Class {sym.name} has child classes: {', '.join(children)} — "
                    f"changes to interface will break subclasses"
                )

        if caller_count > 5 or has_children:
            risk = "HIGH"
        elif caller_count >= 1:
            risk = "MEDIUM"
        else:
            risk = "LOW"

        risk_entries.append((risk, sym.fqn, sym.symbol_type, caller_count))

        if caller_count > 0:
            caller_details = []
            for caller_fqn in sorted(callers)[:5]:
                caller_entry = code_index.symbol_table.get_by_fqn(caller_fqn)
                if caller_entry:
                    caller_details.append(f"{caller_fqn} ({caller_entry.file_path}:{caller_entry.line_start})")
                else:
                    caller_details.append(caller_fqn)
            warnings.append(
                f"{sym.symbol_type} {sym.name} has {caller_count} caller(s): "
                + ", ".join(caller_details)
            )

    # Sort: HIGH first, then MEDIUM, then LOW
    risk_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    risk_entries.sort(key=lambda x: (risk_order[x[0]], -x[3]))

    # Determine overall risk
    risk_levels = {r[0] for r in risk_entries}
    if "HIGH" in risk_levels:
        overall = "HIGH"
    elif "MEDIUM" in risk_levels:
        overall = "MEDIUM"
    else:
        overall = "LOW"

    lines = [f"## Breakage Risk Report: {file_path}", f"Overall risk: **{overall}**"]

    # Dependents
    dependents = code_index.dependency_graph.get_file_dependents(file_path)
    if dependents:
        lines.append(f"\n### Dependent files ({len(dependents)})")
        for dep in sorted(dependents):
            lines.append(f"  - {dep}")

    # Per-symbol breakdown
    lines.append(f"\n### Per-symbol risk ({len(risk_entries)})")
    for risk, fqn, sym_type, caller_count in risk_entries:
        lines.append(f"  - [{risk}] {sym_type} {fqn} — {caller_count} caller(s)")

    # Warnings
    if warnings:
        lines.append(f"\n### Will-break warnings ({len(warnings)})")
        for w in warnings:
            lines.append(f"  - {w}")

    # Test coverage
    test_files = _find_test_files(code_index, file_path)
    if test_files:
        lines.append(f"\n### Test coverage")
        for t in sorted(test_files):
            lines.append(f"  - {t}")
    else:
        lines.append(f"\n### Test coverage")
        lines.append(f"  - WARNING: No test files found for {file_path}")

    # Similar code that may also need changes
    if changes_description:
        similar_results = code_index.embeddings.find_similar(changes_description, top_k=5)
        if similar_results:
            lines.append(f"\n### Related code (may also need changes)")
            for fqn, score in similar_results:
                entry = code_index.symbol_table.get_by_fqn(fqn)
                if entry and entry.file_path != file_path:
                    lines.append(f"  - {fqn} (score: {score:.3f}) at {entry.file_path}:{entry.line_start}")

    return "\n".join(lines)


def _find_all_usages(
    code_index: CodeIndex,
    name: str,
    include_grep: bool = True,
) -> str:
    """Find all usages of a property/field/config key across the codebase."""
    if not name:
        return "Error: 'name' parameter is required."

    # Collect results as (file, line, snippet, confidence)
    seen: set[tuple[str, int]] = set()
    results: list[tuple[str, int, str, str]] = []

    # 1. PropertyIndex lookup → HIGH confidence
    pi_entries = code_index.property_index.lookup(name)
    for file_path, line, snippet in pi_entries:
        key = (file_path, line)
        if key not in seen:
            seen.add(key)
            results.append((file_path, line, snippet, "HIGH"))

    # 2. Dependency graph reverse lookup (callers of matching symbols) → HIGH
    matching_symbols = code_index.symbol_table.get_by_name(name)
    for sym in matching_symbols:
        callers = code_index.dependency_graph.get_callers(sym.fqn)
        for caller_fqn in callers:
            caller_entry = code_index.symbol_table.get_by_fqn(caller_fqn)
            if caller_entry:
                key = (caller_entry.file_path, caller_entry.line_start)
                if key not in seen:
                    seen.add(key)
                    results.append((
                        caller_entry.file_path,
                        caller_entry.line_start,
                        f"calls {sym.fqn}",
                        "HIGH",
                    ))

    # 3. Grep fallback → MEDIUM (code) / LOW (comments)
    if include_grep and code_index.repo_path:
        grep_results = _grep_for_name(code_index.repo_path, name)
        for file_path, line, snippet, is_comment in grep_results:
            key = (file_path, line)
            if key not in seen:
                seen.add(key)
                confidence = "LOW" if is_comment else "MEDIUM"
                results.append((file_path, line, snippet, confidence))

    if not results:
        return f"No usages found for: {name}"

    # Group by confidence
    high = [(f, l, s) for f, l, s, c in results if c == "HIGH"]
    medium = [(f, l, s) for f, l, s, c in results if c == "MEDIUM"]
    low = [(f, l, s) for f, l, s, c in results if c == "LOW"]

    lines = [f"## All usages of '{name}' ({len(results)} total)"]

    if high:
        lines.append(f"\n### HIGH confidence — AST-confirmed ({len(high)})")
        for f, l, s in sorted(high):
            lines.append(f"  - {f}:{l}  {s}")

    if medium:
        lines.append(f"\n### MEDIUM confidence — grep code ({len(medium)})")
        for f, l, s in sorted(medium):
            lines.append(f"  - {f}:{l}  {s}")

    if low:
        lines.append(f"\n### LOW confidence — grep comments/strings ({len(low)})")
        for f, l, s in sorted(low):
            lines.append(f"  - {f}:{l}  {s}")

    return "\n".join(lines)


def _grep_for_name(
    repo_path: str, name: str,
) -> list[tuple[str, int, str, bool]]:
    """Run grep on the repo for a property name.

    Returns list of (rel_path, line_number, snippet, is_comment).
    """
    try:
        result = subprocess.run(
            ["grep", "-rn", "--include=*.py", "--include=*.java", name, repo_path],
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []

    entries: list[tuple[str, int, str, bool]] = []
    for line in result.stdout.splitlines():
        # Format: /abs/path:linenum:content
        parts = line.split(":", 2)
        if len(parts) < 3:
            continue
        abs_path, linenum_str, content = parts[0], parts[1], parts[2]
        try:
            linenum = int(linenum_str)
        except ValueError:
            continue
        # Convert to relative path
        if abs_path.startswith(repo_path):
            rel_path = abs_path[len(repo_path):].lstrip(os.sep).replace("\\", "/")
        else:
            rel_path = abs_path.replace("\\", "/")
        snippet = content.strip()
        is_comment = snippet.lstrip().startswith("#") or snippet.lstrip().startswith("//")
        entries.append((rel_path, linenum, snippet, is_comment))

    return entries
