"""
Call graph construction and traversal.
"""

from pathlib import Path
from typing import Optional

from src.context.call_graph.python_extractor import extract_python_calls


def build_call_graph(
    repo_path: str,
    file_asts: "dict[str, object] | None" = None,
) -> dict[str, set[str]]:
    """Build combined call graph from Python and optionally Java.

    Args:
        repo_path: Repository root path.
        file_asts: Optional pre-parsed AST trees passed through to
            ``extract_python_calls``.
    """
    graph: dict[str, set[str]] = {}

    py_graph = extract_python_calls(repo_path, file_asts=file_asts)
    for k, v in py_graph.items():
        graph[k] = graph.get(k, set()) | v

    try:
        from src.context.call_graph.java_extractor import extract_java_calls
        java_graph = extract_java_calls(repo_path)
        for k, v in java_graph.items():
            graph[k] = graph.get(k, set()) | v
    except ImportError:
        pass

    return graph


def get_related_paths(
    graph: dict[str, set[str]],
    seed_paths: list[str],
    depth: int = 2,
) -> set[str]:
    """Get file paths reachable from seeds within N hops."""
    def path_from_node(node: str) -> str:
        if "::" in node:
            return node.split("::")[0]
        return node

    seed_files = {p.strip() for p in seed_paths if p.strip()}
    current = {n for n in graph if path_from_node(n) in seed_files}
    seen_paths = seed_files | {path_from_node(n) for n in current}

    for _ in range(max(0, depth - 1)):
        next_nodes = set()
        for node in current:
            for callee in graph.get(node, set()):
                next_nodes.add(callee)
                seen_paths.add(path_from_node(callee))
        current = next_nodes

    return seen_paths
