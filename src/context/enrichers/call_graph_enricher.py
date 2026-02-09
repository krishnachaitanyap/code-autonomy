"""
Call graph enricher: include code related via call graph traversal.
"""

from pathlib import Path
from typing import Optional

from src.constants import CODE_EXTENSIONS, SKIP_DIRS
from src.context.base import ContextEnricher, EnrichmentResult


def _get_seed_paths_from_context(base_context: str, requirements: str) -> list[str]:
    """Extract file paths mentioned in base context (--- path ---) and requirements."""
    import re
    seeds = set()
    for m in re.finditer(r"---\s+([^\s\-]+)\s+---", base_context):
        seeds.add(m.group(1).strip())
    for m in re.finditer(r"[\w/]+\.(py|java|kt|js|ts)\b", requirements):
        seeds.add(m.group(0))
    return list(seeds)[:10]


class CallGraphEnricher(ContextEnricher):
    """Adds code related via call graph (callers/callees of seed functions)."""

    def is_enabled(self, config: dict) -> bool:
        return config.get("context", {}).get("call_graph_enricher", False)

    def enrich(
        self,
        repo_path: str,
        base_context: str,
        requirements: str,
        config: dict,
        grep_patterns: Optional[list[str]] = None,
    ) -> Optional[EnrichmentResult]:
        try:
            from src.context.call_graph import build_call_graph, get_related_paths
        except ImportError:
            return None

        ctx = config.get("context", {})
        depth = int(ctx.get("call_graph_depth", 2))

        seed_paths = _get_seed_paths_from_context(base_context, requirements)
        if not seed_paths:
            return None

        try:
            graph = build_call_graph(repo_path)
            related = get_related_paths(graph, seed_paths, depth=depth)
            if not related:
                return None

            repo = Path(repo_path)
            lines = ["## Call graph related code"]
            for rel_path in sorted(related)[:15]:
                full = repo / rel_path
                if not full.exists() or full.suffix not in CODE_EXTENSIONS:
                    continue
                if any(p in full.parts for p in SKIP_DIRS):
                    continue
                try:
                    content = full.read_text(encoding="utf-8", errors="replace")
                    lines.append(f"--- {rel_path} ---")
                    lines.append(content[:4000] + ("\n... (truncated)" if len(content) > 4000 else ""))
                    lines.append("")
                except Exception:
                    continue

            if len(lines) <= 1:
                return None
            return EnrichmentResult(
                context_addition="\n\n" + "\n".join(lines),
                metadata={"paths": list(related)},
            )
        except Exception:
            return None
