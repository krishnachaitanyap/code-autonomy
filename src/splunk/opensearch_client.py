"""
OpenSearch client for Splunk metadata RAG.

Performs knn similarity search on the ``splunk-metadata`` index to discover
which Splunk indexes, fields, sourcetypes, and relationships are relevant
to a user's question.  The results are formatted as context for the LLM
so it can construct precise SPL queries.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Embedding helper
# ---------------------------------------------------------------------------

def _embed_text(text: str, config: dict) -> list[float]:
    """Embed *text* using the configured embedding model via litellm.

    Falls back to the OpenAI SDK directly when litellm is unavailable.
    """
    model = config.get("embedding_model", "text-embedding-3-small")

    try:
        import litellm
        resp = litellm.embedding(model=model, input=[text])
        return resp.data[0]["embedding"]
    except ImportError:
        pass

    # Fallback: openai SDK
    import openai
    import os

    client = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
    resp = client.embeddings.create(model=model, input=[text])
    return resp.data[0].embedding


# ---------------------------------------------------------------------------
# OpenSearch client factory
# ---------------------------------------------------------------------------

def _get_opensearch_client(config: dict):
    """Create an ``OpenSearch`` client using AWS SigV4 auth.

    Credential resolution order (via boto3):
      1. Explicit access key / secret key / session token in config
      2. Environment variables (``AWS_ACCESS_KEY_ID``, etc.)
      3. AWS profile / IAM role (instance profile, ECS task role, etc.)

    Uses ``aws_requests_auth.AWSRequestsAuth`` to sign every request
    with SigV4 for the ``es`` (Elasticsearch/OpenSearch) service.
    """
    import boto3
    from aws_requests_auth.aws_auth import AWSRequestsAuth
    from opensearchpy import OpenSearch, RequestsHttpConnection

    endpoint = config["endpoint"].rstrip("/")
    region = config.get("region", "us-east-1")

    # --- Resolve AWS credentials via boto3 ---
    explicit_key = config.get("aws_access_key_id", "")
    explicit_secret = config.get("aws_secret_access_key", "")

    if explicit_key and explicit_secret:
        session = boto3.Session(
            aws_access_key_id=explicit_key,
            aws_secret_access_key=explicit_secret,
            region_name=region,
        )
    else:
        session = boto3.Session(region_name=region)

    credentials = session.get_credentials().get_frozen_credentials()

    # --- Extract host from endpoint URL ---
    host = endpoint.replace("https://", "").replace("http://", "")

    # --- Build SigV4 auth with AWSRequestsAuth ---
    awsauth = AWSRequestsAuth(
        aws_access_key=credentials.access_key,
        aws_secret_access_key=credentials.secret_key,
        aws_token=credentials.token or "",
        aws_host=host,
        aws_region=region,
        aws_service="es",
    )

    client = OpenSearch(
        hosts=[{"host": host, "port": 443}],
        http_auth=awsauth,
        use_ssl=True,
        verify_certs=config.get("verify_ssl", True),
        connection_class=RequestsHttpConnection,
        timeout=config.get("timeout", 30),
    )
    return client


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

_SPLUNK_SOURCE_FIELDS = [
    "index", "field", "tail_source", "description", "doc_type",
    "metadata", "relationship", "content",
]


def search_index(
    config: dict,
    index_name: str,
    query_text: str,
    top_k: int = 5,
    source_fields: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Search any OpenSearch index via knn similarity.

    This is the generic entry point — callers specify *index_name* and
    optionally which ``_source`` fields to return.

    Returns a list of hit dicts keyed by the requested source fields plus
    ``score``.
    """
    vector = _embed_text(query_text, config)
    client = _get_opensearch_client(config)

    body: dict[str, Any] = {
        "size": top_k,
        "query": {
            "knn": {
                "content_vector": {
                    "vector": vector,
                    "k": top_k,
                }
            }
        },
    }
    if source_fields:
        body["_source"] = source_fields

    try:
        resp = client.search(index=index_name, body=body)
    except Exception as exc:
        logger.error("OpenSearch knn search on '%s' failed: %s", index_name, exc)
        return []

    hits = []
    for h in resp.get("hits", {}).get("hits", []):
        src = h.get("_source", {})
        hit: dict[str, Any] = {"score": round(h.get("_score", 0.0), 4)}
        if source_fields:
            for f in source_fields:
                hit[f] = src.get(f, "" if f not in ("metadata", "relationship") else {})
        else:
            hit.update(src)
        hits.append(hit)
    return hits


def search_splunk_metadata(
    config: dict,
    query_text: str,
    top_k: int = 5,
    index_name: str | None = None,
) -> list[dict[str, Any]]:
    """Search the Splunk metadata OpenSearch index via knn.

    *index_name* resolution: explicit arg > ``config["index_name"]`` >
    ``"splunk-metadata"`` fallback.
    """
    resolved = index_name or config.get("index_name", "splunk-metadata")
    return search_index(
        config,
        index_name=resolved,
        query_text=query_text,
        top_k=top_k,
        source_fields=_SPLUNK_SOURCE_FIELDS,
    )


# ---------------------------------------------------------------------------
# Index listing
# ---------------------------------------------------------------------------

def list_available_indexes(config: dict) -> dict[str, str]:
    """Return the named indexes from config that have a non-empty value.

    Reads ``config["indexes"]`` (the named-index dict produced by
    ``config_loader``).  Falls back to the legacy ``config["index_name"]``
    key when the ``indexes`` dict is absent.

    Returns ``{ logical_name: actual_index_name }`` for every entry that
    has a truthy value.
    """
    indexes = config.get("indexes", {})
    available = {k: v for k, v in indexes.items() if v}
    if not available:
        # Backward compat: expose the single legacy index_name
        legacy = config.get("index_name", "")
        if legacy:
            available["splunk"] = legacy
    return available


# ---------------------------------------------------------------------------
# Format hits for LLM context
# ---------------------------------------------------------------------------

def format_metadata_context(hits: list[dict[str, Any]]) -> str:
    """Format OpenSearch hits into a readable context string for the LLM."""
    if not hits:
        return "No matching Splunk metadata found."

    lines = ["## Relevant Splunk Indexes & Fields\n"]
    for i, hit in enumerate(hits, 1):
        lines.append(f"### Hit {i} (score: {hit['score']})")
        if hit.get("index"):
            lines.append(f"- Index: `{hit['index']}`")
        if hit.get("field"):
            lines.append(f"- Field: `{hit['field']}`")
        if hit.get("tail_source"):
            lines.append(f"- Source: `{hit['tail_source']}`")
        if hit.get("doc_type"):
            lines.append(f"- Doc Type: {hit['doc_type']}")

        # Metadata (ENV, DC, etc.)
        meta = hit.get("metadata", {})
        meta_parts = []
        if meta.get("ENV"):
            meta_parts.append(f"ENV={meta['ENV']}")
        if meta.get("DC"):
            meta_parts.append(f"DC={meta['DC']}")
        if meta_parts:
            lines.append(f"- Environment: {', '.join(meta_parts)}")

        if hit.get("description"):
            lines.append(f"- Description: {hit['description']}")

        # Relationships
        rels = hit.get("relationship", {})
        if rels:
            rel_parts = [f"{k}={v}" for k, v in rels.items() if v]
            if rel_parts:
                lines.append(f"- Relationships: {', '.join(rel_parts)}")

        lines.append("")
    return "\n".join(lines)
