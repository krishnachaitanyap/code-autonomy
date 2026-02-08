"""
Project consciousness: automatic indexing of project structure and conventions.
Stored in file or OpenSearch; consumed as context for AI without explicit "learn from" instructions.
"""

import hashlib
import json
import re
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from src.constants import CODE_EXTENSIONS, SKIP_DIRS


@dataclass
class ProjectConsciousness:
    """Serializable project model: structure, conventions, samples."""
    repo_id: str
    indexed_at: float
    structure: dict  # tree: {dir: {subdirs: [...], files: [...]}}
    conventions: dict  # build_tool, language, test_framework, naming_style
    implementation_samples: list  # [{path, excerpt, metadata}]
    signatures: list  # [{path, name, type}]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ProjectConsciousness":
        return cls(
            repo_id=d["repo_id"],
            indexed_at=d["indexed_at"],
            structure=d.get("structure", {}),
            conventions=d.get("conventions", {}),
            implementation_samples=d.get("implementation_samples", []),
            signatures=d.get("signatures", []),
        )

    def to_context_string(self, max_samples_chars: int = 25000) -> str:
        """Render as context string for AI prompt."""
        lines = ["## Project context (structure and conventions)"]
        lines.append(f"Language/build: {self.conventions.get('language', 'unknown')}, {self.conventions.get('build_tool', 'unknown')}")
        lines.append(f"Test framework: {self.conventions.get('test_framework', 'unknown')}")
        lines.append(f"Naming: {self.conventions.get('naming_style', 'unknown')}")
        lines.append("")
        lines.append("Directory structure (key paths):")
        lines.append(_format_structure(self.structure, indent=0, max_depth=3))
        if self.signatures:
            lines.append("")
            lines.append("Key classes/functions:")
            for sig in self.signatures[:30]:
                lines.append(f"  {sig.get('path', '')}: {sig.get('type', '')} {sig.get('name', '')}")
        if self.implementation_samples:
            lines.append("")
            lines.append("Representative code samples:")
            total = 0
            for s in self.implementation_samples:
                excerpt = s.get("excerpt", "")
                if total + len(excerpt) > max_samples_chars:
                    break
                lines.append(f"--- {s.get('path', '')} ---")
                lines.append(excerpt[:3000] + ("\n... (truncated)" if len(excerpt) > 3000 else ""))
                lines.append("")
                total += len(excerpt)
        return "\n".join(lines) if len(lines) > 1 else ""


def _format_structure(tree: dict, indent: int, max_depth: int) -> str:
    if indent > max_depth:
        return ""
    lines = []
    subdirs = tree.get("subdirs", {})
    files = tree.get("files", [])
    prefix = "  " * indent
    for d in sorted(subdirs.keys())[:15]:
        lines.append(f"{prefix}{d}/")
        lines.append(_format_structure(subdirs[d], indent + 1, max_depth))
    for f in sorted(files)[:12]:
        lines.append(f"{prefix}{f}")
    return "\n".join(lines)


def _compute_repo_id(repo_path: str, repo_url: str = "") -> str:
    """Stable ID for cache key."""
    raw = (repo_url or repo_path).strip()
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _build_structure_tree(repo: Path) -> dict:
    """Build directory tree (subdirs, files)."""
    def get_or_create_node(root: dict, path_parts: list) -> dict:
        current = root
        for part in path_parts:
            if "subdirs" not in current:
                current["subdirs"] = {}
            if part not in current["subdirs"]:
                current["subdirs"][part] = {"subdirs": {}, "files": []}
            current = current["subdirs"][part]
        return current

    tree: dict = {"subdirs": {}, "files": []}
    for f in repo.rglob("*"):
        if not f.is_file():
            continue
        parts = f.relative_to(repo).parts
        if any(p in SKIP_DIRS for p in parts):
            continue
        if f.suffix not in CODE_EXTENSIONS and f.suffix not in {".xml", ".gradle", ".kts", ".toml", ".ini", ".yml", ".yaml", ".json"}:
            continue
        parts_list = list(parts)
        if len(parts_list) == 1:
            tree["files"].append(parts_list[0])
        else:
            parent = get_or_create_node(tree, parts_list[:-1])
            parent["files"].append(parts_list[-1])
    return tree


def _detect_conventions(repo: Path) -> dict:
    """Detect build tool, language, test framework, naming."""
    conventions = {"build_tool": "unknown", "language": "unknown", "test_framework": "unknown", "naming_style": "unknown"}
    if (repo / "pom.xml").exists():
        conventions["build_tool"] = "maven"
        conventions["language"] = "java"
        # Check JUnit 4 vs 5
        try:
            pom = (repo / "pom.xml").read_text(errors="replace")
            if "junit-jupiter" in pom or "org.junit.jupiter" in pom:
                conventions["test_framework"] = "junit5"
            elif "junit" in pom:
                conventions["test_framework"] = "junit4"
        except Exception:
            pass
    elif (repo / "build.gradle").exists() or (repo / "build.gradle.kts").exists():
        conventions["build_tool"] = "gradle"
        conventions["language"] = "java"
    if (repo / "pytest.ini").exists() or "pytest" in str((repo / "pyproject.toml").read_text(errors="replace") if (repo / "pyproject.toml").exists() else ""):
        conventions["test_framework"] = "pytest"
        conventions["language"] = "python"
    elif any(repo.rglob("test_*.py")) or any(repo.rglob("*_test.py")):
        conventions["test_framework"] = "pytest_or_unittest"
        conventions["language"] = "python"
    if conventions["language"] == "unknown":
        if any(repo.rglob("*.py")):
            conventions["language"] = "python"
        elif any(repo.rglob("*.java")):
            conventions["language"] = "java"
    conventions["naming_style"] = "camelCase" if conventions["language"] == "java" else "snake_case"
    return conventions


def _extract_signatures(repo: Path, rel_path: str, content: str) -> list:
    """Extract class/function signatures from file."""
    sigs = []
    path_lower = rel_path.lower()
    if path_lower.endswith(".java"):
        for m in re.finditer(r"(?:public\s+)?(?:static\s+)?(?:class|interface|enum)\s+(\w+)", content):
            sigs.append({"path": rel_path, "type": "class", "name": m.group(1)})
        for m in re.finditer(r"(?:public|private|protected)\s+(?:static\s+)?[\w<>\[\],\s]+\s+(\w+)\s*\(", content):
            sigs.append({"path": rel_path, "type": "method", "name": m.group(1)})
    elif path_lower.endswith(".py"):
        for m in re.finditer(r"^def\s+(\w+)\s*\(", content, re.MULTILINE):
            sigs.append({"path": rel_path, "type": "function", "name": m.group(1)})
        for m in re.finditer(r"^class\s+(\w+)", content, re.MULTILINE):
            sigs.append({"path": rel_path, "type": "class", "name": m.group(1)})
    return sigs


def build_consciousness(repo_path: str, repo_url: str = "") -> ProjectConsciousness:
    """Index the repository and build consciousness."""
    repo = Path(repo_path)
    if not repo.exists():
        return ProjectConsciousness(
            repo_id=_compute_repo_id(repo_path, repo_url),
            indexed_at=time.time(),
            structure={},
            conventions={},
            implementation_samples=[],
            signatures=[],
        )
    repo_id = _compute_repo_id(repo_path, repo_url)
    structure = _build_structure_tree(repo)
    conventions = _detect_conventions(repo)
    samples: list = []
    signatures: list = []
    total_chars = 0
    max_chars = 30000
    for f in sorted(repo.rglob("*"), key=lambda x: str(x)):
        if not f.is_file():
            continue
        if f.suffix not in CODE_EXTENSIONS:
            continue
        parts = f.relative_to(repo).parts
        if any(p in SKIP_DIRS for p in parts):
            continue
        rel = str(f.relative_to(repo)).replace("\\", "/")
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        sigs = _extract_signatures(repo, rel, content)
        signatures.extend(sigs[:5])
        excerpt = content[:2500]
        if len(content) > 2500:
            excerpt += "\n... (truncated)"
        if total_chars + len(excerpt) <= max_chars:
            samples.append({
                "path": rel,
                "excerpt": excerpt,
                "metadata": {"lines": len(content.splitlines())},
            })
            total_chars += len(excerpt)
        if len(samples) >= 15:
            break
    return ProjectConsciousness(
        repo_id=repo_id,
        indexed_at=time.time(),
        structure=structure,
        conventions=conventions,
        implementation_samples=samples,
        signatures=signatures[:80],
    )


class ConsciousnessStore(ABC):
    """Abstract storage for project consciousness."""

    @abstractmethod
    def save(self, repo_id: str, data: ProjectConsciousness) -> None:
        pass

    @abstractmethod
    def load(self, repo_id: str) -> Optional[ProjectConsciousness]:
        pass

    @abstractmethod
    def search(self, repo_id: str, query: str, top_k: int = 5) -> Optional[list[dict]]:
        """Semantic/keyword search. Returns None if not supported."""
        pass


class FileConsciousnessStore(ConsciousnessStore):
    """JSON file-backed storage."""

    def __init__(self, cache_dir: str):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, repo_id: str) -> Path:
        return self.cache_dir / f"{repo_id}.json"

    def save(self, repo_id: str, data: ProjectConsciousness) -> None:
        self._path(repo_id).write_text(json.dumps(data.to_dict(), indent=2), encoding="utf-8")

    def load(self, repo_id: str) -> Optional[ProjectConsciousness]:
        p = self._path(repo_id)
        if not p.exists():
            return None
        try:
            return ProjectConsciousness.from_dict(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            return None

    def search(self, repo_id: str, query: str, top_k: int = 5) -> Optional[list[dict]]:
        """File backend: return None (no semantic search)."""
        return None


def get_store(backend: str, cache_dir: str, opensearch_url: str = "", opensearch_index: str = "code_consciousness") -> ConsciousnessStore:
    """Factory: file or opensearch."""
    if backend == "opensearch" and opensearch_url:
        try:
            from src.consciousness_opensearch import OpenSearchConsciousnessStore
            return OpenSearchConsciousnessStore(url=opensearch_url, index=opensearch_index)
        except ImportError:
            return FileConsciousnessStore(cache_dir)
    return FileConsciousnessStore(cache_dir)


def build_or_load_consciousness(
    repo_path: str,
    config: dict,
    repo_url: str = "",
    force_rebuild: bool = False,
) -> ProjectConsciousness:
    """Build or load from cache. Returns consciousness (never empty)."""
    cfg = config.get("consciousness", {})
    backend = cfg.get("backend", "file")
    cache_dir = cfg.get("cache_dir", ".consciousness")
    work_dir = config.get("workflow", {}).get("work_dir", "./workspace")
    max_age_hours = float(cfg.get("max_age_hours", 24) or 24)
    cache_path = Path(work_dir).resolve() / cache_dir
    opensearch_url = cfg.get("opensearch_url", "")
    opensearch_index = cfg.get("opensearch_index", "code_consciousness")
    store = get_store(backend, str(cache_path), opensearch_url=opensearch_url, opensearch_index=opensearch_index)
    repo_id = _compute_repo_id(repo_path, repo_url or config.get("repository", {}).get("repo_url", ""))
    if not force_rebuild:
        cached = store.load(repo_id)
        if cached:
            age_hours = (time.time() - cached.indexed_at) / 3600
            if max_age_hours <= 0 or age_hours <= max_age_hours:
                return cached
    consciousness = build_consciousness(repo_path, repo_url)
    store.save(repo_id, consciousness)
    return consciousness
