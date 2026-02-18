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


def log_llm_stats(stats) -> None:
    """Print LLM usage statistics after an agent run.

    Args:
        stats: An LLMUsageStats instance (or None).
    """
    if stats is None or stats.num_calls == 0:
        return

    categories = getattr(stats, "categories", None)
    has_categories = categories and len(categories) > 1

    if _USE_RICH and _RICH_AVAILABLE and console:
        table = Table(title="LLM Usage", border_style="dim", show_header=False, padding=(0, 1))
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="bold", justify="right")
        table.add_row("Calls", f"{stats.num_calls:,}")
        if has_categories:
            for cat in categories:
                table.add_row(f"  {cat}", f"{stats.calls_by_category(cat):,}")
        table.add_row("Prompt tokens", f"{stats.total_prompt_tokens:,}")
        table.add_row("Completion tokens", f"{stats.total_completion_tokens:,}")
        table.add_row("Total tokens", f"{stats.total_tokens:,}")
        if has_categories:
            for cat in categories:
                table.add_row(f"  {cat}", f"{stats.tokens_by_category(cat):,}")
        console.print(table)
    else:
        print(f"\n{'── LLM Usage ─':─<44}")
        print(f"  Calls:             {stats.num_calls:,}")
        if has_categories:
            for cat in categories:
                print(f"    {cat + ':':20s} {stats.calls_by_category(cat):,}")
        print(f"  Prompt tokens:     {stats.total_prompt_tokens:,}")
        print(f"  Completion tokens: {stats.total_completion_tokens:,}")
        print(f"  Total tokens:      {stats.total_tokens:,}")
        if has_categories:
            for cat in categories:
                print(f"    {cat + ':':20s} {stats.tokens_by_category(cat):,}")
        print(f"{'─' * 44}")


def log_checkpoint_saved(checkpoint) -> None:
    """Display a summary panel when an incomplete run checkpoint is saved.

    Args:
        checkpoint: A Checkpoint instance (from knowledge.py).
    """
    if checkpoint is None:
        return

    files = getattr(checkpoint, "files_changed", []) or []
    turns_used = getattr(checkpoint, "turns_used", 0)
    max_turns = getattr(checkpoint, "max_turns", 0)

    if _USE_RICH and _RICH_AVAILABLE and console:
        lines = [
            f"[bold yellow]Turns used:[/] {turns_used}/{max_turns}",
            f"[bold yellow]Files changed:[/] {len(files)}",
        ]
        for f in files[:10]:
            lines.append(f"  - {f}")
        if len(files) > 10:
            lines.append(f"  ... and {len(files) - 10} more")
        lines.append("")
        lines.append("[bold]Resume with:[/] --resume")
        content = "\n".join(lines)
        console.print(Panel(
            content,
            title="[bold red]INCOMPLETE RUN — CHECKPOINT SAVED[/]",
            border_style="red",
        ))
    else:
        print(f"\n{'─' * 50}")
        print("  INCOMPLETE RUN — CHECKPOINT SAVED")
        print(f"{'─' * 50}")
        print(f"  Turns used: {turns_used}/{max_turns}")
        print(f"  Files changed: {len(files)}")
        for f in files[:10]:
            print(f"    - {f}")
        if len(files) > 10:
            print(f"    ... and {len(files) - 10} more")
        print(f"  Resume with: --resume")
        print(f"{'─' * 50}")


def _classify_command(command: str) -> str:
    """Classify a shell command into a human-readable category."""
    cmd = command.strip().lower()
    # Maven
    if "mvn " in cmd or "./mvnw " in cmd or "mvnw " in cmd:
        # Split into tokens to check Maven goals (ignore flags like -DskipTests)
        goals = [t for t in cmd.split() if not t.startswith("-") and t not in ("mvn", "./mvnw", "mvnw")]
        if "test" in goals:
            return "Running Maven tests"
        if "compile" in goals:
            return "Running Maven compile"
        if "package" in goals:
            return "Running Maven package"
        if "install" in goals:
            return "Running Maven install"
        if "clean" in goals and len(goals) == 1:
            return "Running Maven clean"
        return "Running Maven build"
    # Gradle
    if "gradle " in cmd or "./gradlew " in cmd or "gradlew " in cmd:
        goals = [t for t in cmd.split() if not t.startswith("-") and t not in ("gradle", "./gradlew", "gradlew")]
        if "test" in goals:
            return "Running Gradle tests"
        if "build" in goals:
            return "Running Gradle build"
        if "compile" in goals or "compileJava" in goals:
            return "Running Gradle compile"
        return "Running Gradle task"
    # Python
    if "pytest" in cmd or "python -m pytest" in cmd:
        return "Running pytest"
    if "python -m unittest" in cmd or "unittest" in cmd:
        return "Running unittest"
    # Node
    if "npm test" in cmd or "npx jest" in cmd or "npm run test" in cmd:
        return "Running npm tests"
    if "npm " in cmd:
        return "Running npm command"
    # Generic test/build detection
    if "test" in cmd:
        return "Running tests"
    if "build" in cmd or "compile" in cmd:
        return "Running build"
    return "Running command"


def log_agent_tool_start(turn: int, tool_name: str, args: dict) -> None:
    """Log when a potentially long-running tool starts (before execution).

    Only emits a message for run_command so the user can see what the agent
    is doing during long builds/tests.
    """
    if tool_name != "run_command":
        return
    command = args.get("command", "")
    category = _classify_command(command)
    short_cmd = command[:80] + ("..." if len(command) > 80 else "")
    msg = f"[turn {turn + 1}] {category}: {short_cmd}"
    if _USE_RICH and _RICH_AVAILABLE and console:
        console.print(f"  [bold yellow]⏳[/] [dim]{msg}[/]")
    else:
        print(f"  ⏳ {msg}")


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
    if tool_name.startswith("gcc_"):
        return result[:60] + ("..." if len(result) > 60 else "")
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
    if tool_name == "gcc_commit":
        return f" {args.get('summary', '')[:40]}"
    if tool_name == "gcc_branch":
        return f" {args.get('name', '')}"
    if tool_name == "gcc_merge":
        return f" {args.get('branch_name', '')}"
    if tool_name == "gcc_context":
        return f" {args.get('scope', 'status')}"
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
