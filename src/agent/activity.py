"""
Activity indicators for autonomous code generation.
Shows progress similar to AI agents - spinners, step status, live updates.
"""

import os
from contextlib import contextmanager
from typing import Generator

# Use rich if available, fallback to plain print
_USE_RICH = bool(os.environ.get("AUTO_USE_RICH", "1") != "0")

try:
    from rich.console import Console
    from rich.spinner import Spinner
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
    from rich.status import Status
    _RICH_AVAILABLE = True
except ImportError:
    _RICH_AVAILABLE = False
    _USE_RICH = False

console = Console() if _RICH_AVAILABLE else None


def _plain_step(step: str, status: str = "running", detail: str = ""):
    """Plain text step output."""
    icon = "○" if status == "running" else "✓" if status == "done" else "✗"
    msg = f"  {icon} {step}"
    if detail:
        msg += f" — {detail}"
    print(msg)


def _plain_spinner(msg: str):
    """Plain message (no spinner)."""
    print(f"  ⟳ {msg}...")


@contextmanager
def step(name: str, detail: str = "") -> Generator[None, None, None]:
    """Context manager for a workflow step with spinner/status."""
    status_msg = f"{name}" + (f" — {detail}" if detail else "")
    if _USE_RICH and _RICH_AVAILABLE and console:
        with console.status(f"[bold cyan]⟳[/] {status_msg}", spinner="dots"):
            yield
        console.print(f"  [green]✓[/] {status_msg}")
    else:
        _plain_step(name, "running", detail)
        yield
        _plain_step(name, "done")


@contextmanager
def spinner(message: str) -> Generator[None, None, None]:
    """Context manager for long-running operation with spinner."""
    if _USE_RICH and _RICH_AVAILABLE and console:
        with console.status(f"[bold cyan]⟳[/] {message}", spinner="dots"):
            yield
        console.print(f"  [green]✓[/] {message}")
    else:
        _plain_spinner(message)
        yield
        _plain_step(message, "done")


def log_info(msg: str) -> None:
    """Log info message."""
    if _USE_RICH and _RICH_AVAILABLE and console:
        console.print(f"  [dim]{msg}[/]")
    else:
        print(f"  {msg}")


def log_success(msg: str) -> None:
    """Log success message."""
    if _USE_RICH and _RICH_AVAILABLE and console:
        console.print(f"  [green]✓[/] {msg}")
    else:
        print(f"  ✓ {msg}")


def log_error(msg: str) -> None:
    """Log error message."""
    if _USE_RICH and _RICH_AVAILABLE and console:
        console.print(f"  [red]✗[/] {msg}")
    else:
        print(f"  ✗ {msg}")


def log_warning(msg: str) -> None:
    """Log warning message."""
    if _USE_RICH and _RICH_AVAILABLE and console:
        console.print(f"  [yellow]![/] {msg}")
    else:
        print(f"  ! {msg}")


def log_agent_activity(
    turn: int,
    tool_name: str,
    args: dict,
    result_summary: str,
) -> None:
    """
    Log agent tool call for visibility (deep thinking / activity indicator).
    Shows what the agent is doing: read_file, grep, edit_file, run_command, etc.
    """
    arg_hint = _format_tool_arg_hint(tool_name, args)
    if result_summary:
        msg = f"[turn {turn + 1}] {tool_name}{arg_hint} → {result_summary}"
    else:
        msg = f"[turn {turn + 1}] {tool_name}{arg_hint}"
    if _USE_RICH and _RICH_AVAILABLE and console:
        console.print(f"  [dim cyan]▸[/] [dim]{msg}[/]")
    else:
        print(f"  ▸ {msg}")


def summarize_tool_result(result: str, tool_name: str) -> str:
    """Produce a short summary of tool result for activity log."""
    if not result:
        return ""
    if result.startswith("Error:"):
        return result[:60] + ("..." if len(result) > 60 else "")
    if tool_name == "read_file":
        lines = result.count("\n") + (1 if result and not result.endswith("\n") else 0)
        return f"{lines} lines"
    if tool_name == "grep":
        if "match" in result.lower() or ":" in result:
            n = result.count("\n") or 1
            return f"{n} line(s)"
        return "results"
    if tool_name == "list_dir":
        n = result.count("\n") + (1 if result and result != "(empty)" else 0)
        return f"{n} item(s)" if n > 0 else "empty"
    if tool_name == "find_files":
        if "No files" in result:
            return "0 files"
        n = result.count("\n") + 1
        return f"{n} files"
    if tool_name in ("write_file", "edit_file", "delete_file"):
        if "Wrote" in result:
            return result.split("Wrote")[-1].strip()[:40]
        if "Edited" in result:
            return "edited"
        if "Deleted" in result:
            return "deleted"
        return "ok"
    if tool_name == "run_command":
        if "exit code:" in result:
            for part in result.split():
                if part.startswith("exit") and ":" in part:
                    return part
            idx = result.rfind("exit code:")
            if idx >= 0:
                snippet = result[idx:idx + 20]
                return snippet.strip()
        return "run"
    if tool_name == "propose_change":
        if "Added" in result or "proposed" in result.lower():
            return "proposed"
        return result[:40] + ("..." if len(result) > 40 else "")
    return result[:50] + ("..." if len(result) > 50 else "")


def _format_tool_arg_hint(tool_name: str, args: dict) -> str:
    """Format a short hint from tool args for the activity log."""
    if not args:
        return ""
    if tool_name == "read_file":
        path = args.get("path", "")
        lines = ""
        if args.get("start_line") or args.get("end_line"):
            s, e = args.get("start_line"), args.get("end_line")
            lines = f" L{s}-{e}" if s or e else ""
        return f" {path}{lines}" if path else ""
    if tool_name == "grep":
        pat = args.get("pattern", "")
        return f" \"{pat[:40]}{'...' if len(pat) > 40 else ''}\"" if pat else ""
    if tool_name == "list_dir":
        path = args.get("path", "") or "."
        return f" {path}"
    if tool_name == "find_files":
        ext = args.get("extension", "")
        pat = args.get("pattern", "")
        return f" {ext or pat or ''}"
    if tool_name in ("write_file", "edit_file", "delete_file"):
        path = args.get("path", "")
        return f" {path}" if path else ""
    if tool_name == "run_command":
        cmd = args.get("command", "")
        short = cmd[:50] + "..." if len(cmd) > 50 else cmd
        return f" {short}"
    if tool_name == "update_memory":
        key = args.get("key", "")
        return f" {key}" if key else ""
    if tool_name == "propose_change":
        path = args.get("path", "")
        action = args.get("action", "")
        return f" {action} {path}" if path else ""
    return ""


def header(title: str, subtitle: str = "") -> None:
    """Print workflow header."""
    if _USE_RICH and _RICH_AVAILABLE and console:
        from rich.rule import Rule
        console.print()
        console.print(Panel(f"[bold]{title}[/]\n{subtitle}" if subtitle else f"[bold]{title}[/]",
                           border_style="blue"))
        console.print()
    else:
        print(f"\n{'='*50}")
        print(f"  {title}")
        if subtitle:
            print(f"  {subtitle}")
        print(f"{'='*50}\n")


def workflow_summary(steps: list[tuple[str, str]]) -> None:
    """Print workflow step summary (e.g., at end)."""
    if _USE_RICH and _RICH_AVAILABLE and console:
        table = Table(title="Workflow Summary")
        table.add_column("Step", style="cyan")
        table.add_column("Status", style="green")
        for name, status in steps:
            table.add_row(name, status)
        console.print(table)
    else:
        print("\n--- Workflow Summary ---")
        for name, status in steps:
            print(f"  {name}: {status}")
        print()
