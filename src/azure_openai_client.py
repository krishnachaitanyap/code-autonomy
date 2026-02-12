"""
Azure OpenAI client with certificate-based auth (S3) or API key.
Supports direct HTTP requests to Azure OpenAI chat completions API.
Integrates with code-autonomy's llm_client when provider=azure.
"""

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _default_log_path() -> str:
    """Default log file path in project root (sibling of src)."""
    return str(Path(__file__).resolve().parent.parent / "llm.log")


def _ensure_logging_configured() -> None:
    """Configure basic logging when the host app has not done so."""
    root = logging.getLogger()
    if root.handlers:
        return
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def _ensure_file_handler(log_path: str) -> None:
    """Attach a file handler for LLM logs if configured via env."""
    if not log_path or not log_path.strip():
        return
    path = Path(log_path).resolve()
    for h in logger.handlers:
        if getattr(h, "baseFilename", None) == str(path):
            return
    try:
        fh = logging.FileHandler(path, encoding="utf-8")
        fh.setLevel(logging.INFO)
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
        logger.addHandler(fh)
    except Exception:
        pass


def _format_messages(messages: list[dict]) -> str:
    """Pretty-print chat messages for console visibility."""
    lines = []
    for i, m in enumerate(messages, 1):
        role = m.get("role", "?")
        content = (m.get("content") or "").strip()
        lines.append(f"{i}. {role}: {content}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# S3 certificate loading (for certificate-based Azure auth)
# ---------------------------------------------------------------------------

def _load_certificate_from_s3(bucket_name: str, file_name: str) -> bytes:
    """Load a certificate from S3."""
    import boto3
    s3 = boto3.client("s3")
    response = s3.get_object(Bucket=bucket_name, Key=file_name)
    return response["Body"].read()


# ---------------------------------------------------------------------------
# Azure access token (certificate-based)
# ---------------------------------------------------------------------------

def _get_access_token(config: dict) -> Optional[str]:
    """
    Obtain Azure access token using certificate from S3.
    Reads S3 and Azure cert fields from the [ai] section of config.
    """
    ai = config.get("ai") or config
    bucket = (ai.get("s3_bucket_name") or "").strip()
    cert_key = (ai.get("azure_cert_file_name") or "").strip()
    tenant_id = (ai.get("tenant_id") or "").strip()
    client_id = (ai.get("client_id") or "").strip()
    scope = (ai.get("scope") or "https://cognitiveservices.azure.com/.default").strip()

    if not all([bucket, cert_key, tenant_id, client_id]):
        return None

    try:
        pem_content = _load_certificate_from_s3(bucket, cert_key)
    except Exception as e:
        logger.error("Failed to load certificate from S3: %s", e)
        return None

    try:
        from azure.identity import CertificateCredential
        from azure.core.exceptions import ClientAuthenticationError

        credential = CertificateCredential(
            tenant_id=tenant_id,
            client_id=client_id,
            certificate_data=pem_content,
        )
        token = credential.get_token(scope)
        return token.token
    except ClientAuthenticationError as e:
        logger.error("Azure authentication failed: %s", e)
        return None
    except Exception as e:
        logger.error("Unexpected error obtaining Azure token: %s", e)
        return None


# ---------------------------------------------------------------------------
# LLM response structures (AGENT_TOOLS compatible)
# ---------------------------------------------------------------------------

class _LLMFunctionCall:
    def __init__(self, name: str, arguments: str):
        self.name = name
        self.arguments = arguments


class _LLMToolCall:
    def __init__(self, name: str, arguments: str, call_id: str = ""):
        self.id = call_id or str(uuid.uuid4())
        self.function = _LLMFunctionCall(name, arguments)


class _LLMMessage:
    def __init__(self, content: str, tool_calls: list):
        self.content = content
        self.tool_calls = tool_calls


# ---------------------------------------------------------------------------
# Azure OpenAI API helpers
# ---------------------------------------------------------------------------

def _build_chat_url(config: dict) -> str:
    """Build Azure OpenAI chat completions URL."""
    ai = config.get("ai") or config
    endpoint = (ai.get("endpoint") or "").rstrip("/")
    deployment = (ai.get("deployment_name") or "").strip()
    version = (ai.get("api_version") or "2024-02-15-preview").strip()
    if not endpoint or not deployment:
        raise ValueError("Azure OpenAI requires endpoint and deployment_name in [ai] section.")
    return f"{endpoint}/openai/deployments/{deployment}/chat/completions?api-version={version}"


def _extract_functions(tools: Optional[list[dict]]) -> list[dict]:
    """Extract function definitions from OpenAI-style tool schemas."""
    if not tools:
        return []
    functions = []
    for t in tools:
        fn = t.get("function") if isinstance(t, dict) else None
        if isinstance(fn, dict) and fn.get("name"):
            functions.append(fn)
    return functions


# ---------------------------------------------------------------------------
# Chat completion
# ---------------------------------------------------------------------------

def chat_completion_azure(
    messages: list[dict],
    config: dict,
    tools: Optional[list[dict]] = None,
    tool_choice: str = "auto",
    temperature: float = 0.2,
    max_tokens: int = 1024,
) -> tuple[str, Any]:
    """
    Call Azure OpenAI chat completion. Returns (content, message).
    message has .content and .tool_calls (AGENT_TOOLS compatible).
    """
    import requests

    _ensure_logging_configured()
    _ensure_file_handler(os.environ.get("LLM_LOG_FILE", ""))

    ai = config.get("ai") or config
    api_key = (ai.get("api_key") or "").strip()
    access_token = _get_access_token(config)

    if not api_key and not access_token:
        raise ValueError(
            "Azure OpenAI requires api_key in [ai] or certificate-based auth (tenant_id, client_id, s3_bucket_name, azure_cert_file_name)."
        )

    deployment = (ai.get("deployment_name") or "").strip()
    if not deployment:
        raise ValueError("Azure OpenAI requires deployment_name in [ai] section.")

    url = _build_chat_url(config)

    payload = {
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    functions = _extract_functions(tools)
    if functions:
        payload["tools"] = [{"type": "function", "function": f} for f in functions]
        payload["tool_choice"] = tool_choice if tool_choice != "none" else "none"

    headers = {
        "Content-Type": "application/json",
        "user_sid": "code-autonomy",
    }
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    if api_key:
        headers["api-key"] = api_key

    logger.info(
        "Azure OpenAI request: deployment=%s temperature=%s tools=%s\n%s",
        deployment, temperature, "enabled" if functions else "none",
        _format_messages(messages),
    )

    response = requests.post(url, json=payload, headers=headers, timeout=60)
    response.raise_for_status()

    data = response.json()
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("Azure OpenAI returned no choices")

    message = choices[0].get("message", {})
    content = (message.get("content") or "").strip()
    function_call = message.get("function_call")

    tool_calls = []
    if function_call and isinstance(function_call, dict):
        name = function_call.get("name") or ""
        arguments = function_call.get("arguments") or "{}"
        tool_calls.append(_LLMToolCall(name=name, arguments=arguments))

    logger.info(
        "Azure OpenAI response: deployment=%s content=%s function_call=%s",
        deployment, content[:200] if content else "(empty)", function_call,
    )

    msg = _LLMMessage(content=content, tool_calls=tool_calls)
    return content, msg
