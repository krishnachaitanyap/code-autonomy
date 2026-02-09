"""
Context enrichers registry.
"""

from typing import Optional

from src.context.base import ContextEnricher
from src.context.enrichers.base_loader import BaseLoaderEnricher
from src.context.enrichers.grep_enricher import GrepEnricher
from src.context.enrichers.similarity_enricher import SimilarityEnricher
from src.context.enrichers.call_graph_enricher import CallGraphEnricher


def get_enabled_enrichers(config: dict) -> list[ContextEnricher]:
    """Return enrichers in pipeline order. BaseLoader first, then optional enrichers."""
    ctx = config.get("context", {})
    enrichers: list[ContextEnricher] = [BaseLoaderEnricher()]

    if ctx.get("grep_enricher", True):
        enrichers.append(GrepEnricher())

    if ctx.get("similarity_enricher", False):
        enrichers.append(SimilarityEnricher())

    if ctx.get("call_graph_enricher", False):
        enrichers.append(CallGraphEnricher())

    return enrichers
