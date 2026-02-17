"""
Python call graph extraction via AST.
"""

import ast
from pathlib import Path
from typing import Optional

from src.constants import CODE_EXTENSIONS, SKIP_DIRS


def extract_python_calls(
    repo_path: str,
    file_asts: "dict[str, ast.Module] | None" = None,
) -> dict[str, set[str]]:
    """
    Build call graph: node -> set of callees.
    Node format: "path/to/file.py::function_name" or "path/to/file.py::ClassName.method_name"

    Args:
        repo_path: Repository root path.
        file_asts: Optional pre-parsed AST trees ``{rel_path: ast.Module}``.
            If provided, iterates cached trees instead of ``rglob`` + ``read_text`` + ``ast.parse``.
    """
    repo = Path(repo_path)
    graph: dict[str, set[str]] = {}
    nodes: set[str] = set()

    if file_asts is not None:
        items = file_asts.items()
    else:
        items = None

    def _process_visitor(visitor: "_PythonCallVisitor") -> None:
        for node in visitor.defined:
            nodes.add(node)
            if node not in graph:
                graph[node] = set()
        for caller, callee in visitor.calls:
            if caller not in graph:
                graph[caller] = set()
            graph[caller].add(callee)
            nodes.add(callee)

    if items is not None:
        for rel, tree in items:
            visitor = _PythonCallVisitor(rel)
            visitor.visit(tree)
            _process_visitor(visitor)
    else:
        for f in repo.rglob("*.py"):
            if not f.is_file():
                continue
            if any(p in f.relative_to(repo).parts for p in SKIP_DIRS):
                continue
            rel = str(f.relative_to(repo)).replace("\\", "/")
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(content)
            except (SyntaxError, Exception):
                continue

            visitor = _PythonCallVisitor(rel)
            visitor.visit(tree)
            _process_visitor(visitor)

    return graph


class _PythonCallVisitor(ast.NodeVisitor):
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.defined: list[str] = []
        self.calls: list[tuple[str, str]] = []
        self._current_func: Optional[str] = None
        self._current_class: Optional[str] = None

    def _node_id(self, name: str) -> str:
        if self._current_class:
            return f"{self.file_path}::{self._current_class}.{name}"
        return f"{self.file_path}::{name}"

    def _callee_id(self, name: str) -> str:
        return f"{self.file_path}::{name}"

    def visit_FunctionDef(self, node: ast.FunctionDef):
        old_func = self._current_func
        old_class = self._current_class
        self._current_func = node.name
        self.defined.append(self._node_id(node.name))
        self.generic_visit(node)
        self._current_func = old_func
        self._current_class = old_class

    def visit_ClassDef(self, node: ast.ClassDef):
        old_class = self._current_class
        self._current_class = node.name
        self.defined.append(self._node_id(node.name))
        self.generic_visit(node)
        self._current_class = old_class

    def visit_Call(self, node: ast.Call):
        if self._current_func is None:
            self.generic_visit(node)
            return
        caller = self._node_id(self._current_func)
        if isinstance(node.func, ast.Name):
            callee = self._callee_id(node.func.id)
            self.calls.append((caller, callee))
        elif isinstance(node.func, ast.Attribute):
            callee = self._callee_id(node.func.attr)
            self.calls.append((caller, callee))
        self.generic_visit(node)
