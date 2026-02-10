"""
Unified LLM client for multi-provider support.
Supports OpenAI, Anthropic (Claude), Google (Gemini) via LiteLLM.
Supports AWS Bedrock (Claude) via org cdao.bedrock_byoa_invoke_model when provider=bedrock or cdao.
Uses config and env for flexible authentication.
Includes retry logic for transient API errors.
Supports circuit breaker and rate limiting when configured.
"""

import json
import os
import time
from typing import Any, Optional

from src.resiliency import CircuitBreaker, TokenBucketRateLimiter

# Provider-specific env var defaults when api_key not in config
DEFAULT_API_KEY_ENV: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "google": "GEMINI_API_KEY",
}

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 2  # seconds

# Resiliency singletons — None = disabled (backward compatible)
_circuit_breaker: Optional[CircuitBreaker] = None
_rate_limiter: Optional[TokenBucketRateLimiter] = None


def configure_resiliency(
    circuit_breaker_threshold: int = 5,
    circuit_breaker_timeout: float = 60.0,
    rate_limit_max_tokens: float = 10.0,
    rate_limit_refill_rate: float = 1.0,
) -> None:
    """Initialize resiliency singletons. Call once at startup."""
    global _circuit_breaker, _rate_limiter
    _circuit_breaker = CircuitBreaker(
        failure_threshold=circuit_breaker_threshold,
        recovery_timeout=circuit_breaker_timeout,
    )
    _rate_limiter = TokenBucketRateLimiter(
        max_tokens=rate_limit_max_tokens,
        refill_rate=rate_limit_refill_rate,
    )


def get_circuit_breaker() -> Optional[CircuitBreaker]:
    """Return the circuit breaker singleton (for monitoring/testing)."""
    return _circuit_breaker


def get_rate_limiter() -> Optional[TokenBucketRateLimiter]:
    """Return the rate limiter singleton (for monitoring/testing)."""
    return _rate_limiter


def _resolve_api_key(config: dict) -> str:
    """Resolve API key from config or environment."""
    api_key = (config.get("api_key") or "").strip()
    if api_key and not (api_key.startswith("<") and api_key.endswith(">")):
        return api_key
    provider = (config.get("provider") or "openai").lower()
    env_var = config.get("api_key_env") or DEFAULT_API_KEY_ENV.get(provider, "OPENAI_API_KEY")
    return os.environ.get(env_var, "")


def _is_bedrock_provider(config: dict) -> bool:
    """True when using org Bedrock BYOA via cdao."""
    return (config.get("provider") or "openai").lower() in ("bedrock", "cdao")


def _build_model_string(config: dict) -> str:
    """Build LiteLLM model string: provider/model or just model for OpenAI. For bedrock/cdao returns model ARN as-is."""
    provider = (config.get("provider") or "openai").lower()
    model = (config.get("model") or "gpt-4o").strip()
    if provider in ("bedrock", "cdao"):
        return model  # Full ARN
    if provider == "openai":
        return model  # "gpt-4o" - LiteLLM routes to OpenAI by default
    return f"{provider}/{model}"  # "anthropic/claude-3-5-sonnet", "gemini/gemini-1.5-pro"


def get_model_name(config: dict) -> str:
    """Return the model name from config (without provider prefix)."""
    return (config.get("model") or "gpt-4o").strip()


def _is_retryable(exc: Exception) -> bool:
    """Check if the error is transient and worth retrying."""
    err = str(exc).lower()
    return any(
        k in err
        for k in ("rate limit", "rate_limit", "429", "timeout", "500", "502", "503", "overloaded")
    )


def _chat_completion_bedrock(
    messages: list[dict],
    config: dict,
    temperature: float = 0.2,
    max_tokens: int = 1024,
) -> tuple[str, Any]:
    """Call Claude via cdao.bedrock_byoa_invoke_model. Returns (content, message-like)."""
    import cdao
    data = {
        "AWSAccountNumber": (config.get("aws_account_number") or "").strip(),
        "AWSRegion": (config.get("aws_region") or "us-east-1").strip(),
        "WorkspaceID": (config.get("workspace_id") or "").strip(),
        "isExecutionRole": config.get("is_execution_role", False),
    }
    model_id = (config.get("model") or "").strip()
    if not all([data["AWSAccountNumber"], data["AWSRegion"], data["WorkspaceID"], model_id]):
        raise ValueError(
            "Bedrock/cdao requires [ai]: aws_account_number, aws_region, workspace_id, model (ARN)."
        )
    input_json = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": max_tokens,
        "messages": messages,
    }
    response = cdao.bedrock_byoa_invoke_model(data, {
        "modelId": model_id,
        "body": json.dumps(input_json),
        "contentType": "application/json",
        "accept": "application/json",
    })
    body_bytes = response.get("body")
    if body_bytes is None:
        raise RuntimeError("Bedrock response has no body")
    response_body = body_bytes.read().decode("utf-8")
    out = json.loads(response_body)
    content_blocks = out.get("content") or []
    text_parts = [b["text"] for b in content_blocks if b.get("type") == "text"]
    content = ("".join(text_parts)).strip()

    class _Msg:
        pass

    m = _Msg()
    m.content = content
    m.tool_calls = []
    return content, m


def chat_completion(
    messages: list[dict],
    config: dict,
    tools: Optional[list[dict]] = None,
    tool_choice: str = "auto",
    temperature: float = 0.2,
) -> tuple[str, Any]:
    """
    Unified chat completion across OpenAI, Anthropic, Gemini.

    Includes automatic retry with exponential backoff for transient errors
    (rate limits, timeouts, 5xx).

    Args:
        messages: List of dicts with role and content (OpenAI format).
        config: AI config with provider, model, api_key, base_url, api_key_env.
        tools: Optional list of tool definitions (for agent mode).
        tool_choice: "auto" or "none".
        temperature: Sampling temperature.

    Returns:
        (content, message).
        content: str from assistant message.
        message: raw message object (has .tool_calls for agent mode).
    """
    # Bedrock/cdao path (org BYOA via cdao)
    if _is_bedrock_provider(config):
        if tools:
            # Bedrock path does not support tools; use text-only
            pass
        if _circuit_breaker is not None:
            _circuit_breaker.ensure_closed()
        if _rate_limiter is not None:
            _rate_limiter.acquire(timeout=30.0)
        last_exc: Optional[Exception] = None
        for attempt in range(_MAX_RETRIES):
            try:
                content, msg = _chat_completion_bedrock(
                    messages, config, temperature=temperature, max_tokens=1024
                )
                if _circuit_breaker is not None:
                    _circuit_breaker.record_success()
                return content, msg
            except Exception as exc:
                last_exc = exc
                if _is_retryable(exc) and _circuit_breaker is not None:
                    _circuit_breaker.record_failure()
                if attempt < _MAX_RETRIES - 1 and _is_retryable(exc):
                    time.sleep(_RETRY_BASE_DELAY * (2 ** attempt))
                    continue
                raise
        raise last_exc  # type: ignore[misc]

    try:
        import litellm
    except ImportError:
        raise ImportError(
            "LiteLLM is required for multi-provider support. "
            "Install with: pip install litellm"
        )

    api_key = _resolve_api_key(config)
    if not api_key:
        raise ValueError(
            "No API key found. Set api_key in config.ini or "
            f"{DEFAULT_API_KEY_ENV.get(config.get('provider', 'openai'), 'OPENAI_API_KEY')} env var."
        )

    model = _build_model_string(config)
    base_url = config.get("base_url", "").strip() or None

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "api_key": api_key,
    }
    if base_url:
        kwargs["api_base"] = base_url.rstrip("/")
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = tool_choice

    # Resiliency: fail-fast if circuit breaker is OPEN
    if _circuit_breaker is not None:
        _circuit_breaker.ensure_closed()

    # Resiliency: wait for rate limiter token
    if _rate_limiter is not None:
        _rate_limiter.acquire(timeout=30.0)

    # Retry loop for transient errors
    last_exc_litellm: Optional[Exception] = None
    for attempt in range(_MAX_RETRIES):
        try:
            response = litellm.completion(**kwargs)
            msg = response.choices[0].message
            content = (msg.content or "").strip()
            if _circuit_breaker is not None:
                _circuit_breaker.record_success()
            return content, msg
        except Exception as exc:
            last_exc_litellm = exc
            if _is_retryable(exc) and _circuit_breaker is not None:
                _circuit_breaker.record_failure()
            if attempt < _MAX_RETRIES - 1 and _is_retryable(exc):
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                time.sleep(delay)
                continue
            raise

    raise last_exc_litellm  # type: ignore[misc]
