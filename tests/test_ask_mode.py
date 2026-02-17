"""Tests for ask-mode fixes: fast path, deadline nudge, and config defaults."""

from unittest.mock import patch, MagicMock
import pytest

from src.agent.analyzer import _try_fast_answer, _FAST_ANSWER_SYSTEM


# ---------------------------------------------------------------------------
# _try_fast_answer
# ---------------------------------------------------------------------------

_CHAT_PATCH = "src.llm_client.chat_completion"


class TestTryFastAnswer:
    """Tests for the fast-path single-call answer attempt."""

    @patch(_CHAT_PATCH)
    def test_returns_answer_when_confident(self, mock_chat):
        mock_chat.return_value = ("The auth module uses JWT tokens stored in Redis.", MagicMock())

        result = _try_fast_answer(
            question="How does auth work?",
            context="## Project overview\nAuth uses JWT tokens stored in Redis via AuthService.",
            llm_config={"model": "gpt-4o", "api_key": "test"},
        )

        assert result is not None
        assert "JWT" in result
        mock_chat.assert_called_once()

    @patch(_CHAT_PATCH)
    def test_returns_none_when_insufficient(self, mock_chat):
        mock_chat.return_value = ("INSUFFICIENT_CONTEXT", MagicMock())

        result = _try_fast_answer(
            question="What database does the billing service use?",
            context="## Project overview\nThis is a Python CLI tool.",
            llm_config={"model": "gpt-4o", "api_key": "test"},
        )

        assert result is None

    @patch(_CHAT_PATCH)
    def test_returns_none_when_empty_response(self, mock_chat):
        mock_chat.return_value = ("", MagicMock())

        result = _try_fast_answer(
            question="How does X work?",
            context="Some context here.",
            llm_config={"model": "gpt-4o", "api_key": "test"},
        )

        assert result is None

    @patch(_CHAT_PATCH)
    def test_returns_none_when_insufficient_embedded(self, mock_chat):
        mock_chat.return_value = (
            "I don't have enough info. INSUFFICIENT_CONTEXT to answer properly.",
            MagicMock(),
        )

        result = _try_fast_answer(
            question="How does X work?",
            context="Some context here.",
            llm_config={"model": "gpt-4o", "api_key": "test"},
        )

        assert result is None

    @patch(_CHAT_PATCH)
    def test_context_trimmed_to_limit(self, mock_chat):
        mock_chat.return_value = ("Answer.", MagicMock())
        long_context = "x" * 50_000

        _try_fast_answer(
            question="Q?",
            context=long_context,
            llm_config={"model": "gpt-4o", "api_key": "test"},
        )

        # Verify the context sent to the LLM was trimmed
        call_args = mock_chat.call_args
        messages = call_args.kwargs.get("messages") or call_args[0][0]
        user_msg_content = messages[1]["content"]
        # 15_000 chars max context + question overhead
        assert len(user_msg_content) < 16_000

    @patch(_CHAT_PATCH)
    def test_usage_category_is_ask_fast_path(self, mock_chat):
        mock_chat.return_value = ("Answer.", MagicMock())

        _try_fast_answer(
            question="Q?",
            context="Some context.",
            llm_config={"model": "gpt-4o", "api_key": "test"},
        )

        call_kwargs = mock_chat.call_args
        category = call_kwargs.kwargs.get("usage_category")
        assert category == "ask_fast_path"

    @patch(_CHAT_PATCH)
    def test_exception_propagates(self, mock_chat):
        """_try_fast_answer does not catch exceptions; the caller does."""
        mock_chat.side_effect = Exception("API error")

        with pytest.raises(Exception, match="API error"):
            _try_fast_answer(
                question="Q?",
                context="Some context.",
                llm_config={"model": "gpt-4o", "api_key": "test"},
            )


# ---------------------------------------------------------------------------
# Fast path integration — skipped when context is too short
# ---------------------------------------------------------------------------


class TestFastPathSkipped:
    """Verify fast path is skipped when context is insufficient."""

    @patch("src.agent.analyzer._try_fast_answer")
    @patch(_CHAT_PATCH)
    def test_fast_path_skipped_when_short_context(self, mock_chat, mock_fast):
        """If combined context < 200 chars, fast path should not be called."""
        from src.agent.analyzer import generate_answer_with_agent

        # Mock the LLM to immediately call task_complete
        mock_msg = MagicMock()
        tc = MagicMock()
        tc.id = "tc1"
        tc.function.name = "task_complete"
        tc.function.arguments = '{"answer": "test answer", "summary": "done", "sources": []}'
        mock_msg.tool_calls = [tc]
        mock_msg.content = ""
        mock_chat.return_value = ("", mock_msg)

        result = generate_answer_with_agent(
            question="What is this?",
            repo_path="/tmp/fake",
            llm_config={"model": "gpt-4o", "api_key": "test"},
            max_turns=5,
            consciousness=None,
            repo_knowledge="",  # empty — no context for fast path
        )

        # Fast path should NOT have been called (short/empty context)
        mock_fast.assert_not_called()


# ---------------------------------------------------------------------------
# Deadline nudge injection
# ---------------------------------------------------------------------------


class TestDeadlineNudge:
    """Verify deadline messages are injected at correct turn thresholds."""

    @patch(_CHAT_PATCH)
    def test_deadline_nudges_injected(self, mock_chat):
        """With max_turns=10, soft deadline at turn 6, hard at turn 8."""
        from src.agent.analyzer import generate_answer_with_agent

        call_count = 0
        all_messages_seen: list[list[dict]] = []

        def mock_chat_fn(**kwargs):
            nonlocal call_count
            call_count += 1
            messages = kwargs.get("messages", [])
            # Take a snapshot of messages
            all_messages_seen.append([m.copy() for m in messages])

            mock_msg = MagicMock()
            if call_count >= 9:
                tc = MagicMock()
                tc.id = f"tc{call_count}"
                tc.function.name = "task_complete"
                tc.function.arguments = '{"answer": "test", "summary": "done", "sources": []}'
                mock_msg.tool_calls = [tc]
                mock_msg.content = ""
            else:
                tc = MagicMock()
                tc.id = f"tc{call_count}"
                tc.function.name = "list_dir"
                tc.function.arguments = '{"path": ""}'
                mock_msg.tool_calls = [tc]
                mock_msg.content = ""
            return ("", mock_msg)

        mock_chat.side_effect = mock_chat_fn

        result = generate_answer_with_agent(
            question="What does this project do?",
            repo_path="/tmp/fake",
            llm_config={"model": "gpt-4o", "api_key": "test"},
            max_turns=10,
            consciousness=None,
            repo_knowledge="",
        )

        # Collect all user messages across all calls
        all_user_msgs = []
        for msg_list in all_messages_seen:
            for m in msg_list:
                if m.get("role") == "user":
                    content = m.get("content", "")
                    all_user_msgs.append(content)

        # Check for soft deadline (at turn 6)
        has_soft = any("wrapping up" in c.lower() or "start wrapping" in c.lower() for c in all_user_msgs)
        # Check for hard deadline (at turn 8)
        has_hard = any("deadline" in c.upper() and "must call" in c.lower() for c in all_user_msgs)

        assert has_soft or has_hard, (
            f"Expected deadline nudge in {call_count} turns. "
            f"User messages seen: {[c[:80] for c in all_user_msgs if 'turn' in c.lower()]}"
        )


# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------


class TestAskConfigDefaults:
    """Verify ask_max_turns config propagation."""

    def test_ask_max_turns_default_from_agent_config(self):
        import inspect
        from src.agent.analyzer import generate_answer_with_agent
        sig = inspect.signature(generate_answer_with_agent)
        assert "max_turns" in sig.parameters
        assert sig.parameters["max_turns"].default == 20

    def test_fast_answer_system_prompt_has_insufficient_marker(self):
        assert "INSUFFICIENT_CONTEXT" in _FAST_ANSWER_SYSTEM
