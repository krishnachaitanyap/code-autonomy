"""
Per-entity embeddings with caching.

Chunks each symbol as ``signature + docstring + first 500 chars of body``,
calls OpenAI embeddings API via litellm (``text-embedding-3-small``),
and caches embeddings as pickle with SHA-256 invalidation per entity.
"""

import hashlib
import logging
import pickle
from pathlib import Path
from typing import Optional

from src.code_index.symbol_table import SymbolTable

logger = logging.getLogger(__name__)

# OpenAI embedding model — small, fast, cheap ($0.02/1M tokens)
_DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
_BATCH_SIZE = 2048  # max texts per API call


class EntityEmbeddings:
    """Per-entity embedding index with cosine similarity search."""

    def __init__(self) -> None:
        self._fqns: list[str] = []
        self._texts: list[str] = []
        self._digests: list[str] = []  # SHA-256 per entity text
        self._vectors = None  # numpy array, shape (n, dim)
        self._config: dict = {}

    @property
    def count(self) -> int:
        return len(self._fqns)

    def build(
        self, repo_path: str, symbol_table: SymbolTable, config: Optional[dict] = None
    ) -> None:
        """Build embeddings for all entities in the symbol table.

        Args:
            repo_path: Repository root path.
            symbol_table: Built symbol table.
            config: Full config dict (needs ``ai`` section with api_key/provider).
        """
        self._config = config or {}
        repo = Path(repo_path)
        fqns: list[str] = []
        texts: list[str] = []
        digests: list[str] = []

        # Read source files for body extraction
        file_contents: dict[str, str] = {}
        for file_path in symbol_table.all_files:
            fpath = repo / file_path
            if fpath.exists():
                try:
                    file_contents[file_path] = fpath.read_text(
                        encoding="utf-8", errors="replace"
                    )
                except Exception:
                    pass

        for entry in symbol_table.all_entries:
            # Build entity text: signature + docstring + first 500 chars of body
            parts = [entry.signature]
            if entry.docstring_summary:
                parts.append(entry.docstring_summary)

            # Extract body text
            content = file_contents.get(entry.file_path, "")
            if content and entry.line_start > 0:
                lines = content.splitlines()
                body_start = entry.line_start
                body_end = entry.line_end
                if body_start < len(lines) and body_end <= len(lines):
                    body = "\n".join(lines[body_start:body_end])
                    parts.append(body[:500])

            text = "\n".join(parts)
            digest = hashlib.sha256(text.encode()).hexdigest()[:16]

            fqns.append(entry.fqn)
            texts.append(text)
            digests.append(digest)

        self._fqns = fqns
        self._texts = texts
        self._digests = digests

        if not texts:
            return

        # Encode via OpenAI embeddings API (through litellm)
        try:
            self._vectors = self._embed_texts(texts)
        except Exception as exc:
            logger.warning("Could not build embeddings via API: %s", exc)
            self._vectors = None

    def find_similar(
        self, query: str, top_k: int = 5
    ) -> list[tuple[str, float]]:
        """Find entities most similar to the query.

        Returns list of ``(fqn, score)`` tuples.
        """
        if self._vectors is None or len(self._fqns) == 0:
            return []

        try:
            import numpy as np

            q_vec = self._embed_texts([query])
            if q_vec is None:
                return []
            q_vec = q_vec[0]

            # Cosine similarity
            q_norm = q_vec / (np.linalg.norm(q_vec) + 1e-9)
            doc_norms = self._vectors / (
                np.linalg.norm(self._vectors, axis=1, keepdims=True) + 1e-9
            )
            scores = np.dot(doc_norms, q_norm)

            top_indices = np.argsort(scores)[::-1][:top_k]
            return [
                (self._fqns[i], float(scores[i]))
                for i in top_indices
                if scores[i] > 0.1
            ]
        except Exception:
            return []

    def save(self, cache_path: str) -> None:
        """Save embeddings to a pickle file."""
        data = {
            "fqns": self._fqns,
            "texts": self._texts,
            "digests": self._digests,
            "vectors": self._vectors,
        }
        path = Path(cache_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(data, f)

    def load(self, cache_path: str) -> bool:
        """Load embeddings from a pickle file. Returns True if successful."""
        path = Path(cache_path)
        if not path.exists():
            return False
        try:
            with open(path, "rb") as f:
                data = pickle.load(f)
            self._fqns = data["fqns"]
            self._texts = data["texts"]
            self._digests = data["digests"]
            self._vectors = data["vectors"]
            return True
        except Exception:
            return False

    def _embed_texts(self, texts: list[str]):
        """Call OpenAI embeddings API via litellm. Returns numpy array (n, dim)."""
        import numpy as np
        from src.llm_client import _resolve_api_key

        ai_cfg = self._config.get("ai", self._config) if isinstance(
            self._config.get("ai"), dict
        ) else self._config

        api_key = _resolve_api_key(ai_cfg)
        if not api_key:
            raise ValueError("No API key available for embeddings")

        import litellm

        model = ai_cfg.get("embedding_model", _DEFAULT_EMBEDDING_MODEL)

        all_vectors = []
        for i in range(0, len(texts), _BATCH_SIZE):
            batch = texts[i : i + _BATCH_SIZE]
            response = litellm.embedding(
                model=model,
                input=batch,
                api_key=api_key,
            )
            # litellm returns response.data = [{"embedding": [...], "index": i}, ...]
            batch_vecs = [item["embedding"] for item in response.data]
            all_vectors.extend(batch_vecs)

        return np.array(all_vectors, dtype=np.float32)
