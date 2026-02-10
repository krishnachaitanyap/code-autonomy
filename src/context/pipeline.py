"""
Context building pipeline: orchestrates enrichers.
"""

from typing import Optional

from src.code.analyzer import load_codebase_context
from src.code.search import grep, format_grep_results
from src.context.enrichers import get_enabled_enrichers


def build_context(
    repo_path: str,
    requirements: str,
    config: dict,
    grep_patterns: Optional[list[str]] = None,
) -> str:
    """
    Build context using pipeline or legacy loader.
    Returns combined context string for AI prompt.
    """
    ctx_cfg = config.get("context", {})
    if not ctx_cfg.get("use_pipeline", False):
        # Legacy: load_codebase_context + grep (preserve existing behavior)
        context = load_codebase_context(repo_path)
        for pattern in (grep_patterns or [])[:5]:
            try:
                results = grep(repo_path, pattern, context_lines=2)
                if results:
                    context += f"\n\n## Grep results for '{pattern}':\n{format_grep_results(results)[:4000]}"
            except Exception:
                pass
        return context

    enrichers = get_enabled_enrichers(config)
    context = ""

    for enricher in enrichers:
        try:
            result = enricher.enrich(
                repo_path=repo_path,
                base_context=context,
                requirements=requirements,
                config=config,
                grep_patterns=grep_patterns,
            )
            if result and result.context_addition:
                context += result.context_addition
        except Exception:
            continue

    return context if context else load_codebase_context(repo_path)
