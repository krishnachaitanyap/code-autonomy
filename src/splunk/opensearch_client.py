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
    """Create an ``OpenSearch`` client using AWS SigV4 auth."""
    from opensearchpy import OpenSearch, RequestsHttpConnection
    from requests_aws4auth import AWS4Auth

    endpoint = config["endpoint"].rstrip("/")
    region = config.get("region", "us-east-1")
    access_key = config.get("aws_access_key_id", "")
    secret_key = config.get("aws_secret_access_key", "")

    awsauth = AWS4Auth(access_key, secret_key, region, "es")

    # Strip scheme for host param
    host = endpoint.replace("https://", "").replace("http://", "")

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

def search_splunk_metadata(
    config: dict,
    query_text: str,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Search the ``splunk-metadata`` OpenSearch index via knn.

    1. Embeds *query_text* using the configured embedding model.
    2. Runs a knn query on the ``content_vector`` field.
    3. Returns a list of hit dicts with keys:
       ``index``, ``field``, ``tail_source``, ``metadata``, ``relationship``,
       ``description``, ``score``.
    """
    vector = _embed_text(query_text, config)
    index_name = config.get("index_name", "splunk-metadata")

    client = _get_opensearch_client(config)

    body = {
        "size": top_k,
        "query": {
            "knn": {
                "content_vector": {
                    "vector": vector,
                    "k": top_k,
                }
            }
        },
        "_source": [
            "index", "field", "tail_source", "description", "doc_type",
            "metadata", "relationship", "content",
        ],
    }

    try:
        resp = client.search(index=index_name, body=body)
    except Exception as exc:
        logger.error("OpenSearch knn search failed: %s", exc)
        return []

    hits = []
    for h in resp.get("hits", {}).get("hits", []):
        src = h.get("_source", {})
        hits.append({
            "score": round(h.get("_score", 0.0), 4),
            "index": src.get("index", ""),
            "field": src.get("field", ""),
            "tail_source": src.get("tail_source", ""),
            "description": src.get("description", ""),
            "doc_type": src.get("doc_type", ""),
            "metadata": src.get("metadata", {}),
            "relationship": src.get("relationship", {}),
            "content": src.get("content", ""),
        })
    return hits


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
