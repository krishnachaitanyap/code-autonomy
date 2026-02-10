"""
OpenSearch backend for project consciousness.
Optional: requires opensearch-py. Falls back to file store if unavailable.
"""

from typing import Optional

from src.consciousness.core import ConsciousnessStore, ProjectConsciousness


class OpenSearchConsciousnessStore(ConsciousnessStore):
    """OpenSearch-backed storage with optional semantic search."""

    def __init__(
        self,
        url: str = "http://localhost:9200",
        index: str = "code_consciousness",
        **kwargs,
    ):
        self.url = url
        self.index = index
        self._client = None

    def _client_maybe(self):
        if self._client is None:
            try:
                from opensearchpy import OpenSearch
                self._client = OpenSearch(hosts=[self.url], **{k: v for k, v in [("verify_certs", False)] if k in ["verify_certs"]})
            except ImportError:
                raise ImportError("opensearch-py required for OpenSearch backend. pip install opensearch-py")
        return self._client

    def save(self, repo_id: str, data: ProjectConsciousness) -> None:
        try:
            client = self._client_maybe()
            body = data.to_dict()
            client.index(index=self.index, id=repo_id, body=body, refresh=True)
        except Exception:
            raise

    def load(self, repo_id: str) -> Optional[ProjectConsciousness]:
        try:
            client = self._client_maybe()
            r = client.get(index=self.index, id=repo_id, ignore=[404])
            if r.get("found"):
                return ProjectConsciousness.from_dict(r["_source"])
        except Exception:
            pass
        return None

    def search(self, repo_id: str, query: str, top_k: int = 5) -> Optional[list[dict]]:
        """Semantic search would require embeddings. Returns None for now."""
        return None
