"""
Project consciousness: automatic indexing of project structure and conventions.
Stored in file or OpenSearch; consumed as context for AI without explicit "learn from" instructions.
"""

import ast
import json
import os
import re
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from src.constants import CODE_EXTENSIONS, SKIP_DIRS
from src.agent.knowledge import compute_repo_id

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_STRUCTURE_EXTENSIONS = CODE_EXTENSIONS | {
    ".xml", ".gradle", ".kts", ".toml", ".ini", ".yml", ".yaml", ".json",
}

_ENTRY_POINTS = {"main", "app", "index", "application", "server", "cli"}

_BOILERPLATE_PATTERNS = {"__init__", "setup", "conftest", "config", "migrations"}

# Pre-compiled Java regexes (Improvement 5)
_JAVA_CLASS_RE = re.compile(
    r"(?:public\s+)?(?:static\s+)?(?:class|interface|enum)\s+(\w+)"
)
_JAVA_METHOD_RE = re.compile(
    r"(?:public|private|protected)\s+(?:static\s+)?[\w<>\[\],\s]+\s+(\w+)\s*\("
)


# ---------------------------------------------------------------------------
# Improvement 1: Single-walk indexing
# ---------------------------------------------------------------------------

@dataclass
class _RepoIndex:
    """Result of a single os.walk() pass over the repository."""
    structure_tree: dict = field(default_factory=lambda: {"subdirs": {}, "files": []})
    code_files: list = field(default_factory=list)  # list of (rel_path_str, Path)
    has_test_py: bool = False
    has_py: bool = False
    has_java: bool = False
    total_code_files: int = 0


def _insert_into_tree(tree: dict, dir_parts: list, filename: str) -> None:
    """Insert a file into the nested structure tree."""
    current = tree
    for part in dir_parts:
        subdirs = current.setdefault("subdirs", {})
        if part not in subdirs:
            subdirs[part] = {"subdirs": {}, "files": []}
        current = subdirs[part]
    current.setdefault("files", []).append(filename)


def _walk_repo(repo: Path) -> _RepoIndex:
    """Single os.walk() pass with directory pruning. Populates structure tree and code file list."""
    idx = _RepoIndex()
    repo_str = str(repo)

    for dirpath, dirnames, filenames in os.walk(repo):
        # Prune skip directories in-place (prevents descent)
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

        rel_dir = os.path.relpath(dirpath, repo_str)
        if rel_dir == ".":
            dir_parts = []
        else:
            dir_parts = rel_dir.replace("\\", "/").split("/")

        for fname in filenames:
            fpath = Path(dirpath) / fname
            suffix = fpath.suffix

            # Structure tree: include code + config extensions
            if suffix in _STRUCTURE_EXTENSIONS:
                _insert_into_tree(idx.structure_tree, dir_parts, fname)

            # Code files: only CODE_EXTENSIONS
            if suffix in CODE_EXTENSIONS:
                rel_path = os.path.relpath(str(fpath), repo_str).replace("\\", "/")
                idx.code_files.append((rel_path, fpath))
                idx.total_code_files += 1

                if suffix == ".py":
                    idx.has_py = True
                    fname_lower = fname.lower()
                    if fname_lower.startswith("test_") or fname_lower.endswith("_test.py"):
                        idx.has_test_py = True
                elif suffix == ".java":
                    idx.has_java = True

    return idx


# ---------------------------------------------------------------------------
# Improvement 3: AST-based Python signatures
# ---------------------------------------------------------------------------

def _ast_name(node) -> str:
    """Get a simple name string from an AST node."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _ast_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    if isinstance(node, ast.Constant):
        return repr(node.value)
    if isinstance(node, ast.Subscript):
        base = _ast_name(node.value)
        sl = _ast_annotation_str(node.slice)
        return f"{base}[{sl}]"
    return ""


def _ast_annotation_str(node) -> str:
    """Convert an AST annotation node to a readable string."""
    if node is None:
        return ""
    if isinstance(node, ast.Constant):
        return repr(node.value) if isinstance(node.value, str) else str(node.value)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return _ast_name(node)
    if isinstance(node, ast.Subscript):
        return _ast_name(node)
    if isinstance(node, (ast.Tuple, ast.List)):
        return ", ".join(_ast_annotation_str(e) for e in node.elts)
    return ""


def _ast_extract_params(func_node) -> list:
    """Extract parameter list from a FunctionDef/AsyncFunctionDef."""
    params = []
    args = func_node.args
    # Positional args (skip 'self'/'cls')
    all_args = args.args
    defaults = args.defaults
    n_defaults = len(defaults)
    for i, arg in enumerate(all_args):
        if arg.arg in ("self", "cls"):
            continue
        ann = _ast_annotation_str(arg.annotation) if arg.annotation else ""
        # Check if this arg has a default
        default_idx = i - (len(all_args) - n_defaults)
        has_default = default_idx >= 0
        p = arg.arg
        if ann:
            p = f"{arg.arg}: {ann}"
        if has_default:
            p += "=..."
        params.append(p)
    # *args
    if args.vararg:
        p = f"*{args.vararg.arg}"
        ann = _ast_annotation_str(args.vararg.annotation) if args.vararg.annotation else ""
        if ann:
            p = f"*{args.vararg.arg}: {ann}"
        params.append(p)
    # **kwargs
    if args.kwarg:
        p = f"**{args.kwarg.arg}"
        ann = _ast_annotation_str(args.kwarg.annotation) if args.kwarg.annotation else ""
        if ann:
            p = f"**{args.kwarg.arg}: {ann}"
        params.append(p)
    return params


def _ast_decorator_name(node) -> str:
    """Get decorator name from an AST decorator node."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return _ast_name(node)
    if isinstance(node, ast.Call):
        return _ast_decorator_name(node.func)
    return ""


def _extract_python_signatures_ast(rel_path: str, content: str) -> list:
    """Extract Python signatures using AST. Returns list of signature dicts."""
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return _extract_python_signatures_regex_fallback(rel_path, content)

    sigs = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            bases = [_ast_name(b) for b in node.bases if _ast_name(b)]
            decorators = [_ast_decorator_name(d) for d in node.decorator_list if _ast_decorator_name(d)]
            sig = {"path": rel_path, "type": "class", "name": node.name}
            if bases:
                sig["bases"] = bases
            if decorators:
                sig["decorators"] = decorators
            sigs.append(sig)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            params = _ast_extract_params(node)
            return_type = _ast_annotation_str(node.returns) if node.returns else ""
            decorators = [_ast_decorator_name(d) for d in node.decorator_list if _ast_decorator_name(d)]
            sig_type = "function"
            if isinstance(node, ast.AsyncFunctionDef):
                sig_type = "async function"
            sig = {"path": rel_path, "type": sig_type, "name": node.name}
            if params:
                sig["params"] = params
            if return_type:
                sig["return_type"] = return_type
            if decorators:
                sig["decorators"] = decorators
            sigs.append(sig)
    return sigs


def _extract_python_signatures_regex_fallback(rel_path: str, content: str) -> list:
    """Regex fallback for Python files that fail AST parsing."""
    sigs = []
    for m in re.finditer(r"^def\s+(\w+)\s*\(", content, re.MULTILINE):
        sigs.append({"path": rel_path, "type": "function", "name": m.group(1)})
    for m in re.finditer(r"^class\s+(\w+)", content, re.MULTILINE):
        sigs.append({"path": rel_path, "type": "class", "name": m.group(1)})
    return sigs


def _extract_java_signatures_regex(rel_path: str, content: str) -> list:
    """Extract Java signatures using pre-compiled regexes."""
    sigs = []
    for m in _JAVA_CLASS_RE.finditer(content):
        sigs.append({"path": rel_path, "type": "class", "name": m.group(1)})
    for m in _JAVA_METHOD_RE.finditer(content):
        sigs.append({"path": rel_path, "type": "method", "name": m.group(1)})
    return sigs


def _extract_signatures(repo: Path, rel_path: str, content: str) -> list:
    """Extract class/function signatures from file. Dispatches by language."""
    path_lower = rel_path.lower()
    if path_lower.endswith(".java"):
        return _extract_java_signatures_regex(rel_path, content)
    elif path_lower.endswith(".py"):
        return _extract_python_signatures_ast(rel_path, content)
    return []


# ---------------------------------------------------------------------------
# Improvement 2: Smart sample ranking
# ---------------------------------------------------------------------------

def _score_file(rel_path: str, content: str, sig_count: int) -> float:
    """Score a file for sample selection. Higher = more representative."""
    score = 0.0
    stem = Path(rel_path).stem.lower()
    lines = content.count("\n") + 1
    depth = rel_path.count("/")

    # Files with many signatures (classes/functions) are informative
    if sig_count >= 3:
        score += 30
    elif sig_count >= 1:
        score += 15

    # Entry points are high-value
    if stem in _ENTRY_POINTS:
        score += 20

    # Medium-sized files are the sweet spot
    if 20 <= lines <= 300:
        score += 15
    elif lines < 5:
        score -= 5

    # Test files are useful for understanding patterns
    if "test" in stem:
        score += 10

    # Boilerplate is low-value
    if stem in _BOILERPLATE_PATTERNS:
        score -= 15

    # Deeply nested files are less representative
    if depth > 4:
        score -= 5

    return score


# ---------------------------------------------------------------------------
# Improvement 1 continued: Convention detection from index
# ---------------------------------------------------------------------------

def _detect_conventions_from_index(repo: Path, idx: _RepoIndex) -> dict:
    """Detect conventions using pre-built _RepoIndex (no extra walks)."""
    conventions = {
        "build_tool": "unknown",
        "language": "unknown",
        "test_framework": "unknown",
        "naming_style": "unknown",
    }

    # Build tool / language from known config files
    if (repo / "pom.xml").exists():
        conventions["build_tool"] = "maven"
        conventions["language"] = "java"
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

    # Python detection using index flags (no rglob)
    if (repo / "pytest.ini").exists():
        conventions["test_framework"] = "pytest"
        conventions["language"] = "python"
    elif (repo / "pyproject.toml").exists():
        try:
            toml_content = (repo / "pyproject.toml").read_text(errors="replace")
            if "pytest" in toml_content:
                conventions["test_framework"] = "pytest"
                conventions["language"] = "python"
        except Exception:
            pass

    if conventions["test_framework"] == "unknown" and idx.has_test_py:
        conventions["test_framework"] = "pytest_or_unittest"
        conventions["language"] = "python"

    if conventions["language"] == "unknown":
        if idx.has_py:
            conventions["language"] = "python"
        elif idx.has_java:
            conventions["language"] = "java"

    conventions["naming_style"] = "camelCase" if conventions["language"] == "java" else "snake_case"
    conventions["_total_code_files"] = idx.total_code_files
    return conventions


def _detect_conventions(repo: Path) -> dict:
    """Detect build tool, language, test framework, naming."""
    idx = _walk_repo(repo)
    return _detect_conventions_from_index(repo, idx)


def _build_structure_tree(repo: Path) -> dict:
    """Build directory tree (subdirs, files)."""
    idx = _walk_repo(repo)
    return idx.structure_tree


# ---------------------------------------------------------------------------
# ProjectConsciousness dataclass
# ---------------------------------------------------------------------------

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

    # --- Improvement 6: Token-budget-aware rendering ---

    def to_context_string(self, max_samples_chars: int = 25000, max_tokens: int = 0) -> str:
        """Render as context string for AI prompt.

        Args:
            max_samples_chars: Max chars for implementation samples.
            max_tokens: Approximate token budget (1 token ~ 4 chars). 0 = unlimited.
        """
        if max_tokens <= 0:
            return self._render_full(
                max_samples_chars=max_samples_chars,
                structure_depth=3,
                max_sigs=30,
            )

        # Progressive trimming to fit within budget
        char_budget = max_tokens * 4

        # Tier 1: full output
        result = self._render_full(max_samples_chars=max_samples_chars, structure_depth=3, max_sigs=30)
        if len(result) <= char_budget:
            return result

        # Tier 2: reduced samples
        for sample_chars in [15000, 8000, 3000, 0]:
            result = self._render_full(max_samples_chars=sample_chars, structure_depth=3, max_sigs=30)
            if len(result) <= char_budget:
                return result

        # Tier 3: reduced signatures
        for max_sigs in [20, 10, 5, 0]:
            result = self._render_full(max_samples_chars=0, structure_depth=3, max_sigs=max_sigs)
            if len(result) <= char_budget:
                return result

        # Tier 4: reduced structure depth
        for depth in [2, 1, 0]:
            result = self._render_full(max_samples_chars=0, structure_depth=depth, max_sigs=0)
            if len(result) <= char_budget:
                return result

        # Last resort: header only
        return f"## Project context (structure and conventions)\nLanguage/build: {self.conventions.get('language', 'unknown')}, {self.conventions.get('build_tool', 'unknown')}"

    def _render_full(self, max_samples_chars: int, structure_depth: int, max_sigs: int) -> str:
        """Render consciousness with given limits."""
        lines = ["## Project context (structure and conventions)"]
        lines.append(f"Language/build: {self.conventions.get('language', 'unknown')}, {self.conventions.get('build_tool', 'unknown')}")
        lines.append(f"Test framework: {self.conventions.get('test_framework', 'unknown')}")
        lines.append(f"Naming: {self.conventions.get('naming_style', 'unknown')}")

        if structure_depth >= 0:
            lines.append("")
            lines.append("Directory structure (key paths):")
            lines.append(_format_structure(self.structure, indent=0, max_depth=structure_depth))

        if self.signatures and max_sigs > 0:
            lines.append("")
            lines.append("Key classes/functions:")
            for sig in self.signatures[:max_sigs]:
                line = f"  {sig.get('path', '')}: {sig.get('type', '')} {sig.get('name', '')}"
                # Show params/return types from AST extraction
                params = sig.get("params")
                return_type = sig.get("return_type")
                decorators = sig.get("decorators")
                bases = sig.get("bases")
                if params is not None:
                    line = f"  {sig.get('path', '')}: {sig.get('type', '')} {sig.get('name', '')}({', '.join(params)})"
                    if return_type:
                        line += f" -> {return_type}"
                elif bases:
                    line += f"({', '.join(bases)})"
                if decorators:
                    line += f"  [{', '.join('@' + d for d in decorators)}]"
                lines.append(line)

        if self.implementation_samples and max_samples_chars > 0:
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


def _format_structure(tree: dict, indent: int = 0, max_depth: int = 3) -> str:
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


# ---------------------------------------------------------------------------
# build_consciousness — single walk + scoring + AST sigs
# ---------------------------------------------------------------------------

def build_consciousness(repo_path: str, repo_url: str = "") -> ProjectConsciousness:
    """Index the repository and build consciousness."""
    repo = Path(repo_path)
    if not repo.exists():
        return ProjectConsciousness(
            repo_id=compute_repo_id(repo_path, repo_url),
            indexed_at=time.time(),
            structure={},
            conventions={},
            implementation_samples=[],
            signatures=[],
        )

    repo_id = compute_repo_id(repo_path, repo_url)

    # Single walk (Improvement 1)
    idx = _walk_repo(repo)
    structure = idx.structure_tree
    conventions = _detect_conventions_from_index(repo, idx)

    # Read all code files, extract signatures, score for samples
    signatures: list = []
    candidates: list = []  # (score, rel_path, excerpt, metadata, sig_count)
    max_chars = 30000
    total_chars = 0

    for rel_path, fpath in idx.code_files:
        try:
            content = fpath.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue

        sigs = _extract_signatures(repo, rel_path, content)
        signatures.extend(sigs[:5])

        # Prepare sample candidate
        excerpt = content[:2500]
        if len(content) > 2500:
            excerpt += "\n... (truncated)"

        score = _score_file(rel_path, content, len(sigs))
        candidates.append((score, rel_path, excerpt, {"lines": len(content.splitlines())}))

    # Sort by score descending, take top 15 (Improvement 2)
    candidates.sort(key=lambda c: c[0], reverse=True)

    samples: list = []
    for score, rel_path, excerpt, metadata in candidates:
        if total_chars + len(excerpt) > max_chars:
            continue
        samples.append({
            "path": rel_path,
            "excerpt": excerpt,
            "metadata": metadata,
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


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

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
            from src.consciousness.opensearch import OpenSearchConsciousnessStore
            return OpenSearchConsciousnessStore(url=opensearch_url, index=opensearch_index)
        except ImportError:
            return FileConsciousnessStore(cache_dir)
    return FileConsciousnessStore(cache_dir)


# ---------------------------------------------------------------------------
# Improvement 4: Git-aware incremental rebuild
# ---------------------------------------------------------------------------

def _get_changed_files_since(repo_path: Path, since_timestamp: float) -> Optional[list]:
    """Get files changed since a timestamp using git log. Returns None if git unavailable."""
    try:
        from git import Repo as GitRepo, InvalidGitRepositoryError
    except ImportError:
        return None

    try:
        git_repo = GitRepo(str(repo_path))
    except (InvalidGitRepositoryError, Exception):
        return None

    try:
        import datetime
        since_date = datetime.datetime.fromtimestamp(since_timestamp).isoformat()
        # Get list of changed files since timestamp
        log_output = git_repo.git.log(
            f"--since={since_date}", "--name-only", "--pretty=format:"
        )
        if not log_output.strip():
            return []
        files = list(set(
            f.strip() for f in log_output.strip().split("\n") if f.strip()
        ))
        return files
    except Exception:
        return None


def _incremental_update(
    cached: "ProjectConsciousness",
    repo_path: str,
    repo_url: str,
    changed_files: list,
) -> "ProjectConsciousness":
    """Incrementally update consciousness for changed files only."""
    repo = Path(repo_path)

    # Always rebuild structure (it's cheap with single walk)
    idx = _walk_repo(repo)
    structure = idx.structure_tree
    conventions = _detect_conventions_from_index(repo, idx)

    # Build set of changed file paths for quick lookup
    changed_set = set(changed_files)

    # Keep unchanged signatures, rebuild only changed ones
    unchanged_sigs = [s for s in cached.signatures if s.get("path") not in changed_set]
    new_sigs = []
    for rel_path, fpath in idx.code_files:
        if rel_path in changed_set:
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            sigs = _extract_signatures(repo, rel_path, content)
            new_sigs.extend(sigs[:5])
    signatures = unchanged_sigs + new_sigs

    # Keep unchanged samples, rebuild changed ones, then re-score and pick top 15
    unchanged_samples = [s for s in cached.implementation_samples if s.get("path") not in changed_set]

    new_candidates = []
    for rel_path, fpath in idx.code_files:
        if rel_path in changed_set:
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            excerpt = content[:2500]
            if len(content) > 2500:
                excerpt += "\n... (truncated)"
            sigs = _extract_signatures(repo, rel_path, content)
            score = _score_file(rel_path, content, len(sigs))
            new_candidates.append((score, {
                "path": rel_path,
                "excerpt": excerpt,
                "metadata": {"lines": len(content.splitlines())},
            }))

    # Combine: unchanged samples keep implicit high score, new candidates compete
    all_candidates = [(50.0, s) for s in unchanged_samples] + new_candidates
    all_candidates.sort(key=lambda c: c[0], reverse=True)

    samples = []
    total_chars = 0
    max_chars = 30000
    for _, sample in all_candidates:
        excerpt = sample.get("excerpt", "")
        if total_chars + len(excerpt) > max_chars:
            continue
        samples.append(sample)
        total_chars += len(excerpt)
        if len(samples) >= 15:
            break

    return ProjectConsciousness(
        repo_id=cached.repo_id,
        indexed_at=time.time(),
        structure=structure,
        conventions=conventions,
        implementation_samples=samples,
        signatures=signatures[:80],
    )


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
    repo_id = compute_repo_id(repo_path, repo_url or config.get("repository", {}).get("repo_url", ""))

    if not force_rebuild:
        cached = store.load(repo_id)
        if cached:
            age_hours = (time.time() - cached.indexed_at) / 3600
            if max_age_hours <= 0 or age_hours <= max_age_hours:
                return cached

            # Stale cache — try incremental rebuild (Improvement 4)
            changed = _get_changed_files_since(Path(repo_path), cached.indexed_at)
            if changed is not None:
                if len(changed) == 0:
                    # No changes — refresh timestamp and return
                    cached_dict = cached.to_dict()
                    cached_dict["indexed_at"] = time.time()
                    refreshed = ProjectConsciousness.from_dict(cached_dict)
                    store.save(repo_id, refreshed)
                    return refreshed

                total = cached.conventions.get("_total_code_files", 0)
                if total > 0 and len(changed) / total <= 0.30:
                    consciousness = _incremental_update(cached, repo_path, repo_url, changed)
                    store.save(repo_id, consciousness)
                    return consciousness
            # Else: git unavailable or too many changes → full rebuild below

    consciousness = build_consciousness(repo_path, repo_url)
    store.save(repo_id, consciousness)
    return consciousness
