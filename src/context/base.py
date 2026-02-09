"""
Base definitions for context enrichers.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class EnrichmentResult:
    """What an enricher adds to context."""

    context_addition: str
    metadata: Optional[dict] = None


class ContextEnricher(ABC):
    """Enrichers add relevant content to the base context."""

    @property
    def name(self) -> str:
        return self.__class__.__name__

    def is_enabled(self, config: dict) -> bool:
        """Override to check config. Default: enabled."""
        return True

    @abstractmethod
    def enrich(
        self,
        repo_path: str,
        base_context: str,
        requirements: str,
        config: dict,
        grep_patterns: Optional[list[str]] = None,
    ) -> Optional[EnrichmentResult]:
        """Add context. Return None on failure (graceful degradation)."""
        pass
