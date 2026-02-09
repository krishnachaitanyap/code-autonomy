"""
Local embeddings for similarity search.
"""

from typing import Optional

_model = None


def _get_model():
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
            _model = SentenceTransformer("all-MiniLM-L6-v2")
        except ImportError:
            raise ImportError("sentence-transformers required for similarity search. pip install sentence-transformers")
    return _model


def embed(text: str) -> list[float]:
    """Embed text to vector."""
    model = _get_model()
    return model.encode(text, convert_to_numpy=True).tolist()


def get_similar_chunks(
    repo_path: str,
    query: str,
    top_k: int = 5,
) -> list[tuple[str, float, str]]:
    """
    Return top-k code chunks most similar to query.
    Returns list of (path, score, content).
    """
    from pathlib import Path

    from src.constants import CODE_EXTENSIONS, SKIP_DIRS

    model = _get_model()
    repo = Path(repo_path)
    if not repo.exists():
        return []

    chunks: list[tuple[str, str]] = []
    for f in repo.rglob("*"):
        if not f.is_file() or f.suffix not in CODE_EXTENSIONS:
            continue
        if any(p in f.relative_to(repo).parts for p in SKIP_DIRS):
            continue
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        rel = str(f.relative_to(repo)).replace("\\", "/")
        # Chunk by function/class or first 500 chars
        chunk = content[:2000] + ("\n..." if len(content) > 2000 else "")
        chunks.append((rel, chunk))

    if not chunks:
        return []

    texts = [c[1] for c in chunks]
    paths = [c[0] for c in chunks]
    q_vec = model.encode(query, convert_to_numpy=True)
    doc_vecs = model.encode(texts, convert_to_numpy=True)

    # Cosine similarity
    import numpy as np
    q_norm = q_vec / (np.linalg.norm(q_vec) + 1e-9)
    doc_norms = doc_vecs / (np.linalg.norm(doc_vecs, axis=1, keepdims=True) + 1e-9)
    scores = np.dot(doc_norms, q_norm)

    top_indices = np.argsort(scores)[::-1][:top_k]
    return [(paths[i], float(scores[i]), texts[i]) for i in top_indices if scores[i] > 0.1]
