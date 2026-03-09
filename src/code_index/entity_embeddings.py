"""
Per-entity embeddings with caching, sliding-window chunking, and BM25 hybrid retrieval.

Chunks each symbol as ``signature + docstring + body``, with sliding-window
chunking for large methods (>1000 chars).  Optionally prepends import context.

Uses OpenAI embeddings API via litellm (``text-embedding-3-small``) for vector
search, and BM25 for keyword search, fused via Reciprocal Rank Fusion (RRF).

Caches embeddings as pickle with SHA-256 invalidation per entity.
"""

import hashlib
import logging
import pickle
import re
from pathlib import Path
from typing import Optional

from src.code_index.symbol_table import SymbolTable

logger = logging.getLogger(__name__)

# OpenAI embedding model — small, fast, cheap ($0.02/1M tokens)
_DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
_BATCH_SIZE = 2048  # max texts per API call
_MAX_CONCURRENT_BATCHES = 5  # max parallel API calls

# Sliding window chunking defaults
_CHUNK_SIZE = 800        # chars per embedding chunk
_CHUNK_OVERLAP = 200     # overlap between consecutive chunks
_SMALL_BODY_LIMIT = 1000  # body <= this: single chunk (original behavior)


def _sliding_window_chunks(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Split text into overlapping windows. Returns at least one chunk."""
    if not text or chunk_size <= 0:
        return [text] if text else [""]

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        if end >= len(text):
            break
        start = end - overlap
        if start <= 0 and len(chunks) > 0:
            break

    return chunks if chunks else [text]


def _tokenize(text: str) -> list[str]:
    """Tokenize text for BM25: split camelCase, lowercase, strip non-alphanumeric."""
    # Split camelCase: findByStatus → find By Status
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text)
    # Split on non-alphanumeric
    tokens = re.split(r"[^a-zA-Z0-9]+", text.lower())
    # Keep tokens > 1 char
    return [t for t in tokens if len(t) > 1]


class EntityEmbeddings:
    """Per-entity embedding index with cosine similarity + BM25 hybrid search."""

    def __init__(self) -> None:
        self._fqns: list[str] = []
        self._texts: list[str] = []
        self._digests: list[str] = []  # SHA-256 per entity text
        self._vectors = None  # numpy array, shape (n, dim)
        self._chunk_indices: list[int] = []  # chunk index per embedding (0 for single-chunk)
        self._config: dict = {}

        # BM25 index
        self._bm25 = None  # BM25Okapi instance
        self._bm25_fqns: list[str] = []
        self._bm25_corpus: list[list[str]] = []

        # Lazy build support
        self._deferred_build_args: Optional[dict] = None
        self._build_attempted: bool = False

    @property
    def count(self) -> int:
        return len(self._fqns)

    def __len__(self) -> int:
        return len(self._fqns)

    def ensure_built(self) -> None:
        """Build embeddings from deferred args on first use."""
        if self._build_attempted or self._deferred_build_args is None:
            return
        self._build_attempted = True
        args = self._deferred_build_args
        self._deferred_build_args = None
        try:
            self.build(
                repo_path=args["repo_path"],
                symbol_table=args["symbol_table"],
                config=args.get("config"),
                file_contents=args.get("file_contents"),
            )
            logger.info("Lazy embedding build completed: %d embeddings", len(self))
        except Exception as exc:
            logger.warning("Lazy embedding build failed: %s", exc)

    def build(
        self,
        repo_path: str,
        symbol_table: SymbolTable,
        config: Optional[dict] = None,
        file_contents: Optional[dict[str, str]] = None,
        import_map: Optional[dict[str, dict[str, str]]] = None,
    ) -> None:
        """Build embeddings for all entities in the symbol table.

        Args:
            repo_path: Repository root path.
            symbol_table: Built symbol table.
            config: Full config dict (needs ``ai`` section with api_key/provider).
            file_contents: Optional pre-read file contents ``{rel_path: source}``.
                If provided, skips reading files from disk.
            import_map: Optional import map for prepending import context.
        """
        self._config = config or {}
        ci_cfg = self._config.get("code_index", {})
        repo = Path(repo_path)

        # Config-driven chunking parameters
        chunk_size = int(ci_cfg.get("chunk_size", _CHUNK_SIZE))
        chunk_overlap = int(ci_cfg.get("chunk_overlap", _CHUNK_OVERLAP))
        small_body_limit = int(ci_cfg.get("small_body_limit", _SMALL_BODY_LIMIT))
        include_import_context = str(ci_cfg.get("include_import_context", "false")).lower() in ("true", "1", "yes")
        enable_bm25 = str(ci_cfg.get("enable_bm25", "true")).lower() in ("true", "1", "yes")

        fqns: list[str] = []
        texts: list[str] = []
        digests: list[str] = []
        chunk_indices: list[int] = []

        # Use cached contents or read source files for body extraction
        if file_contents is None:
            file_contents = {}
            for file_path in symbol_table.all_files:
                fpath = repo / file_path
                if fpath.exists():
                    try:
                        file_contents[file_path] = fpath.read_text(
                            encoding="utf-8", errors="replace"
                        )
                    except Exception:
                        pass

        # Pre-compute import context per file if enabled
        import_context: dict[str, str] = {}
        if include_import_context:
            import_context = _extract_import_context(file_contents)

        for entry in symbol_table.all_entries:
            # Build header: signature + docstring
            header_parts = [entry.signature]
            if entry.docstring_summary:
                header_parts.append(entry.docstring_summary)
            header = "\n".join(header_parts)

            # Prepend import context if enabled
            prefix = ""
            if include_import_context and entry.file_path in import_context:
                prefix = f"[imports] {import_context[entry.file_path]}\n"

            # Extract body text
            content = file_contents.get(entry.file_path, "")
            body = ""
            if content and entry.line_start > 0:
                lines = content.splitlines()
                body_start = entry.line_start
                body_end = entry.line_end
                if body_start < len(lines) and body_end <= len(lines):
                    body = "\n".join(lines[body_start:body_end])

            if len(body) <= small_body_limit:
                # Single chunk: full body (improved from old 500-char limit)
                text = prefix + header + ("\n" + body if body else "")
                digest = hashlib.sha256(text.encode()).hexdigest()[:16]
                fqns.append(entry.fqn)
                texts.append(text)
                digests.append(digest)
                chunk_indices.append(0)
            else:
                # Multiple chunks with sliding window
                chunks = _sliding_window_chunks(body, chunk_size, chunk_overlap)
                for ci, chunk in enumerate(chunks):
                    chunk_header = f"{header}\n[chunk {ci + 1}/{len(chunks)}]"
                    text = prefix + chunk_header + "\n" + chunk
                    digest = hashlib.sha256(text.encode()).hexdigest()[:16]
                    fqns.append(entry.fqn)
                    texts.append(text)
                    digests.append(digest)
                    chunk_indices.append(ci)

        self._fqns = fqns
        self._texts = texts
        self._digests = digests
        self._chunk_indices = chunk_indices

        if not texts:
            return

        # Build BM25 index
        if enable_bm25:
            self._build_bm25_index(fqns, texts)

        # Encode via OpenAI embeddings API (through litellm)
        import time
        t0 = time.time()
        logger.info("Embedding %d texts in batches of %d (max %d concurrent)...",
                     len(texts), _BATCH_SIZE, _MAX_CONCURRENT_BATCHES)
        try:
            self._vectors = self._embed_texts(texts)
            elapsed = time.time() - t0
            logger.info("Embedding completed: %d vectors in %.2fs", len(texts), elapsed)
        except Exception as exc:
            logger.warning("Could not build embeddings via API: %s", exc)
            self._vectors = None

    def find_similar(
        self, query: str, top_k: int = 5
    ) -> list[tuple[str, float]]:
        """Find entities most similar to the query using hybrid vector + BM25 search.

        Returns list of ``(fqn, score)`` tuples, deduplicated by FQN.
        """
        self.ensure_built()
        vec_results = self._find_by_vector(query, top_k * 2)
        bm25_results = self._find_by_bm25(query, top_k * 2)

        if vec_results and bm25_results:
            merged = _reciprocal_rank_fusion(vec_results, bm25_results)
        elif vec_results:
            merged = vec_results
        elif bm25_results:
            merged = bm25_results
        else:
            return []

        # Deduplicate by FQN (keep highest score per FQN)
        seen: dict[str, float] = {}
        for fqn, score in merged:
            if fqn not in seen or score > seen[fqn]:
                seen[fqn] = score

        results = sorted(seen.items(), key=lambda x: -x[1])[:top_k]
        return [(fqn, score) for fqn, score in results if score > 0.0]

    def _find_by_vector(
        self, query: str, top_k: int
    ) -> list[tuple[str, float]]:
        """Vector-based cosine similarity search."""
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

    def _find_by_bm25(
        self, query: str, top_k: int
    ) -> list[tuple[str, float]]:
        """BM25 keyword search."""
        if self._bm25 is None or not self._bm25_fqns:
            return []

        try:
            tokens = _tokenize(query)
            if not tokens:
                return []
            scores = self._bm25.get_scores(tokens)
            top_indices = sorted(range(len(scores)), key=lambda i: -scores[i])[:top_k]
            return [
                (self._bm25_fqns[i], float(scores[i]))
                for i in top_indices
                if scores[i] > 0.0
            ]
        except Exception:
            return []

    def _build_bm25_index(self, fqns: list[str], texts: list[str]) -> None:
        """Build BM25 index, deduplicating chunks by FQN (merges chunk texts)."""
        try:
            from rank_bm25 import BM25Okapi
        except ImportError:
            logger.debug("rank_bm25 not installed, BM25 search disabled")
            return

        # Merge chunk texts by FQN
        merged: dict[str, str] = {}
        for fqn, text in zip(fqns, texts):
            if fqn in merged:
                merged[fqn] += " " + text
            else:
                merged[fqn] = text

        self._bm25_fqns = list(merged.keys())
        self._bm25_corpus = [_tokenize(text) for text in merged.values()]

        if self._bm25_corpus:
            self._bm25 = BM25Okapi(self._bm25_corpus)

    def save(self, cache_path: str) -> None:
        """Save embeddings to a pickle file."""
        data = {
            "fqns": self._fqns,
            "texts": self._texts,
            "digests": self._digests,
            "vectors": self._vectors,
            "chunk_indices": self._chunk_indices,
            "bm25_fqns": self._bm25_fqns,
            "bm25_corpus": self._bm25_corpus,
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
            # Backward-compatible: old caches won't have these keys
            self._chunk_indices = data.get("chunk_indices", [0] * len(self._fqns))
            self._bm25_fqns = data.get("bm25_fqns", [])
            self._bm25_corpus = data.get("bm25_corpus", [])
            # Rebuild BM25 from corpus
            if self._bm25_corpus:
                try:
                    from rank_bm25 import BM25Okapi
                    self._bm25 = BM25Okapi(self._bm25_corpus)
                except ImportError:
                    pass
            return True
        except Exception:
            return False

    def _embed_single_batch(self, texts, model, api_key):
        """Embed a single batch of texts. Returns numpy array (n, dim)."""
        import numpy as np
        import litellm

        response = litellm.embedding(model=model, input=texts, api_key=api_key)
        batch_vecs = [item["embedding"] for item in response.data]
        return np.array(batch_vecs, dtype=np.float32)

    def _embed_texts(self, texts: list[str]):
        """Call embeddings API. Uses Azure OpenAI when provider=azure, else litellm."""
        import numpy as np
        from src.llm_client import _is_azure_provider, _resolve_api_key

        ai_cfg = self._config.get("ai", self._config) if isinstance(
            self._config.get("ai"), dict
        ) else self._config

        # --- Azure OpenAI path ---
        if _is_azure_provider(ai_cfg):
            return self._embed_texts_azure(texts)

        # --- Standard OpenAI / litellm path ---
        api_key = _resolve_api_key(ai_cfg)
        if not api_key:
            raise ValueError("No API key available for embeddings")

        model = ai_cfg.get("embedding_model", _DEFAULT_EMBEDDING_MODEL)

        # Split into batches
        batches = [(i, texts[i : i + _BATCH_SIZE]) for i in range(0, len(texts), _BATCH_SIZE)]

        if len(batches) <= 1:
            # Single batch — no threading overhead
            return self._embed_single_batch(batches[0][1], model, api_key)

        # Concurrent execution
        from concurrent.futures import ThreadPoolExecutor, as_completed

        results = [None] * len(batches)  # preserve order

        def _call_api(batch_idx, batch_texts):
            vecs = self._embed_single_batch(batch_texts, model, api_key)
            return batch_idx, vecs

        max_workers = min(_MAX_CONCURRENT_BATCHES, len(batches))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(_call_api, idx, batch): idx
                for idx, (_, batch) in enumerate(batches)
            }
            for future in as_completed(futures):
                batch_idx, vecs = future.result()
                results[batch_idx] = vecs

        return np.concatenate(results, axis=0)

    def _embed_texts_azure(self, texts: list[str]):
        """Call Azure OpenAI Embeddings via LangChain. Returns numpy array (n, dim)."""
        import numpy as np
        from src.azure_openai_client import create_embeddings_client

        client = create_embeddings_client(self._config)

        # Split into batches
        batches = [(i, texts[i : i + _BATCH_SIZE]) for i in range(0, len(texts), _BATCH_SIZE)]

        if len(batches) <= 1:
            vecs = client.embed_documents(batches[0][1])
            return np.array(vecs, dtype=np.float32)

        # Concurrent execution
        from concurrent.futures import ThreadPoolExecutor, as_completed

        results = [None] * len(batches)

        def _call_api(batch_idx, batch_texts):
            vecs = client.embed_documents(batch_texts)
            return batch_idx, np.array(vecs, dtype=np.float32)

        max_workers = min(_MAX_CONCURRENT_BATCHES, len(batches))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(_call_api, idx, batch): idx
                for idx, (_, batch) in enumerate(batches)
            }
            for future in as_completed(futures):
                batch_idx, vecs = future.result()
                results[batch_idx] = vecs

        return np.concatenate(results, axis=0)


def _extract_import_context(file_contents: dict[str, str]) -> dict[str, str]:
    """Extract import lines from each file, truncated to 300 chars."""
    result: dict[str, str] = {}
    for rel_path, content in file_contents.items():
        import_lines = []
        for line in content.splitlines():
            stripped = line.strip()
            if rel_path.endswith(".py"):
                if stripped.startswith("import ") or stripped.startswith("from "):
                    import_lines.append(stripped)
            elif rel_path.endswith(".java"):
                if stripped.startswith("import "):
                    import_lines.append(stripped)
        if import_lines:
            text = "; ".join(import_lines)
            result[rel_path] = text[:300]
    return result


def _reciprocal_rank_fusion(
    results_a: list[tuple[str, float]],
    results_b: list[tuple[str, float]],
    k: int = 60,
) -> list[tuple[str, float]]:
    """Standard RRF: score(doc) = sum(1/(k + rank)) across both lists."""
    scores: dict[str, float] = {}

    for rank, (fqn, _) in enumerate(results_a):
        scores[fqn] = scores.get(fqn, 0.0) + 1.0 / (k + rank + 1)

    for rank, (fqn, _) in enumerate(results_b):
        scores[fqn] = scores.get(fqn, 0.0) + 1.0 / (k + rank + 1)

    return sorted(scores.items(), key=lambda x: -x[1])
