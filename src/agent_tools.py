"""
Agent tools for Cursor-like capabilities.
read_file, grep, list_dir, find_files - AI can call these to build context iteratively.
"""

import json
from pathlib import Path
from typing import Any, Optional

from src.code_search import grep, format_grep_results
from src.constants import SEARCH_EXTENSIONS, SKIP_DIRS


def _safe_path(repo_root: Path, requested: str) -> Optional[Path]:
    """Resolve path, ensure it stays within repo (no path traversal)."""
    requested = requested.strip().lstrip("/")
    if not requested:
        return repo_root
    full = (repo_root / requested).resolve()
    try:
        full.relative_to(repo_root.resolve())
    except ValueError:
        return None
    return full


def run_read_file(repo_root: Path, path: str, start_line: Optional[int] = None, end_line: Optional[int] = None) -> str:
    """
    Read file content, optionally a line range (1-based inclusive).
    Returns file content or error message.
    """
    target = _safe_path(repo_root, path)
    if not target or not target.exists():
        return f"Error: File not found or outside repo: {path}"
    if not target.is_file():
        return f"Error: Not a file: {path}"
    try:
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as e:
        return f"Error reading file: {e}"
    if start_line is not None or end_line is not None:
        s = max(0, (start_line or 1) - 1)
        e = end_line or len(lines)
        lines = lines[s:e]
    return "\n".join(lines)


def run_grep(repo_root: Path, pattern: str, path_filter: Optional[str] = None, context_lines: int = 2, max_results: int = 100) -> str:
    """Search for pattern in code files. path_filter is optional glob/regex for file path."""
    results = grep(
        str(repo_root),
        pattern,
        file_pattern=path_filter,
        context_lines=context_lines,
        max_results=max_results,
    )
    return format_grep_results(results)


def run_list_dir(repo_root: Path, path: str) -> str:
    """List directory contents (files and subdirs)."""
    target = _safe_path(repo_root, path)
    if not target or not target.exists():
        return f"Error: Directory not found or outside repo: {path}"
    if not target.is_dir():
        return f"Error: Not a directory: {path}"
    items = []
    for p in sorted(target.iterdir()):
        name = p.name
        if name.startswith(".") and name not in (".gitignore",):
            continue
        if p.is_dir():
            items.append(f"  [dir]  {name}/")
        else:
            items.append(f"  [file] {name}")
    return "\n".join(items) if items else "(empty)"


def run_find_files(repo_root: Path, extension: Optional[str] = None, pattern: Optional[str] = None) -> str:
    """Find files by extension (e.g. .java) or name pattern (glob). Returns list of relative paths."""
    target = Path(repo_root)
    if not target.exists():
        return "Error: Repo path not found"
    found = []
    ext_filter = {extension} if extension else SEARCH_EXTENSIONS
    for f in target.rglob("*"):
        if not f.is_file():
            continue
        if any(p in SKIP_DIRS for p in f.relative_to(target).parts):
            continue
        if extension and f.suffix != extension:
            continue
        if not extension and f.suffix not in SEARCH_EXTENSIONS:
            continue
        rel = str(f.relative_to(target))
        if pattern:
            import fnmatch
            if not fnmatch.fnmatch(rel, pattern):
                continue
        found.append(rel)
    found.sort()
    return "\n".join(found[:200]) if found else "No files found"


# OpenAI tool definitions (function calling format)
AGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the contents of a file. Use path relative to repo root. Optionally specify start_line and end_line (1-based) to read a range.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative file path (e.g., src/main/java/demo/App.java)"},
                    "start_line": {"type": "integer", "description": "Optional start line (1-based)"},
                    "end_line": {"type": "integer", "description": "Optional end line (1-based)"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "grep",
            "description": "Search for a regex pattern across code files. Returns matching lines with context.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex pattern to search for"},
                    "path_filter": {"type": "string", "description": "Optional file path filter (regex)"},
                    "context_lines": {"type": "integer", "description": "Lines of context around matches (default 2)"},
                },
                "required": ["pattern"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_dir",
            "description": "List contents of a directory. Use path relative to repo root. Use empty string for repo root.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative directory path (empty for repo root)"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_files",
            "description": "Find files by extension or name pattern. Returns list of relative paths.",
            "parameters": {
                "type": "object",
                "properties": {
                    "extension": {"type": "string", "description": "File extension (e.g., .java, .py)"},
                    "pattern": {"type": "string", "description": "Optional glob pattern for file name"},
                },
            },
        },
    },
]


def execute_tool(repo_root: Path, tool_name: str, args: dict) -> str:
    """Execute a tool and return the result string."""
    repo = Path(repo_root)
    if tool_name == "read_file":
        return run_read_file(repo, args.get("path", ""), args.get("start_line"), args.get("end_line"))
    if tool_name == "grep":
        return run_grep(repo, args.get("pattern", ""), args.get("path_filter"), args.get("context_lines", 2))
    if tool_name == "list_dir":
        return run_list_dir(repo, args.get("path", ""))
    if tool_name == "find_files":
        return run_find_files(repo, args.get("extension"), args.get("pattern"))
    return f"Unknown tool: {tool_name}"
