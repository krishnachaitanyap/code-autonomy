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
