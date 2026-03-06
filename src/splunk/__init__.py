"""
Splunk integration — tool schemas, dispatcher, and SPLUNK_TOOLS list.

Provides four agent tools:

    splunk_discover     — knn search on OpenSearch ``splunk-metadata`` to find
                          relevant indexes, fields, sourcetypes, relationships
    splunk_search       — run SPL query, return tabular results
    splunk_stats        — run SPL aggregation for chart visualisation
    splunk_saved_search — list or run saved searches/reports
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper: build an OpenAI function-calling tool schema
# ---------------------------------------------------------------------------

def _tool(name: str, description: str, params: dict, required: list[str] | None = None) -> dict:
    schema: dict = {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": params},
        },
    }
    if required:
        schema["function"]["parameters"]["required"] = required
    return schema


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

_SPLUNK_DISCOVER_SCHEMA = _tool(
    "splunk_discover",
    "Search OpenSearch for relevant Splunk indexes, fields, sourcetypes, and "
    "relationships matching the user's question. ALWAYS call this FIRST before "
    "splunk_search or splunk_stats so you know which index/fields to query.",
    {
        "query": {
            "type": "string",
            "description": "Natural language description of what to look for "
            "(e.g. 'profile service errors in production')",
        },
        "top_k": {
            "type": "integer",
            "description": "Number of metadata hits to return (default 5)",
        },
        "index": {
            "type": "string",
            "description": "OpenSearch index to search (default: splunk-metadata). "
            "Use the logical index name from config, e.g. 'splunk', 'code', 'incident'.",
        },
    },
    required=["query"],
)

_SPLUNK_SEARCH_SCHEMA = _tool(
    "splunk_search",
    "Run an SPL query against Splunk. Use the index/field/sourcetype context "
    "from splunk_discover to build a precise query. Returns tabular results.",
    {
        "spl": {
            "type": "string",
            "description": "SPL query string (e.g. 'index=app_logs_prod sourcetype=application.log level=ERROR | head 50')",
        },
        "earliest": {
            "type": "string",
            "description": "Earliest time (default: -24h). Examples: -1h, -7d, 2024-01-01T00:00:00",
        },
        "latest": {
            "type": "string",
            "description": "Latest time (default: now)",
        },
        "max_results": {
            "type": "integer",
            "description": "Max rows to return (default: 1000)",
        },
    },
    required=["spl"],
)

_SPLUNK_STATS_SCHEMA = _tool(
    "splunk_stats",
    "Run an SPL aggregation query for chart visualisation (bar/line/pie). "
    "The query should use stats/timechart/chart commands. Returns structured "
    "data the UI renders as a chart.",
    {
        "spl": {
            "type": "string",
            "description": "SPL aggregation query (e.g. 'index=app_logs_prod level=ERROR | timechart span=1h count')",
        },
        "chart_type": {
            "type": "string",
            "enum": ["auto", "bar", "line", "pie"],
            "description": "Chart type (default: auto — inferred from query)",
        },
        "earliest": {
            "type": "string",
            "description": "Earliest time (default: -24h)",
        },
        "latest": {
            "type": "string",
            "description": "Latest time (default: now)",
        },
        "max_results": {
            "type": "integer",
            "description": "Max rows (default: 1000)",
        },
    },
    required=["spl"],
)

_SPLUNK_SAVED_SEARCH_SCHEMA = _tool(
    "splunk_saved_search",
    "List available saved searches (omit name) or run a specific saved search "
    "by name. Returns tabular results when a name is given.",
    {
        "name": {
            "type": "string",
            "description": "Saved search name to run. Omit to list all available saved searches.",
        },
    },
)

SPLUNK_TOOLS = [
    _SPLUNK_DISCOVER_SCHEMA,
    _SPLUNK_SEARCH_SCHEMA,
    _SPLUNK_STATS_SCHEMA,
    _SPLUNK_SAVED_SEARCH_SCHEMA,
]

SPLUNK_TOOL_NAMES = {
    "splunk_discover",
    "splunk_search",
    "splunk_stats",
    "splunk_saved_search",
}


# ---------------------------------------------------------------------------
# Result formatting helpers
# ---------------------------------------------------------------------------

def _structured_table(title: str, rows: list[dict], spl: str = "") -> str:
    """Build a structured result envelope + plain markdown table."""
    if not rows:
        return json.dumps({"__structured": True, "format": "table", "title": title, "columns": [], "rows": [], "total": 0})

    columns = list(rows[0].keys())
    # Filter out internal fields starting with underscore
    columns = [c for c in columns if not c.startswith("_")]
    clean_rows = [{c: r.get(c, "") for c in columns} for r in rows]

    envelope = json.dumps({
        "__structured": True,
        "format": "table",
        "title": title,
        "columns": columns,
        "rows": clean_rows,
        "total": len(clean_rows),
    })

    # Also produce a plain markdown table for the LLM to reason about
    md_lines = [f"\n\n**{title}** ({len(clean_rows)} rows)\n"]
    md_lines.append("| " + " | ".join(columns) + " |")
    md_lines.append("| " + " | ".join("---" for _ in columns) + " |")
    for row in clean_rows[:20]:  # cap markdown to 20 rows
        vals = [str(row.get(c, ""))[:60] for c in columns]
        md_lines.append("| " + " | ".join(vals) + " |")
    if len(clean_rows) > 20:
        md_lines.append(f"\n... and {len(clean_rows) - 20} more rows")

    return envelope + "\n".join(md_lines)


def _structured_chart(title: str, rows: list[dict], chart_type: str = "auto", spl: str = "") -> str:
    """Build a structured result envelope for chart rendering."""
    if not rows:
        return json.dumps({"__structured": True, "format": "chart", "chart_type": "bar", "title": title, "columns": [], "rows": [], "total": 0})

    columns = list(rows[0].keys())
    columns = [c for c in columns if not c.startswith("_")]
    clean_rows = [{c: r.get(c, "") for c in columns} for r in rows]

    # Auto-detect chart type
    if chart_type == "auto":
        if any("time" in c.lower() or c == "_time" for c in rows[0].keys()):
            chart_type = "line"
        elif len(columns) == 2:
            chart_type = "pie"
        else:
            chart_type = "bar"

    envelope = json.dumps({
        "__structured": True,
        "format": "chart",
        "chart_type": chart_type,
        "title": title,
        "columns": columns,
        "rows": clean_rows,
        "total": len(clean_rows),
    })

    # Plain text summary for LLM
    md_lines = [f"\n\n**{title}** ({chart_type} chart, {len(clean_rows)} data points)\n"]
    md_lines.append("| " + " | ".join(columns) + " |")
    md_lines.append("| " + " | ".join("---" for _ in columns) + " |")
    for row in clean_rows[:10]:
        vals = [str(row.get(c, ""))[:40] for c in columns]
        md_lines.append("| " + " | ".join(vals) + " |")
    if len(clean_rows) > 10:
        md_lines.append(f"\n... and {len(clean_rows) - 10} more data points")

    return envelope + "\n".join(md_lines)


# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------

def execute_splunk_tool(cfg: dict, tool_name: str, args: dict) -> str:
    """Execute a Splunk tool and return the result string.

    *cfg* must contain keys ``splunk``, ``opensearch``, and ``ai`` with the
    respective configuration dicts.
    """
    splunk_config = cfg.get("splunk", {})
    opensearch_config = cfg.get("opensearch", {})

    try:
        if tool_name == "splunk_discover":
            return _execute_discover(opensearch_config, args)
        if tool_name == "splunk_search":
            return _execute_search(splunk_config, args)
        if tool_name == "splunk_stats":
            return _execute_stats(splunk_config, args)
        if tool_name == "splunk_saved_search":
            return _execute_saved_search(splunk_config, args)
        return f"Error: Unknown splunk tool: {tool_name}"
    except Exception as exc:
        logger.error("Splunk tool %s failed: %s", tool_name, exc, exc_info=True)
        return f"Error: {tool_name} failed — {exc}"


def _execute_discover(config: dict, args: dict) -> str:
    from src.splunk.opensearch_client import search_splunk_metadata, format_metadata_context

    query = args.get("query", "")
    if not query:
        return "Error: query is required for splunk_discover"

    top_k = args.get("top_k", 5)

    # Resolve logical index name → actual OpenSearch index name
    index_name = None
    requested = args.get("index", "")
    if requested:
        indexes = config.get("indexes", {})
        index_name = indexes.get(requested, requested)

    hits = search_splunk_metadata(config, query, top_k=top_k, index_name=index_name)
    return format_metadata_context(hits)


def _execute_search(config: dict, args: dict) -> str:
    from src.splunk.client import run_search_oneshot

    spl = args.get("spl", "")
    if not spl:
        return "Error: spl is required for splunk_search"

    rows = run_search_oneshot(
        config,
        spl,
        earliest=args.get("earliest"),
        latest=args.get("latest"),
        max_results=args.get("max_results"),
    )
    title = f"Splunk Search Results"
    return _structured_table(title, rows, spl=spl)


def _execute_stats(config: dict, args: dict) -> str:
    from src.splunk.client import run_search_oneshot

    spl = args.get("spl", "")
    if not spl:
        return "Error: spl is required for splunk_stats"

    rows = run_search_oneshot(
        config,
        spl,
        earliest=args.get("earliest"),
        latest=args.get("latest"),
        max_results=args.get("max_results"),
    )
    chart_type = args.get("chart_type", "auto")
    title = f"Splunk Stats"
    return _structured_chart(title, rows, chart_type=chart_type, spl=spl)


def _execute_saved_search(config: dict, args: dict) -> str:
    from src.splunk.client import list_saved_searches, run_saved_search

    name = args.get("name", "")
    if not name:
        # List mode
        searches = list_saved_searches(config)
        if not searches:
            return "No saved searches found."
        lines = ["## Available Saved Searches\n"]
        for s in searches:
            lines.append(f"- **{s['name']}**")
            if s.get("description"):
                lines.append(f"  {s['description']}")
            if s.get("search"):
                lines.append(f"  SPL: `{s['search'][:100]}`")
            lines.append("")
        return "\n".join(lines)

    # Run mode
    rows = run_saved_search(config, name)
    title = f"Saved Search: {name}"
    return _structured_table(title, rows)
