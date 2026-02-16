"""Tests for LLMUsageStats dataclass and log_llm_stats display function."""

import io
import sys
from unittest.mock import patch

import pytest

from src.llm_client import LLMUsageStats
from src.agent.activity import log_llm_stats


# ---------------------------------------------------------------------------
# LLMUsageStats dataclass
# ---------------------------------------------------------------------------


class TestLLMUsageStats:
    def test_empty_stats(self):
        stats = LLMUsageStats()
        assert stats.num_calls == 0
        assert stats.total_prompt_tokens == 0
        assert stats.total_completion_tokens == 0
        assert stats.total_tokens == 0
        assert stats.calls == []

    def test_single_record(self):
        stats = LLMUsageStats()
        stats.record(prompt_tokens=100, completion_tokens=50, total_tokens=150)
        assert stats.num_calls == 1
        assert stats.total_prompt_tokens == 100
        assert stats.total_completion_tokens == 50
        assert stats.total_tokens == 150

    def test_multiple_records(self):
        stats = LLMUsageStats()
        stats.record(prompt_tokens=100, completion_tokens=50, total_tokens=150)
        stats.record(prompt_tokens=200, completion_tokens=80, total_tokens=280)
        stats.record(prompt_tokens=50, completion_tokens=20, total_tokens=70)
        assert stats.num_calls == 3
        assert stats.total_prompt_tokens == 350
        assert stats.total_completion_tokens == 150
        assert stats.total_tokens == 500

    def test_calls_list_structure(self):
        stats = LLMUsageStats()
        stats.record(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        assert len(stats.calls) == 1
        assert stats.calls[0] == {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "category": "main",
        }

    def test_zero_token_record(self):
        stats = LLMUsageStats()
        stats.record(prompt_tokens=0, completion_tokens=0, total_tokens=0)
        assert stats.num_calls == 1
        assert stats.total_tokens == 0


# ---------------------------------------------------------------------------
# log_llm_stats display function
# ---------------------------------------------------------------------------


class TestLogLLMStats:
    def test_none_stats_no_output(self, capsys):
        log_llm_stats(None)
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_empty_stats_no_output(self, capsys):
        stats = LLMUsageStats()
        log_llm_stats(stats)
        captured = capsys.readouterr()
        assert captured.out == ""

    @patch("src.agent.activity._USE_RICH", False)
    @patch("src.agent.activity._RICH_AVAILABLE", False)
    def test_plain_text_output(self, capsys):
        stats = LLMUsageStats()
        stats.record(prompt_tokens=45230, completion_tokens=8412, total_tokens=53642)
        stats.record(prompt_tokens=1000, completion_tokens=500, total_tokens=1500)
        log_llm_stats(stats)
        captured = capsys.readouterr()
        output = captured.out
        assert "Calls:" in output
        assert "2" in output
        assert "Prompt tokens:" in output
        assert "46,230" in output
        assert "Completion tokens:" in output
        assert "8,912" in output
        assert "Total tokens:" in output
        assert "55,142" in output

    @patch("src.agent.activity._USE_RICH", False)
    @patch("src.agent.activity._RICH_AVAILABLE", False)
    def test_single_call_output(self, capsys):
        stats = LLMUsageStats()
        stats.record(prompt_tokens=100, completion_tokens=50, total_tokens=150)
        log_llm_stats(stats)
        captured = capsys.readouterr()
        output = captured.out
        assert "Calls:" in output
        assert "Prompt tokens:" in output
        assert "100" in output
        assert "50" in output
        assert "150" in output
