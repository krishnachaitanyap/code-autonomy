"""
PropertyIndex: pre-computed map from property/field names to file locations.

Walks ASTs (Python via stdlib ast, Java via javalang) to extract property
accesses, config keys, field declarations, and constants.  The resulting
index enables O(1) lookup of every file that references a given name,
powering the ``find_all_usages`` tool.
"""

import ast
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from src.constants import SKIP_DIRS

logger = logging.getLogger(__name__)


@dataclass
class PropertyIndex:
    """Maps property/field names to (file, line, snippet) tuples."""

    index: dict[str, list[tuple[str, int, str]]] = field(default_factory=dict)

    def add(self, name: str, file_path: str, line: int, snippet: str) -> None:
        self.index.setdefault(name, []).append((file_path, line, snippet))

    def lookup(self, name: str) -> list[tuple[str, int, str]]:
        """Exact match lookup."""
        return self.index.get(name, [])

    def lookup_fuzzy(self, pattern: str) -> dict[str, list[tuple[str, int, str]]]:
        """Substring or regex match across all keys."""
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error:
            regex = re.compile(re.escape(pattern), re.IGNORECASE)
        results: dict[str, list[tuple[str, int, str]]] = {}
        for key, entries in self.index.items():
            if regex.search(key):
                results[key] = entries
        return results

    def to_dict(self) -> dict:
        """Serialize for JSON storage."""
        return {
            name: [[fp, line, snippet] for fp, line, snippet in entries]
            for name, entries in self.index.items()
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PropertyIndex":
        """Deserialize from JSON."""
        pi = cls()
        for name, entries in data.items():
            pi.index[name] = [(e[0], e[1], e[2]) for e in entries]
        return pi


# ---------------------------------------------------------------------------
# Python extractor
# ---------------------------------------------------------------------------

def _extract_python_properties(
    file_path: str,
    source: str,
    tree: ast.Module,
) -> list[tuple[str, int, str]]:
    """Extract property names from a Python AST.

    Returns list of (property_name, line_number, snippet).
    """
    results: list[tuple[str, int, str]] = []
    lines = source.splitlines()

    def _snippet(lineno: int) -> str:
        if 1 <= lineno <= len(lines):
            return lines[lineno - 1].strip()
        return ""

    for node in ast.walk(tree):
        # self.timeout, config.timeout → "timeout"
        if isinstance(node, ast.Attribute):
            results.append((node.attr, node.lineno, _snippet(node.lineno)))

        # config["timeout"] → "timeout"
        elif isinstance(node, ast.Subscript):
            if isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
                results.append((node.slice.value, node.lineno, _snippet(node.lineno)))

        # cfg.get("timeout"), get_int("jira", "timeout") → "timeout", "jira"
        elif isinstance(node, ast.Call):
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    results.append((arg.value, node.lineno, _snippet(node.lineno)))

        # TIMEOUT_MS = 30000 (top-level assignment)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    results.append((target.id, node.lineno, _snippet(node.lineno)))

        # timeout: int = 30 (annotated assignment)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                results.append((node.target.id, node.lineno, _snippet(node.lineno)))

    return results


# ---------------------------------------------------------------------------
# Java extractor
# ---------------------------------------------------------------------------

def _extract_java_properties(
    file_path: str,
    source: str,
) -> list[tuple[str, int, str]]:
    """Extract property names from Java source via javalang.

    Returns list of (property_name, line_number, snippet).
    """
    try:
        import javalang
    except ImportError:
        return []

    try:
        tree = javalang.parse.parse(source)
    except Exception:
        return []

    results: list[tuple[str, int, str]] = []
    lines = source.splitlines()

    def _snippet(lineno: int) -> str:
        if 1 <= lineno <= len(lines):
            return lines[lineno - 1].strip()
        return ""

    for path, node in tree:
        # Field declarations: private int timeout = 30
        if isinstance(node, javalang.tree.FieldDeclaration):
            lineno = node.position.line if node.position else 0
            for decl in node.declarators:
                if decl.name:
                    results.append((decl.name, lineno, _snippet(lineno)))

        # Member references: this.timeout, config.timeout
        elif isinstance(node, javalang.tree.MemberReference):
            lineno = node.position.line if node.position else 0
            if node.member:
                results.append((node.member, lineno, _snippet(lineno)))

        # Method invocations with string literal arg: getProperty("timeout")
        elif isinstance(node, javalang.tree.MethodInvocation):
            lineno = node.position.line if node.position else 0
            if node.arguments:
                for arg in node.arguments:
                    if isinstance(arg, javalang.tree.Literal) and arg.value:
                        val = arg.value
                        if val.startswith('"') and val.endswith('"'):
                            results.append((val[1:-1], lineno, _snippet(lineno)))

        # Annotations: @Value("${app.timeout}")
        elif isinstance(node, javalang.tree.Annotation):
            lineno = node.position.line if node.position else 0
            if isinstance(node.element, javalang.tree.Literal) and node.element.value:
                val = node.element.value
                if val.startswith('"') and val.endswith('"'):
                    inner = val[1:-1]
                    # Extract from ${app.timeout} pattern
                    m = re.search(r"\$\{(.+?)\}", inner)
                    if m:
                        results.append((m.group(1), lineno, _snippet(lineno)))
                    else:
                        results.append((inner, lineno, _snippet(lineno)))

    return results


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def build_property_index(
    repo_path: str,
    file_contents: dict[str, str],
    file_asts: dict[str, ast.Module],
) -> PropertyIndex:
    """Build a PropertyIndex from pre-parsed files.

    Args:
        repo_path: Repository root path.
        file_contents: {rel_path: source_text} for all files.
        file_asts: {rel_path: ast.Module} for successfully parsed Python files.
    """
    pi = PropertyIndex()

    # Python files (use pre-parsed ASTs)
    for rel_path, tree in file_asts.items():
        source = file_contents.get(rel_path, "")
        for name, line, snippet in _extract_python_properties(rel_path, source, tree):
            pi.add(name, rel_path, line, snippet)

    # Java files (scan repo for .java files)
    repo = Path(repo_path)
    for java_file in repo.rglob("*.java"):
        if not java_file.is_file():
            continue
        if any(p in java_file.relative_to(repo).parts for p in SKIP_DIRS):
            continue
        rel = str(java_file.relative_to(repo)).replace("\\", "/")
        try:
            source = java_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for name, line, snippet in _extract_java_properties(rel, source):
            pi.add(name, rel, line, snippet)

    logger.debug("PropertyIndex built: %d unique names", len(pi.index))
    return pi
