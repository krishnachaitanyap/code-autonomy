"""
CodeIndex: composite dataclass + build / load / cache logic.

Orchestrates symbol_table, import_resolver, graph_builder, hierarchy,
and entity_embeddings into a single indexable structure.  Follows the
same caching pattern as ``build_or_load_consciousness``.
"""

import json
import logging
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from src.agent.knowledge import compute_repo_id
from src.code_index.symbol_table import SymbolTable, build_symbol_table
from src.code_index.import_resolver import resolve_imports
from src.code_index.graph_builder import DependencyGraph, build_dependency_graph
from src.code_index.hierarchy import ClassHierarchy, build_class_hierarchy
from src.code_index.entity_embeddings import EntityEmbeddings

logger = logging.getLogger(__name__)


@dataclass
class CodeIndex:
    """Complete code intelligence index for a repository."""

    repo_id: str
    indexed_at: float
    symbol_table: SymbolTable
    dependency_graph: DependencyGraph
    class_hierarchy: ClassHierarchy
    embeddings: EntityEmbeddings
    total_symbols: int
    total_files: int


def build_code_index(
    repo_path: str,
    consciousness: "ProjectConsciousness | None" = None,
    config: Optional[dict] = None,
) -> CodeIndex:
    """Build a fresh CodeIndex from the repository on disk.

    Args:
        repo_path: Absolute or relative path to the repo root.
        consciousness: Optional pre-built consciousness (unused for now,
                       reserved for seeding data).
        config: Full config dict (passed to embeddings for API key).
    """
    repo_id = compute_repo_id(repo_path)

    # 1. Symbol table
    symbol_table = build_symbol_table(repo_path)

    # 2. Import resolution
    import_map = resolve_imports(repo_path, symbol_table)

    # 3. Dependency graph
    dependency_graph = build_dependency_graph(repo_path, symbol_table, import_map)

    # 4. Class hierarchy
    class_hierarchy = build_class_hierarchy(symbol_table, import_map)

    # 5. Entity embeddings (best-effort — no failure if API key missing)
    embeddings = EntityEmbeddings()
    try:
        embeddings.build(repo_path, symbol_table, config=config)
    except Exception as exc:
        logger.warning("Could not build entity embeddings: %s", exc)

    return CodeIndex(
        repo_id=repo_id,
        indexed_at=time.time(),
        symbol_table=symbol_table,
        dependency_graph=dependency_graph,
        class_hierarchy=class_hierarchy,
        embeddings=embeddings,
        total_symbols=len(symbol_table),
        total_files=len(symbol_table.all_files),
    )


def _cache_dir(config: dict) -> Path:
    """Determine cache directory from config."""
    work_dir = config.get("workflow", {}).get("work_dir", "./workspace")
    ci_cfg = config.get("code_index", {})
    cache_subdir = ci_cfg.get("cache_dir", ".code-index")
    return Path(work_dir).resolve() / cache_subdir


def _save_code_index(code_index: CodeIndex, cache_path: Path) -> None:
    """Persist CodeIndex to disk (JSON + pickle for embeddings)."""
    cache_path.mkdir(parents=True, exist_ok=True)

    # Save metadata + symbol table + graphs + hierarchy as JSON
    meta = {
        "repo_id": code_index.repo_id,
        "indexed_at": code_index.indexed_at,
        "total_symbols": code_index.total_symbols,
        "total_files": code_index.total_files,
        "symbol_table": code_index.symbol_table.to_dict(),
        "dependency_graph": code_index.dependency_graph.to_dict(),
        "class_hierarchy": code_index.class_hierarchy.to_dict(),
    }
    json_path = cache_path / f"{code_index.repo_id}.json"
    # Atomic write: temp file + rename to prevent corrupt cache on crash
    fd, tmp = tempfile.mkstemp(dir=cache_path, suffix=".json.tmp")
    try:
        with open(fd, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
        Path(tmp).replace(json_path)
    except Exception:
        Path(tmp).unlink(missing_ok=True)
        raise

    # Save embeddings as pickle
    emb_path = cache_path / f"{code_index.repo_id}_embeddings.pkl"
    try:
        code_index.embeddings.save(str(emb_path))
    except Exception as exc:
        logger.warning("Could not save embeddings: %s", exc)


def _load_code_index(repo_id: str, cache_path: Path) -> Optional[CodeIndex]:
    """Load CodeIndex from disk cache. Returns None if not found or corrupt."""
    json_path = cache_path / f"{repo_id}.json"
    if not json_path.exists():
        return None

    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    try:
        symbol_table = SymbolTable.from_dict(data.get("symbol_table", []))
        dependency_graph = DependencyGraph.from_dict(data.get("dependency_graph", {}))
        class_hierarchy = ClassHierarchy.from_dict(data.get("class_hierarchy", {}))

        embeddings = EntityEmbeddings()
        emb_path = cache_path / f"{repo_id}_embeddings.pkl"
        embeddings.load(str(emb_path))  # best-effort

        return CodeIndex(
            repo_id=data["repo_id"],
            indexed_at=data["indexed_at"],
            symbol_table=symbol_table,
            dependency_graph=dependency_graph,
            class_hierarchy=class_hierarchy,
            embeddings=embeddings,
            total_symbols=data.get("total_symbols", len(symbol_table)),
            total_files=data.get("total_files", len(symbol_table.all_files)),
        )
    except Exception:
        return None


def build_or_load_code_index(
    repo_path: str,
    config: dict,
    repo_url: str = "",
    force_rebuild: bool = False,
    consciousness: "ProjectConsciousness | None" = None,
) -> CodeIndex:
    """Build or load CodeIndex from cache.

    Follows the same pattern as ``build_or_load_consciousness``:
    - Loads from cache if available and fresh (max_age_hours)
    - Falls back to full rebuild
    - Saves result to cache
    """
    ci_cfg = config.get("code_index", {})
    max_age_hours = float(ci_cfg.get("max_age_hours", 24) or 24)
    cache_path = _cache_dir(config)
    repo_id = compute_repo_id(repo_path, repo_url or config.get("repository", {}).get("repo_url", ""))

    if not force_rebuild:
        cached = _load_code_index(repo_id, cache_path)
        if cached:
            age_hours = (time.time() - cached.indexed_at) / 3600
            if max_age_hours <= 0 or age_hours <= max_age_hours:
                return cached

    # Full rebuild
    code_index = build_code_index(repo_path, consciousness=consciousness, config=config)
    # Update repo_id to match URL-based ID
    code_index.repo_id = repo_id

    # Save to cache
    try:
        _save_code_index(code_index, cache_path)
    except Exception as exc:
        logger.warning("Could not save code index to cache: %s", exc)

    return code_index
