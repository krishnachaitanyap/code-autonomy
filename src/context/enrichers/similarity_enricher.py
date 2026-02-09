"""
Similarity enricher: local embedding-based search for semantically relevant code.
"""

from pathlib import Path
from typing import Optional

from src.constants import CODE_EXTENSIONS, SKIP_DIRS
from src.context.base import ContextEnricher, EnrichmentResult


class SimilarityEnricher(ContextEnricher):
    """Adds code chunks similar to requirements via local embeddings."""

    def is_enabled(self, config: dict) -> bool:
        return config.get("context", {}).get("similarity_enricher", False)

    def enrich(
        self,
        repo_path: str,
        base_context: str,
        requirements: str,
        config: dict,
        grep_patterns: Optional[list[str]] = None,
    ) -> Optional[EnrichmentResult]:
        try:
            from src.embeddings import get_similar_chunks
        except ImportError:
            return None

        ctx = config.get("context", {})
        top_k = int(ctx.get("similarity_top_k", 5))

        try:
            chunks = get_similar_chunks(repo_path, requirements[:2000], top_k=top_k)
            if not chunks:
                return None

            lines = ["## Similarity search (relevant code)"]
            for path, score, content in chunks:
                lines.append(f"--- {path} (score: {score:.2f}) ---")
                lines.append(content[:3000] + ("\n... (truncated)" if len(content) > 3000 else ""))
                lines.append("")

            return EnrichmentResult(
                context_addition="\n\n" + "\n".join(lines),
                metadata={"files": [c[0] for c in chunks]},
            )
        except Exception:
            return None
