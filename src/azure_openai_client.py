"""
Azure OpenAI client with certificate-based auth (S3) or API key.
Uses LangChain's AzureChatOpenAI for chat completions.
Integrates with code-autonomy's llm_client when provider=azure.
"""

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Optional

from langchain_openai import AzureChatOpenAI

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
    Call Azure OpenAI chat completion via LangChain AzureChatOpenAI.
    Returns (content, message) where message has .content and .tool_calls
    (AGENT_TOOLS compatible).
    """
    _ensure_logging_configured()
    _ensure_file_handler(os.environ.get("LLM_LOG_FILE", ""))

    ai = config.get("ai") or config
    api_key = (ai.get("api_key") or "").strip()
    access_token = _get_access_token(config)

    if not api_key and not access_token:
        raise ValueError(
            "Azure OpenAI requires api_key in [ai] or certificate-based auth "
            "(tenant_id, client_id, s3_bucket_name, azure_cert_file_name)."
        )

    endpoint = (ai.get("endpoint") or "").rstrip("/")
    deployment = (ai.get("deployment_name") or "").strip()
    api_version = (ai.get("api_version") or "2024-02-15-preview").strip()

    if not endpoint or not deployment:
        raise ValueError("Azure OpenAI requires endpoint and deployment_name in [ai] section.")

    # Build default headers for auth
    default_headers = {"user_sid": "code-autonomy"}
    if access_token:
        default_headers["Authorization"] = f"Bearer {access_token}"
    if api_key:
        default_headers["api-key"] = api_key

    functions = _extract_functions(tools)

    logger.info(
        "Azure OpenAI request: deployment=%s temperature=%s tools=%s\n%s",
        deployment, temperature, "enabled" if functions else "none",
        _format_messages(messages),
    )

    llm = AzureChatOpenAI(
        azure_endpoint=endpoint,
        openai_api_version=api_version,
        deployment_name=deployment,
        openai_api_key=api_key or "placeholder",
        openai_api_type="azure",
        max_tokens=max_tokens,
        temperature=temperature,
        streaming=False,
        default_headers=default_headers,
    )

    # Bind tools if provided
    if functions:
        tools_schema = [{"type": "function", "function": f} for f in functions]
        llm_with_tools = llm.bind_tools(tools_schema)
    else:
        llm_with_tools = llm

    # Invoke LangChain
    ai_message = llm_with_tools.invoke(messages)
    content = (ai_message.content or "").strip()

    # Convert LangChain tool_calls to our wrapper format
    tool_calls = []
    for tc in (ai_message.tool_calls or []):
        tool_calls.append(_LLMToolCall(
            name=tc["name"],
            arguments=json.dumps(tc["args"]) if isinstance(tc["args"], dict) else tc["args"],
            call_id=tc.get("id", ""),
        ))

    logger.info(
        "Azure OpenAI response: deployment=%s content=%s tool_calls=%d",
        deployment, content[:200] if content else "(empty)", len(tool_calls),
    )

    msg = _LLMMessage(content=content, tool_calls=tool_calls)
    return content, msg


# ---------------------------------------------------------------------------
# Azure OpenAI Embeddings
# ---------------------------------------------------------------------------

def create_embeddings_client(config: dict):
    """Create Azure OpenAI Embeddings client.

    Args:
        config: Full application config dict (with "ai" section).

    Returns:
        AzureOpenAIEmbeddings instance.
    """
    from langchain_openai import AzureOpenAIEmbeddings

    ai = config.get("ai") or config
    api_key = (ai.get("api_key") or "").strip()
    endpoint = (ai.get("endpoint") or "").strip()
    api_version = (ai.get("api_version") or "2024-02-15-preview").strip()
    deployment = (ai.get("embedding_model") or ai.get("deployment_name") or "text-embedding-3-small").strip()

    # Try certificate-based access token first, fall back to API key
    access_token = _get_access_token(config)

    embed_kwargs: dict[str, Any] = {
        "azure_endpoint": endpoint,
        "openai_api_version": api_version,
        "model": deployment,
    }

    if access_token:
        embed_kwargs["openai_api_key"] = access_token
        embed_kwargs["openai_api_type"] = "azure"
        embed_kwargs["default_headers"] = {
            "Authorization": f"Bearer {access_token}",
            "user_sid": "default_user",
        }
    elif api_key:
        embed_kwargs["openai_api_key"] = api_key
    else:
        raise ValueError("No API key or certificate available for Azure OpenAI Embeddings.")

    return AzureOpenAIEmbeddings(**embed_kwargs)
