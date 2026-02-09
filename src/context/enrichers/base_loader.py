"""
Base loader enricher: wraps load_codebase_context.
Always runs first in the pipeline.
"""

from typing import Optional

from src.code_analyzer import load_codebase_context
from src.context.base import ContextEnricher, EnrichmentResult


class BaseLoaderEnricher(ContextEnricher):
    """Provides the initial codebase context from file loading."""

    def is_enabled(self, config: dict) -> bool:
        return True

    def enrich(
        self,
        repo_path: str,
        base_context: str,
        requirements: str,
        config: dict,
        grep_patterns: Optional[list[str]] = None,
    ) -> Optional[EnrichmentResult]:
        ctx = config.get("context", {})
        max_files = int(ctx.get("max_files", 30))
        max_chars = int(ctx.get("max_chars_per_file", 4000))
        content = load_codebase_context(repo_path, max_files=max_files, max_chars_per_file=max_chars)
        return EnrichmentResult(context_addition=content, metadata={"source": "base_loader"})
