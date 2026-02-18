"""
Execution tracing for the agent loop — inspired by Agent Lightning's span model.

Captures structured spans for every LLM call, tool execution, context management
event, and session lifecycle.  Traces are persisted as JSON and can feed:
  - Analytics dashboards (which tools succeed, failure patterns)
  - Automatic Prompt Optimization (APO)
  - Future RL training pipelines (Agent Lightning compatible)

Three-layer architecture (mirrors Agent Lightning):
  1. **Span collection** — lightweight ``TraceCollector`` emits spans during execution
  2. **FileTraceStore** — persists traces to ``~/.code-autonomy/traces/``
  3. **AgentTrace** — structured record with spans + aggregate metrics
"""

import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Span — single event in the agent's execution
# ---------------------------------------------------------------------------

SPAN_LLM_CALL = "llm_call"
SPAN_TOOL_CALL = "tool_call"
SPAN_CONTEXT_MGMT = "context_mgmt"
SPAN_STUCK_DETECT = "stuck_detection"
SPAN_SESSION = "session"
SPAN_GCC_COMMAND = "gcc_command"


@dataclass
class Span:
    """One event in the agent's execution trace.

    Compatible with Agent Lightning's state-action-reward representation:
    each LLM call is an *action*, each tool call is a *state transition*,
    and ``reward`` captures the outcome signal.
    """

    span_id: str
    span_type: str  # SPAN_* constants
    name: str  # tool name, model name, event description
    turn: int  # agent loop turn (0-based)
    start_time: float  # time.time()
    end_time: float = 0.0
    duration_ms: float = 0.0

    # Inputs (sanitized — no file contents or secrets)
    inputs: dict = field(default_factory=dict)

    # Outputs (summarized)
    output_summary: str = ""
    output_chars: int = 0

    # Outcome
    success: bool = True
    error: str = ""

    # Reward signal (Agent Lightning compatible)
    # +1.0 = good, 0.0 = neutral, -1.0 = bad
    reward: float = 0.0

    # Extra metadata (model, tokens, custom)
    metadata: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# AgentTrace — full session record
# ---------------------------------------------------------------------------

@dataclass
class AgentTrace:
    """Complete execution trace for one agent session.

    Contains all spans plus aggregate metrics for analysis and training.
    """

    trace_id: str
    repo_id: str = ""
    repo_url: str = ""
    started_at: str = ""  # ISO timestamp
    ended_at: str = ""
    total_duration_ms: float = 0.0
    model: str = ""
    requirements_summary: str = ""  # first 200 chars

    # Session outcome
    success: bool = False
    turns_used: int = 0
    files_changed: list = field(default_factory=list)
    summary: str = ""

    # All spans
    spans: list = field(default_factory=list)  # list of Span dicts

    # Aggregate metrics
    metrics: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "AgentTrace":
        return cls(
            trace_id=d.get("trace_id", ""),
            repo_id=d.get("repo_id", ""),
            repo_url=d.get("repo_url", ""),
            started_at=d.get("started_at", ""),
            ended_at=d.get("ended_at", ""),
            total_duration_ms=d.get("total_duration_ms", 0.0),
            model=d.get("model", ""),
            requirements_summary=d.get("requirements_summary", ""),
            success=d.get("success", False),
            turns_used=d.get("turns_used", 0),
            files_changed=d.get("files_changed", []),
            summary=d.get("summary", ""),
            spans=d.get("spans", []),
            metrics=d.get("metrics", {}),
        )


# ---------------------------------------------------------------------------
# TraceCollector — accumulates spans during an agent session
# ---------------------------------------------------------------------------

def _sanitize_tool_args(tool_name: str, args: dict) -> dict:
    """Sanitize tool arguments for tracing — strip large content, keep metadata."""
    safe = {}
    for k, v in args.items():
        if k == "content":
            # write_file: log length, not content
            safe[k] = f"<{len(v)} chars>" if isinstance(v, str) else str(v)
        elif k == "old_string":
            safe[k] = f"<{len(v)} chars>" if isinstance(v, str) else str(v)
        elif k == "new_string":
            safe[k] = f"<{len(v)} chars>" if isinstance(v, str) else str(v)
        elif isinstance(v, str) and len(v) > 500:
            safe[k] = v[:500] + "..."
        else:
            safe[k] = v
    return safe


def _summarize_output(result: str, max_len: int = 200) -> str:
    """Create a brief summary of tool output for the span."""
    if not result:
        return ""
    # Capture error messages verbatim (they're short and important)
    if result.startswith("Error:"):
        return result[:max_len]
    # For commands, capture exit code
    if "[exit code:" in result:
        idx = result.rfind("[exit code:")
        exit_part = result[idx:idx + 30]
        prefix = result[:max(0, max_len - len(exit_part) - 4)]
        return f"{prefix}... {exit_part}" if len(result) > max_len else result[:max_len]
    if len(result) <= max_len:
        return result
    return result[:max_len] + "..."


class TraceCollector:
    """Collects spans during an agent session.

    Usage::

        collector = TraceCollector(repo_id="abc", model="gpt-4o", ...)
        sid = collector.start_span(SPAN_TOOL_CALL, "read_file", turn=0, inputs={...})
        collector.end_span(sid, output_summary="200 lines", success=True, reward=0.5)
        ...
        trace = collector.finalize(success=True, turns_used=10, ...)
    """

    def __init__(
        self,
        repo_id: str = "",
        repo_url: str = "",
        model: str = "",
        requirements: str = "",
    ) -> None:
        self.trace_id = uuid.uuid4().hex[:16]
        self.repo_id = repo_id
        self.repo_url = repo_url
        self.model = model
        self.requirements_summary = requirements[:200]
        self.started_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._start_time = time.time()
        self._spans: list[Span] = []
        self._active: dict[str, Span] = {}  # span_id → in-progress span

    def start_span(
        self,
        span_type: str,
        name: str,
        turn: int,
        inputs: Optional[dict] = None,
        metadata: Optional[dict] = None,
    ) -> str:
        """Begin a new span. Returns span_id for later ``end_span()``."""
        span = Span(
            span_id=uuid.uuid4().hex[:12],
            span_type=span_type,
            name=name,
            turn=turn,
            start_time=time.time(),
            inputs=inputs or {},
            metadata=metadata or {},
        )
        self._active[span.span_id] = span
        return span.span_id

    def end_span(
        self,
        span_id: str,
        output_summary: str = "",
        output_chars: int = 0,
        success: bool = True,
        error: str = "",
        reward: float = 0.0,
        metadata: Optional[dict] = None,
    ) -> None:
        """Complete an active span with results."""
        span = self._active.pop(span_id, None)
        if span is None:
            logger.warning("end_span called for unknown span_id: %s", span_id)
            return
        span.end_time = time.time()
        span.duration_ms = (span.end_time - span.start_time) * 1000
        span.output_summary = output_summary
        span.output_chars = output_chars
        span.success = success
        span.error = error
        span.reward = reward
        if metadata:
            span.metadata.update(metadata)
        self._spans.append(span)

    def add_event(
        self,
        span_type: str,
        name: str,
        turn: int,
        inputs: Optional[dict] = None,
        success: bool = True,
        error: str = "",
        reward: float = 0.0,
        metadata: Optional[dict] = None,
    ) -> None:
        """Record a point-in-time event (no start/end, instant span)."""
        now = time.time()
        span = Span(
            span_id=uuid.uuid4().hex[:12],
            span_type=span_type,
            name=name,
            turn=turn,
            start_time=now,
            end_time=now,
            duration_ms=0.0,
            inputs=inputs or {},
            success=success,
            error=error,
            reward=reward,
            metadata=metadata or {},
        )
        self._spans.append(span)

    def _compute_metrics(self) -> dict:
        """Compute aggregate metrics from collected spans."""
        metrics: dict[str, Any] = {
            "total_spans": len(self._spans),
            "llm_calls": 0,
            "tool_calls": 0,
            "gcc_commands": 0,
            "errors": 0,
            "total_llm_duration_ms": 0.0,
            "total_tool_duration_ms": 0.0,
            "total_tokens_est": 0,
            "tool_breakdown": {},
            "reward_total": 0.0,
        }

        for span in self._spans:
            if span.span_type == SPAN_LLM_CALL:
                metrics["llm_calls"] += 1
                metrics["total_llm_duration_ms"] += span.duration_ms
                metrics["total_tokens_est"] += span.metadata.get("tokens_est", 0)
            elif span.span_type == SPAN_GCC_COMMAND:
                metrics["gcc_commands"] += 1
                metrics["total_tool_duration_ms"] += span.duration_ms
            elif span.span_type == SPAN_TOOL_CALL:
                metrics["tool_calls"] += 1
                metrics["total_tool_duration_ms"] += span.duration_ms
                tool_name = span.name
                if tool_name not in metrics["tool_breakdown"]:
                    metrics["tool_breakdown"][tool_name] = {
                        "count": 0, "errors": 0, "total_ms": 0.0,
                    }
                metrics["tool_breakdown"][tool_name]["count"] += 1
                metrics["tool_breakdown"][tool_name]["total_ms"] += span.duration_ms
                if not span.success:
                    metrics["tool_breakdown"][tool_name]["errors"] += 1

            if not span.success:
                metrics["errors"] += 1
            metrics["reward_total"] += span.reward

        return metrics

    def finalize(
        self,
        success: bool,
        turns_used: int,
        files_changed: list,
        summary: str,
    ) -> AgentTrace:
        """Finalize the trace with session outcome. Returns the complete trace."""
        ended_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        total_ms = (time.time() - self._start_time) * 1000

        # Close any orphaned spans
        for span_id in list(self._active.keys()):
            self.end_span(span_id, output_summary="(orphaned)", success=False, error="span not closed")

        metrics = self._compute_metrics()
        metrics["session_reward"] = 1.0 if success else -1.0

        return AgentTrace(
            trace_id=self.trace_id,
            repo_id=self.repo_id,
            repo_url=self.repo_url,
            started_at=self.started_at,
            ended_at=ended_at,
            total_duration_ms=total_ms,
            model=self.model,
            requirements_summary=self.requirements_summary,
            success=success,
            turns_used=turns_used,
            files_changed=files_changed,
            summary=summary,
            spans=[asdict(s) for s in self._spans],
            metrics=metrics,
        )


# ---------------------------------------------------------------------------
# FileTraceStore — persistence
# ---------------------------------------------------------------------------

class FileTraceStore:
    """Stores traces as JSON files in ``~/.code-autonomy/traces/``."""

    def __init__(self, storage_dir: str = "") -> None:
        if storage_dir:
            self._dir = Path(os.path.expanduser(storage_dir))
        else:
            self._dir = Path.home() / ".code-autonomy" / "traces"

    def save(self, trace: AgentTrace) -> Path:
        """Save trace to a JSON file. Returns the file path."""
        self._dir.mkdir(parents=True, exist_ok=True)
        filename = f"{trace.trace_id}_{trace.repo_id[:8]}.json"
        path = self._dir / filename
        try:
            data = trace.to_dict()
            path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        except (TypeError, ValueError) as ser_err:
            # Fallback: serialize with default=str for non-JSON types
            logger.warning("Trace serialization issue (%s), retrying with default=str", ser_err)
            path.write_text(json.dumps(trace.to_dict(), indent=2, default=str), encoding="utf-8")
        logger.info("Trace saved to %s", path)
        return path

    def load(self, trace_id: str) -> Optional[AgentTrace]:
        """Load a trace by ID (searches for matching file)."""
        if not self._dir.exists():
            return None
        for f in self._dir.iterdir():
            if f.name.startswith(trace_id) and f.suffix == ".json":
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                    return AgentTrace.from_dict(data)
                except Exception as exc:
                    logger.warning("Failed to load trace %s: %s", f, exc)
                    return None
        return None

    def list_traces(self, repo_id: str = "", limit: int = 50) -> list[dict]:
        """List recent traces, optionally filtered by repo_id.

        Returns summary dicts (not full traces) sorted by date descending.
        """
        if not self._dir.exists():
            return []

        summaries = []
        for f in sorted(self._dir.iterdir(), reverse=True):
            if not f.suffix == ".json":
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if repo_id and data.get("repo_id") != repo_id:
                    continue
                summaries.append({
                    "trace_id": data.get("trace_id", ""),
                    "repo_id": data.get("repo_id", ""),
                    "started_at": data.get("started_at", ""),
                    "model": data.get("model", ""),
                    "success": data.get("success", False),
                    "turns_used": data.get("turns_used", 0),
                    "summary": data.get("summary", "")[:100],
                    "metrics": data.get("metrics", {}),
                })
                if len(summaries) >= limit:
                    break
            except Exception:
                continue
        return summaries


# ---------------------------------------------------------------------------
# Helper — get trace store from config
# ---------------------------------------------------------------------------

def get_trace_store(config: Optional[dict] = None) -> FileTraceStore:
    """Create a trace store from config. Currently only file backend."""
    if config is None:
        return FileTraceStore()
    tcfg = config.get("tracing", {})
    storage_dir = tcfg.get("storage_dir", "")
    return FileTraceStore(storage_dir)


def is_tracing_enabled(config: Optional[dict] = None) -> bool:
    """Check if tracing is enabled in config."""
    if config is None:
        return True  # enabled by default
    return config.get("tracing", {}).get("enabled", True)
