"""
Rich terminal rendering for agent plan mode.

Shows a summary table and colored diffs for each proposed change,
then prompts the user for approval.  Falls back to plain text when
Rich is not available (same pattern as activity.py).
"""

import os
from typing import Optional

from src.agent.plan import ChangePlan, ChangeAction, generate_diff

# Use rich if available, fallback to plain print
_USE_RICH = bool(os.environ.get("AUTO_USE_RICH", "1") != "0")

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich.prompt import Prompt
    _RICH_AVAILABLE = True
except ImportError:
    _RICH_AVAILABLE = False
    _USE_RICH = False

_console: Optional["Console"] = Console() if _RICH_AVAILABLE else None


# ---------------------------------------------------------------------------
# Diff colouring helpers
# ---------------------------------------------------------------------------

_ACTION_STYLES = {
    ChangeAction.create: ("green", "CREATE"),
    ChangeAction.modify: ("yellow", "MODIFY"),
    ChangeAction.delete: ("red", "DELETE"),
}


def _colorize_diff_rich(diff_text: str) -> Text:
    """Return a Rich Text with per-line diff colours."""
    text = Text()
    for line in diff_text.splitlines(keepends=True):
        stripped = line.rstrip("\n")
        if stripped.startswith("+++") or stripped.startswith("---"):
            text.append(stripped + "\n", style="cyan")
        elif stripped.startswith("@@"):
            text.append(stripped + "\n", style="magenta")
        elif stripped.startswith("+"):
            text.append(stripped + "\n", style="green")
        elif stripped.startswith("-"):
            text.append(stripped + "\n", style="red")
        else:
            text.append(stripped + "\n")
    return text


def _colorize_diff_plain(diff_text: str) -> str:
    """Return plain diff text (no ANSI), for fallback."""
    return diff_text


def _count_lines(diff_text: str) -> tuple[int, int]:
    """Count additions (+) and deletions (-) in a unified diff."""
    added = 0
    removed = 0
    for line in diff_text.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return added, removed


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_plan(plan: ChangePlan, repo_root: str) -> None:
    """Render the full plan: summary table + per-file colored diffs."""
    from pathlib import Path
    root = Path(repo_root)

    if plan.is_empty:
        _print("No changes proposed.")
        return

    # Pre-compute diffs
    diffs: list[tuple[str, ChangeAction, str, str]] = []  # (path, action, desc, diff)
    for change in plan.changes:
        diff_text = generate_diff(root, change)
        diffs.append((change.path, change.action, change.description, diff_text))

    # --- Summary table ---
    if _USE_RICH and _RICH_AVAILABLE and _console:
        table = Table(title="Proposed Changes", show_lines=True)
        table.add_column("File", style="bold")
        table.add_column("Action", justify="center")
        table.add_column("Description")
        table.add_column("+/-", justify="right")

        for path, action, desc, diff_text in diffs:
            style, label = _ACTION_STYLES.get(action, ("white", action.value.upper()))
            added, removed = _count_lines(diff_text)
            pm = f"[green]+{added}[/] / [red]-{removed}[/]"
            table.add_row(path, f"[{style}]{label}[/{style}]", desc, pm)

        _console.print()
        _console.print(Panel(table, border_style="blue", title="Plan Summary"))
    else:
        print("\n--- Proposed Changes ---")
        for path, action, desc, diff_text in diffs:
            _, label = _ACTION_STYLES.get(action, ("", action.value.upper()))
            added, removed = _count_lines(diff_text)
            print(f"  [{label}] {path}  (+{added}/-{removed})  {desc}")
        print()

    # --- Per-file diffs ---
    for path, action, desc, diff_text in diffs:
        if not diff_text:
            continue
        if _USE_RICH and _RICH_AVAILABLE and _console:
            colored = _colorize_diff_rich(diff_text)
            style, label = _ACTION_STYLES.get(action, ("white", action.value.upper()))
            _console.print(Panel(
                colored,
                title=f"[bold]{path}[/bold]  [{style}]{label}[/{style}]",
                border_style=style,
                expand=True,
            ))
        else:
            _, label = _ACTION_STYLES.get(action, ("", action.value.upper()))
            print(f"\n--- {path} ({label}) ---")
            print(_colorize_diff_plain(diff_text))


def prompt_approval() -> str:
    """Prompt user to approve, reject, or modify the plan.

    Returns one of: "approve", "reject", "modify".
    """
    if _USE_RICH and _RICH_AVAILABLE and _console:
        _console.print()
        choice = Prompt.ask(
            "[bold]Apply changes?[/bold]",
            choices=["approve", "reject", "modify"],
            default="approve",
        )
        return choice
    else:
        print("\nApply changes? [approve/reject/modify] (default: approve): ", end="")
        raw = input().strip().lower()
        if raw in ("approve", "reject", "modify"):
            return raw
        return "approve"


def _print(msg: str) -> None:
    if _USE_RICH and _RICH_AVAILABLE and _console:
        _console.print(msg)
    else:
        print(msg)
