"""
One-time scaffolding tool: auto-generate a `.code-autonomy.md` repo knowledge
file from ProjectConsciousness data.

Separate from knowledge.py (which handles runtime load/persist) since this is
a CLI-invoked generation tool, not part of the agent loop.
"""

import os
from pathlib import Path
from typing import Optional

from src.consciousness.core import ProjectConsciousness, _format_structure
from src.agent.knowledge import (
    _REPO_KNOWLEDGE_DIR,
    _REPO_KNOWLEDGE_FILE,
    _REPO_KNOWLEDGE_ALT_FILE,
    _REPO_KNOWLEDGE_MAX_CHARS,
)

_BUDGET = 9500  # leave headroom below _REPO_KNOWLEDGE_MAX_CHARS (10,000)
_SKILLS_BUDGET = 5000  # SKILLS.md should be more concise


# ---------------------------------------------------------------------------
# Section generators
# ---------------------------------------------------------------------------

def _section_project_overview(conventions: dict) -> str:
    lang = conventions.get("language", "unknown")
    build = conventions.get("build_tool", "unknown")

    lines = ["## Project Overview", ""]
    if lang != "unknown":
        lines.append(f"- **Language:** {lang}")
    else:
        lines.append("- **Language:** <!-- TODO: e.g. python, java, typescript -->")
    if build != "unknown":
        lines.append(f"- **Build tool:** {build}")
    else:
        lines.append("- **Build tool:** <!-- TODO: e.g. pip, maven, gradle, npm -->")
    lines.append("- **Description:** <!-- TODO: one-line project description -->")
    return "\n".join(lines)


def _section_repository_layout(structure: dict) -> str:
    lines = ["## Repository Layout", ""]
    if not structure or (not structure.get("subdirs") and not structure.get("files")):
        lines.append("<!-- TODO: describe your directory layout -->")
        return "\n".join(lines)

    tree = _format_structure(structure, indent=0, max_depth=2)
    # Cap the tree at 1500 chars
    if len(tree) > 1500:
        tree = tree[:1500] + "\n... (trimmed)"
    lines.append("```")
    lines.append(tree)
    lines.append("```")
    return "\n".join(lines)


def _section_coding_conventions(conventions: dict) -> str:
    naming = conventions.get("naming_style", "unknown")

    lines = ["## Coding Conventions", ""]
    if naming != "unknown":
        lines.append(f"- **Naming style:** {naming}")
    else:
        lines.append("- **Naming style:** <!-- TODO: snake_case, camelCase, etc. -->")
    lines.append("- **Formatting/linting:** <!-- TODO: e.g. black, ruff, prettier, checkstyle -->")
    lines.append("- **Import ordering:** <!-- TODO: e.g. isort, stdlib-first -->")
    return "\n".join(lines)


def _section_testing(conventions: dict) -> str:
    framework = conventions.get("test_framework", "unknown")

    lines = ["## Testing", ""]
    if framework != "unknown":
        lines.append(f"- **Framework:** {framework}")
    else:
        lines.append("- **Framework:** <!-- TODO: e.g. pytest, junit5, jest -->")
    lines.append("- **Run tests:** <!-- TODO: e.g. pytest tests/, mvn test -->")
    lines.append("- **Coverage:** <!-- TODO: e.g. pytest --cov=src -->")
    return "\n".join(lines)


def _section_important_files(signatures: list, samples: list) -> str:
    lines = ["## Important Files", ""]

    # Build table from top 8 ranked samples + their signature names
    entries: list[tuple[str, str]] = []
    sig_by_path: dict[str, list[str]] = {}
    for sig in signatures:
        p = sig.get("path", "")
        n = sig.get("name", "")
        if p and n:
            sig_by_path.setdefault(p, []).append(n)

    for sample in samples[:8]:
        path = sample.get("path", "")
        if not path:
            continue
        names = sig_by_path.get(path, [])
        desc = ", ".join(names[:4]) if names else "<!-- TODO: describe -->"
        entries.append((path, desc))

    if entries:
        lines.append("| File | Key symbols / purpose |")
        lines.append("|------|----------------------|")
        for path, desc in entries:
            lines.append(f"| `{path}` | {desc} |")
    else:
        lines.append("| File | Key symbols / purpose |")
        lines.append("|------|----------------------|")
        lines.append("| <!-- TODO --> | <!-- TODO --> |")

    return "\n".join(lines)


def _section_architecture_notes() -> str:
    return "\n".join([
        "## Architecture Notes",
        "",
        "<!-- TODO: describe high-level architecture, data flow, key design decisions -->",
    ])


def _section_domain_context() -> str:
    return "\n".join([
        "## Domain Context",
        "",
        "<!-- TODO: describe the business domain, key terminology, domain rules -->",
    ])


def _section_things_to_watch() -> str:
    return "\n".join([
        "## Things to Watch",
        "",
        "<!-- TODO: gotchas, common mistakes, files that should not be modified, etc. -->",
    ])


# ---------------------------------------------------------------------------
# Trim to budget
# ---------------------------------------------------------------------------

def _trim_to_budget(content: str, max_chars: int = _BUDGET) -> str:
    """Trim content to fit within character budget.

    Strategy:
    1. Remove sections that are purely TODO placeholders (no auto-filled data).
    2. If still over budget, hard truncate with a marker.
    """
    if len(content) <= max_chars:
        return content

    # Split into sections by ## headings
    sections: list[str] = []
    current: list[str] = []
    for line in content.split("\n"):
        if line.startswith("## ") and current:
            sections.append("\n".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        sections.append("\n".join(current))

    # Identify TODO-only sections (all non-heading, non-empty lines contain <!-- TODO)
    def _is_todo_only(section: str) -> bool:
        lines = section.strip().split("\n")
        content_lines = [
            l for l in lines
            if l.strip() and not l.startswith("## ") and not l.startswith("```")
        ]
        if not content_lines:
            return True
        return all("<!-- TODO" in l for l in content_lines)

    # Remove TODO-only sections from the end first
    trimmed = list(sections)
    while len("\n\n".join(trimmed)) > max_chars and len(trimmed) > 1:
        # Find last TODO-only section
        removed = False
        for i in range(len(trimmed) - 1, 0, -1):
            if _is_todo_only(trimmed[i]):
                trimmed.pop(i)
                removed = True
                break
        if not removed:
            break

    result = "\n\n".join(trimmed)

    # Hard truncate if still over
    if len(result) > max_chars:
        result = result[:max_chars] + "\n\n[... trimmed to fit budget]\n"

    return result


# ---------------------------------------------------------------------------
# Detection + write
# ---------------------------------------------------------------------------

def detect_existing_knowledge_file(repo_path: str) -> Optional[str]:
    """Check for existing knowledge files. Returns absolute path or None."""
    root = Path(repo_path)
    if not root.is_dir():
        return None

    # Check directory first
    d = root / _REPO_KNOWLEDGE_DIR
    if d.is_dir() and any(d.glob("*.md")):
        return str(d.resolve())

    # Check .code-autonomy.md
    f = root / _REPO_KNOWLEDGE_FILE
    if f.is_file():
        return str(f.resolve())

    # Check AGENT.md
    a = root / _REPO_KNOWLEDGE_ALT_FILE
    if a.is_file():
        return str(a.resolve())

    return None


def write_knowledge_file(repo_path: str, content: str) -> str:
    """Write .code-autonomy.md to the repo root. Returns absolute path."""
    root = Path(repo_path)
    target = root / _REPO_KNOWLEDGE_FILE
    target.write_text(content, encoding="utf-8")
    return str(target.resolve())


# ---------------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------------

def generate_knowledge_markdown(consciousness: ProjectConsciousness) -> str:
    """Assemble a .code-autonomy.md from ProjectConsciousness data.

    Auto-fills what it can, leaves <!-- TODO --> markers for the rest.
    Enforces a 9,500 character budget.
    """
    conventions = consciousness.conventions or {}
    structure = consciousness.structure or {}
    signatures = consciousness.signatures or []
    samples = consciousness.implementation_samples or []

    parts = [
        "# Repo Knowledge",
        "",
        _section_project_overview(conventions),
        "",
        _section_repository_layout(structure),
        "",
        _section_coding_conventions(conventions),
        "",
        _section_testing(conventions),
        "",
        _section_important_files(signatures, samples),
        "",
        _section_architecture_notes(),
        "",
        _section_domain_context(),
        "",
        _section_things_to_watch(),
    ]

    content = "\n".join(parts)
    return _trim_to_budget(content, _BUDGET)


def generate_skills_markdown(consciousness: ProjectConsciousness) -> str:
    """Assemble a concise SKILLS.md from ProjectConsciousness data.

    Focused on actionable project context for agent prompts.
    Enforces a 5,000 character budget (more concise than .code-autonomy.md).
    """
    conventions = consciousness.conventions or {}
    structure = consciousness.structure or {}
    signatures = consciousness.signatures or []
    samples = consciousness.implementation_samples or []

    lang = conventions.get("language", "unknown")
    build = conventions.get("build_tool", "unknown")
    framework = conventions.get("test_framework", "unknown")

    # Compact tech stack summary instead of separate sections
    tech_lines = ["## Tech Stack", ""]
    tech_items = []
    if lang != "unknown":
        tech_items.append(f"**Language:** {lang}")
    if build != "unknown":
        tech_items.append(f"**Build tool:** {build}")
    if framework != "unknown":
        tech_items.append(f"**Test framework:** {framework}")
    if tech_items:
        tech_lines.append(" | ".join(tech_items))
    else:
        tech_lines.append("Not detected")
    tech_stack = "\n".join(tech_lines)

    parts = [
        "# SKILLS.md",
        "",
        _section_project_overview(conventions),
        "",
        tech_stack,
        "",
        _section_repository_layout(structure),
        "",
        _section_important_files(signatures, samples),
        "",
        _section_coding_conventions(conventions),
        "",
        _section_testing(conventions),
    ]

    content = "\n".join(parts)
    return _trim_to_budget(content, _SKILLS_BUDGET)
