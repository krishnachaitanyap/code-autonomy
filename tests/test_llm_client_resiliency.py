"""Tests for resiliency integration in src/llm_client.py."""

from unittest.mock import patch, MagicMock

import pytest

import src.llm_client as llm_client
from src.resiliency import CircuitBreaker, CircuitOpenError, CircuitState, TokenBucketRateLimiter


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Reset module-level singletons before and after each test."""
    llm_client._circuit_breaker = None
    llm_client._rate_limiter = None
    yield
    llm_client._circuit_breaker = None
    llm_client._rate_limiter = None


def _ai_config():
    return {
        "provider": "openai",
        "api_key": "sk-test",
        "model": "gpt-4o",
        "base_url": "",
    }


def _mock_response(content="hello"):
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = None
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


class TestConfigureResiliency:
    def test_configure_creates_singletons(self):
        llm_client.configure_resiliency(
            circuit_breaker_threshold=3,
            circuit_breaker_timeout=30.0,
            rate_limit_max_tokens=5.0,
            rate_limit_refill_rate=2.0,
        )
        cb = llm_client.get_circuit_breaker()
        rl = llm_client.get_rate_limiter()
        assert cb is not None
        assert cb.failure_threshold == 3
        assert cb.recovery_timeout == 30.0
        assert rl is not None
        assert rl.max_tokens == 5.0
        assert rl.refill_rate == 2.0

    def test_no_configure_singletons_are_none(self):
        assert llm_client.get_circuit_breaker() is None
        assert llm_client.get_rate_limiter() is None


class TestCircuitBreakerIntegration:
    def test_success_resets_circuit(self):
        llm_client.configure_resiliency(circuit_breaker_threshold=3)
        cb = llm_client.get_circuit_breaker()
        cb.record_failure()
        cb.record_failure()
        assert cb.failure_count == 2

        with patch("litellm.completion", return_value=_mock_response()):
            llm_client.chat_completion(
                [{"role": "user", "content": "hi"}],
                _ai_config(),
            )
        assert cb.failure_count == 0
        assert cb.state == CircuitState.CLOSED

    def test_retryable_failure_records_on_circuit(self):
        llm_client.configure_resiliency(circuit_breaker_threshold=10)
        cb = llm_client.get_circuit_breaker()

        with patch("litellm.completion", side_effect=Exception("rate limit exceeded")):
            with pytest.raises(Exception, match="rate limit"):
                llm_client.chat_completion(
                    [{"role": "user", "content": "hi"}],
                    _ai_config(),
                )
        # Should have recorded failures for each retry attempt
        assert cb.failure_count > 0

    def test_open_circuit_raises_without_api_call(self):
        llm_client.configure_resiliency(circuit_breaker_threshold=1)
        cb = llm_client.get_circuit_breaker()
        cb.record_failure()  # Opens circuit

        with patch("litellm.completion") as mock_comp:
            with pytest.raises(CircuitOpenError):
                llm_client.chat_completion(
                    [{"role": "user", "content": "hi"}],
                    _ai_config(),
                )
            mock_comp.assert_not_called()


class TestRateLimiterIntegration:
    def test_acquire_called_before_api(self):
        llm_client.configure_resiliency(rate_limit_max_tokens=10.0)
        rl = llm_client.get_rate_limiter()
        initial = rl.available_tokens

        with patch("litellm.completion", return_value=_mock_response()):
            llm_client.chat_completion(
                [{"role": "user", "content": "hi"}],
                _ai_config(),
            )
        # One token should have been consumed
        assert rl.available_tokens < initial


class TestBackwardCompatibility:
    def test_no_configure_still_works(self):
        """Without configure_resiliency(), chat_completion works as before."""
        with patch("litellm.completion", return_value=_mock_response("world")):
            content, msg = llm_client.chat_completion(
                [{"role": "user", "content": "hello"}],
                _ai_config(),
            )
        assert content == "world"
