"""
Grep enricher: requirement-based and config-based grep for better context.
"""

import re
from typing import Optional

from src.code.search import grep, format_grep_results
from src.context.base import ContextEnricher, EnrichmentResult


def _parse_grep_from_requirements(requirements: str) -> list[str]:
    """Extract # Grep: a, b, c from requirements."""
    patterns = []
    for line in requirements.splitlines():
        m = re.search(r"#\s*Grep\s*:\s*(.+)", line, re.I)
        if m:
            parts = [p.strip() for p in m.group(1).split(",") if p.strip()]
            patterns.extend(parts)
    return patterns


def _extract_identifiers(text: str) -> list[str]:
    """Extract CamelCase and snake_case identifiers that might be code symbols."""
    found = set()
    # CamelCase
    for m in re.finditer(r"\b([A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)*)\b", text):
        found.add(m.group(1))
    # snake_case (at least 2 segments)
    for m in re.finditer(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\b", text):
        found.add(m.group(1))
    return [p for p in sorted(found) if len(p) > 2][:15]


class GrepEnricher(ContextEnricher):
    """Adds grep results from requirements keywords and config patterns."""

    def is_enabled(self, config: dict) -> bool:
        return config.get("context", {}).get("grep_enricher", True)

    def enrich(
        self,
        repo_path: str,
        base_context: str,
        requirements: str,
        config: dict,
        grep_patterns: Optional[list[str]] = None,
    ) -> Optional[EnrichmentResult]:
        ctx = config.get("context", {})
        grep_from_req = ctx.get("grep_from_requirements", True)

        patterns = list(grep_patterns or [])
        if grep_from_req:
            patterns.extend(_parse_grep_from_requirements(requirements))
            patterns.extend(_extract_identifiers(requirements))

        patterns = list(dict.fromkeys(p for p in patterns if p))[:10]
        if not patterns:
            return None

        sections = []
        max_per_pattern = 4000
        for pattern in patterns:
            try:
                results = grep(repo_path, pattern, context_lines=2)
                if results:
                    formatted = format_grep_results(results)[:max_per_pattern]
                    sections.append(f"## Grep results for '{pattern}'\n{formatted}")
            except Exception:
                continue

        if not sections:
            return None
        return EnrichmentResult(
            context_addition="\n\n" + "\n\n".join(sections),
            metadata={"patterns": patterns, "sections": len(sections)},
        )
