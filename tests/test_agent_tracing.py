"""Tests for src.agent.tracing — execution tracing module."""

import json
import time
from pathlib import Path

import pytest

from src.agent.tracing import (
    Span,
    AgentTrace,
    TraceCollector,
    FileTraceStore,
    _sanitize_tool_args,
    _summarize_output,
    is_tracing_enabled,
    get_trace_store,
    SPAN_LLM_CALL,
    SPAN_TOOL_CALL,
    SPAN_CONTEXT_MGMT,
    SPAN_STUCK_DETECT,
    SPAN_SESSION,
)


# ---------------------------------------------------------------------------
# _sanitize_tool_args
# ---------------------------------------------------------------------------

class TestSanitizeToolArgs:
    def test_strips_content_field(self):
        args = {"path": "foo.py", "content": "x" * 5000}
        safe = _sanitize_tool_args("write_file", args)
        assert safe["path"] == "foo.py"
        assert "<5000 chars>" in safe["content"]

    def test_strips_old_new_string(self):
        args = {"path": "f.py", "old_string": "abc" * 100, "new_string": "xyz" * 200}
        safe = _sanitize_tool_args("edit_file", args)
        assert "<300 chars>" in safe["old_string"]
        assert "<600 chars>" in safe["new_string"]

    def test_preserves_short_args(self):
        args = {"command": "pytest -v", "timeout": 120}
        safe = _sanitize_tool_args("run_command", args)
        assert safe == args

    def test_truncates_long_string_values(self):
        args = {"pattern": "a" * 1000}
        safe = _sanitize_tool_args("grep", args)
        assert safe["pattern"].endswith("...")
        assert len(safe["pattern"]) == 503  # 500 + "..."


# ---------------------------------------------------------------------------
# _summarize_output
# ---------------------------------------------------------------------------

class TestSummarizeOutput:
    def test_short_output_unchanged(self):
        assert _summarize_output("OK", 200) == "OK"

    def test_error_preserved(self):
        msg = "Error: File not found: missing.py"
        assert _summarize_output(msg, 200) == msg

    def test_exit_code_captured(self):
        output = "x" * 500 + "\n[exit code: 1]"
        result = _summarize_output(output, 200)
        assert "[exit code: 1]" in result

    def test_long_output_truncated(self):
        output = "x" * 1000
        result = _summarize_output(output, 200)
        assert len(result) <= 210  # 200 + "..."
        assert result.endswith("...")

    def test_empty_output(self):
        assert _summarize_output("", 200) == ""


# ---------------------------------------------------------------------------
# TraceCollector — span lifecycle
# ---------------------------------------------------------------------------

class TestTraceCollector:
    def test_start_and_end_span(self):
        c = TraceCollector(repo_id="abc", model="gpt-4o", requirements="test req")
        sid = c.start_span(SPAN_TOOL_CALL, "read_file", turn=0, inputs={"path": "a.py"})
        assert sid  # non-empty
        time.sleep(0.01)
        c.end_span(sid, output_summary="100 lines", output_chars=500, success=True, reward=0.5)

        # Span should be in the list now
        assert len(c._spans) == 1
        span = c._spans[0]
        assert span.name == "read_file"
        assert span.success is True
        assert span.reward == 0.5
        assert span.duration_ms > 0

    def test_add_event(self):
        c = TraceCollector(repo_id="abc")
        c.add_event(SPAN_STUCK_DETECT, "stuck_3x", turn=5, reward=-1.0)
        assert len(c._spans) == 1
        assert c._spans[0].span_type == SPAN_STUCK_DETECT
        assert c._spans[0].duration_ms == 0.0

    def test_end_unknown_span_no_crash(self):
        c = TraceCollector()
        c.end_span("nonexistent_id")  # should log warning, not crash
        assert len(c._spans) == 0

    def test_orphaned_spans_closed_on_finalize(self):
        c = TraceCollector()
        sid = c.start_span(SPAN_LLM_CALL, "gpt-4o", turn=0)
        # Never call end_span — finalize should close it
        trace = c.finalize(success=False, turns_used=1, files_changed=[], summary="timeout")
        orphaned = [s for s in trace.spans if s.get("output_summary") == "(orphaned)"]
        assert len(orphaned) == 1
        assert orphaned[0]["success"] is False


# ---------------------------------------------------------------------------
# TraceCollector — finalize and metrics
# ---------------------------------------------------------------------------

class TestTraceCollectorMetrics:
    def _run_session(self):
        c = TraceCollector(repo_id="r1", repo_url="https://example.com/repo", model="gpt-4o", requirements="add tests")

        # Turn 0: LLM call
        sid = c.start_span(SPAN_LLM_CALL, "gpt-4o", turn=0, metadata={"model": "gpt-4o", "tokens_est": 1000})
        c.end_span(sid, output_summary="2 tool calls", metadata={"tokens_est": 1000})

        # Turn 0: read_file tool
        sid = c.start_span(SPAN_TOOL_CALL, "read_file", turn=0, inputs={"path": "main.py"})
        c.end_span(sid, output_summary="50 lines", output_chars=500, success=True, reward=0.5)

        # Turn 0: edit_file tool
        sid = c.start_span(SPAN_TOOL_CALL, "edit_file", turn=0, inputs={"path": "main.py"})
        c.end_span(sid, output_summary="edited", output_chars=100, success=True, reward=1.0)

        # Turn 1: LLM call
        sid = c.start_span(SPAN_LLM_CALL, "gpt-4o", turn=1, metadata={"model": "gpt-4o", "tokens_est": 800})
        c.end_span(sid, output_summary="1 tool call", metadata={"tokens_est": 800})

        # Turn 1: run_command tool (error)
        sid = c.start_span(SPAN_TOOL_CALL, "run_command", turn=1, inputs={"command": "pytest"})
        c.end_span(sid, output_summary="exit code 1", output_chars=2000, success=False, error="tests failed", reward=-0.5)

        # Stuck event
        c.add_event(SPAN_STUCK_DETECT, "stuck_3x", turn=1, reward=-1.0)

        return c.finalize(success=True, turns_used=2, files_changed=["main.py"], summary="Added tests")

    def test_metrics_counts(self):
        trace = self._run_session()
        m = trace.metrics
        assert m["llm_calls"] == 2
        assert m["tool_calls"] == 3
        assert m["errors"] == 1  # run_command failure
        assert m["total_spans"] == 6  # 2 LLM + 3 tool + 1 event

    def test_metrics_tool_breakdown(self):
        trace = self._run_session()
        breakdown = trace.metrics["tool_breakdown"]
        assert "read_file" in breakdown
        assert breakdown["read_file"]["count"] == 1
        assert breakdown["run_command"]["errors"] == 1

    def test_metrics_session_reward(self):
        trace = self._run_session()
        assert trace.metrics["session_reward"] == 1.0  # success=True

    def test_trace_fields(self):
        trace = self._run_session()
        assert trace.trace_id
        assert trace.repo_id == "r1"
        assert trace.model == "gpt-4o"
        assert trace.success is True
        assert trace.turns_used == 2
        assert trace.files_changed == ["main.py"]
        assert trace.total_duration_ms > 0
        assert trace.started_at
        assert trace.ended_at

    def test_failed_session_negative_reward(self):
        c = TraceCollector()
        trace = c.finalize(success=False, turns_used=50, files_changed=[], summary="exhausted")
        assert trace.metrics["session_reward"] == -1.0


# ---------------------------------------------------------------------------
# FileTraceStore — save/load
# ---------------------------------------------------------------------------

class TestFileTraceStore:
    def test_save_and_load(self, tmp_path):
        store = FileTraceStore(str(tmp_path))
        c = TraceCollector(repo_id="testrepo", model="test")
        sid = c.start_span(SPAN_TOOL_CALL, "read_file", turn=0)
        c.end_span(sid, output_summary="ok", success=True)
        trace = c.finalize(success=True, turns_used=1, files_changed=["a.py"], summary="done")

        path = store.save(trace)
        assert path.exists()

        loaded = store.load(trace.trace_id)
        assert loaded is not None
        assert loaded.trace_id == trace.trace_id
        assert loaded.success is True
        assert loaded.turns_used == 1
        assert len(loaded.spans) == 1

    def test_load_nonexistent(self, tmp_path):
        store = FileTraceStore(str(tmp_path))
        assert store.load("nonexistent") is None

    def test_list_traces(self, tmp_path):
        store = FileTraceStore(str(tmp_path))

        # Save two traces
        for i in range(2):
            c = TraceCollector(repo_id="repo1", model="test")
            trace = c.finalize(success=i == 1, turns_used=i + 1, files_changed=[], summary=f"trace {i}")
            store.save(trace)

        summaries = store.list_traces(repo_id="repo1")
        assert len(summaries) == 2
        assert all(s["repo_id"] == "repo1" for s in summaries)

    def test_list_traces_empty(self, tmp_path):
        store = FileTraceStore(str(tmp_path))
        assert store.list_traces() == []

    def test_list_traces_filters_by_repo(self, tmp_path):
        store = FileTraceStore(str(tmp_path))
        for rid in ["repo_a", "repo_b"]:
            c = TraceCollector(repo_id=rid)
            store.save(c.finalize(success=True, turns_used=1, files_changed=[], summary="ok"))
        assert len(store.list_traces(repo_id="repo_a")) == 1


# ---------------------------------------------------------------------------
# AgentTrace — serialization
# ---------------------------------------------------------------------------

class TestAgentTraceSerialization:
    def test_round_trip(self):
        trace = AgentTrace(
            trace_id="abc123",
            repo_id="r1",
            success=True,
            turns_used=5,
            files_changed=["a.py"],
            summary="done",
            spans=[{"span_id": "s1", "span_type": "tool_call", "name": "read_file"}],
            metrics={"llm_calls": 3, "tool_calls": 5},
        )
        d = trace.to_dict()
        assert isinstance(d, dict)
        loaded = AgentTrace.from_dict(d)
        assert loaded.trace_id == "abc123"
        assert loaded.success is True
        assert loaded.spans[0]["name"] == "read_file"

    def test_from_dict_missing_fields(self):
        loaded = AgentTrace.from_dict({"trace_id": "x"})
        assert loaded.trace_id == "x"
        assert loaded.success is False
        assert loaded.spans == []


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

class TestConfigHelpers:
    def test_tracing_enabled_default(self):
        assert is_tracing_enabled(None) is True
        assert is_tracing_enabled({}) is True

    def test_tracing_enabled_explicit(self):
        assert is_tracing_enabled({"tracing": {"enabled": True}}) is True
        assert is_tracing_enabled({"tracing": {"enabled": False}}) is False

    def test_get_trace_store_default(self):
        store = get_trace_store(None)
        assert isinstance(store, FileTraceStore)

    def test_get_trace_store_with_dir(self, tmp_path):
        store = get_trace_store({"tracing": {"storage_dir": str(tmp_path)}})
        assert store._dir == tmp_path
