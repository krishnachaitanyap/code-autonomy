"""
Code search / grep across repository files.
Similar to Cursor's grep - search patterns in Python and Java files.
"""

import re
from pathlib import Path
from typing import Optional

from src.constants import SEARCH_EXTENSIONS, SKIP_DIRS


def grep(
    repo_path: str,
    pattern: str,
    *,
    file_pattern: Optional[str] = None,
    extensions: Optional[set[str]] = None,
    case_sensitive: bool = False,
    max_results: int = 500,
    context_lines: int = 2,
) -> list[dict]:
    """
    Search for pattern across code files (grep-like).

    Returns list of:
        {"path": str, "line_num": int, "line": str, "context_before": list, "context_after": list}
    """
    repo = Path(repo_path)
    if not repo.exists():
        return []

    ext_filter = extensions or SEARCH_EXTENSIONS
    try:
        regex = re.compile(pattern, 0 if case_sensitive else re.IGNORECASE)
    except re.error:
        # Fallback to literal search
        regex = re.compile(re.escape(pattern), 0 if case_sensitive else re.IGNORECASE)

    results: list[dict] = []

    for f in repo.rglob("*"):
        if not f.is_file():
            continue
        if f.suffix not in ext_filter:
            continue
        if any(p in SKIP_DIRS for p in f.relative_to(repo).parts):
            continue
        if file_pattern and not re.search(file_pattern, str(f), re.I):
            continue

        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue

        for i, line in enumerate(lines):
            if regex.search(line):
                rel_path = str(f.relative_to(repo))
                ctx_before = lines[max(0, i - context_lines) : i] if context_lines else []
                ctx_after = lines[i + 1 : i + 1 + context_lines] if context_lines else []
                results.append({
                    "path": rel_path,
                    "line_num": i + 1,
                    "line": line,
                    "context_before": ctx_before,
                    "context_after": ctx_after,
                })
                if len(results) >= max_results:
                    return results

    return results


def grep_files(
    repo_path: str,
    pattern: str,
    *,
    extensions: Optional[set[str]] = None,
) -> list[str]:
    """Return list of file paths containing the pattern."""
    results = grep(repo_path, pattern, extensions=extensions, max_results=10000)
    return sorted(set(r["path"] for r in results))


def format_grep_results(results: list[dict]) -> str:
    """Format grep results for AI context (similar to grep -n output)."""
    if not results:
        return "No matches found."

    lines = []
    for r in results:
        path, ln, line = r["path"], r["line_num"], r["line"]
        lines.append(f"{path}:{ln}: {line.strip()}")
        if r.get("context_before"):
            for c in r["context_before"]:
                lines.append(f"  | {c}")
        if r.get("context_after"):
            for c in r["context_after"]:
                lines.append(f"  | {c}")
    return "\n".join(lines)


def search_codebase(
    repo_path: str,
    patterns: list[str],
    extensions: Optional[set[str]] = None,
) -> dict[str, str]:
    """
    Run multiple grep patterns and return combined context.
    Useful for gathering relevant files before AI analysis.
    """
    combined: dict[str, list[dict]] = {}
    for pattern in patterns:
        results = grep(repo_path, pattern, extensions=extensions)
        for r in results:
            path = r["path"]
            if path not in combined:
                combined[path] = []
            combined[path].append(r)

    output = {}
    for path, results in sorted(combined.items()):
        output[path] = format_grep_results(results)
    return output
