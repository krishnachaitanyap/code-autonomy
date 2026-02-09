"""
Java call graph extraction via javalang (optional).
"""

from pathlib import Path
from typing import Optional

from src.constants import SKIP_DIRS


def extract_java_calls(repo_path: str) -> dict[str, set[str]]:
    """
    Build call graph for Java files.
    Node format: "path/to/File.java::methodName"
    """
    try:
        import javalang
    except ImportError:
        return {}

    repo = Path(repo_path)
    graph: dict[str, set[str]] = {}

    for f in repo.rglob("*.java"):
        if not f.is_file():
            continue
        if any(p in f.relative_to(repo).parts for p in SKIP_DIRS):
            continue
        rel = str(f.relative_to(repo)).replace("\\", "/")
        try:
            content = f.read_text(encoding="utf-8", errors="replace")
            tree = javalang.parse.parse(content)
        except (javalang.parser.JavaSyntaxError, Exception):
            continue

        for path, node in tree.filter(javalang.tree.MethodDeclaration):
            method_name = node.name
            node_id = f"{rel}::{method_name}"
            if node_id not in graph:
                graph[node_id] = set()

            for _, inv in node.filter(javalang.tree.MethodInvocation):
                if inv.member:
                    callee = f"{rel}::{inv.member}"
                    graph[node_id].add(callee)

    return graph
