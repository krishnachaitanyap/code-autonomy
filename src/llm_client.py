"""
Unified LLM client for multi-provider support.
Supports OpenAI, Anthropic (Claude), Google (Gemini) via LiteLLM.
Uses config and env for flexible authentication.
Includes retry logic for transient API errors.
"""

import os
import time
from typing import Any, Optional

# Provider-specific env var defaults when api_key not in config
DEFAULT_API_KEY_ENV: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "google": "GEMINI_API_KEY",
}

_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 2  # seconds


def _resolve_api_key(config: dict) -> str:
    """Resolve API key from config or environment."""
    api_key = (config.get("api_key") or "").strip()
    if api_key and not (api_key.startswith("<") and api_key.endswith(">")):
        return api_key
    provider = (config.get("provider") or "openai").lower()
    env_var = config.get("api_key_env") or DEFAULT_API_KEY_ENV.get(provider, "OPENAI_API_KEY")
    return os.environ.get(env_var, "")


def _build_model_string(config: dict) -> str:
    """Build LiteLLM model string: provider/model or just model for OpenAI."""
    provider = (config.get("provider") or "openai").lower()
    model = (config.get("model") or "gpt-4o").strip()
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

    # Retry loop for transient errors
    last_exc: Optional[Exception] = None
    for attempt in range(_MAX_RETRIES):
        try:
            response = litellm.completion(**kwargs)
            msg = response.choices[0].message
            content = (msg.content or "").strip()
            return content, msg
        except Exception as exc:
            last_exc = exc
            if attempt < _MAX_RETRIES - 1 and _is_retryable(exc):
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                time.sleep(delay)
                continue
            raise

    # Should not reach here, but just in case
    raise last_exc  # type: ignore[misc]
