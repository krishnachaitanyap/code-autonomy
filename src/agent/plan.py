"""
Plan mode data structures and logic.

Two-phase execution:
  Phase 1 (Plan): Agent explores with read-only tools + propose_change.
                   All proposals accumulate in a ChangePlan.
  Phase 2 (Apply): Approved changes are written to disk via existing tools.
"""

import difflib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from src.agent.tools import run_write_file, run_edit_file, run_delete_file, _safe_path


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class ChangeAction(str, Enum):
    create = "create"
    modify = "modify"
    delete = "delete"


@dataclass
class ProposedChange:
    """A single proposed change to a file."""

    path: str
    action: ChangeAction
    description: str = ""
    # For create / full replacement
    new_content: Optional[str] = None
    # For modify (surgical edits)
    edits: list[dict] = field(default_factory=list)  # [{old_string, new_string}]


@dataclass
class ChangePlan:
    """Accumulates proposed changes during the planning phase."""

    changes: list[ProposedChange] = field(default_factory=list)

    # ------ helpers ------

    @property
    def is_empty(self) -> bool:
        return len(self.changes) == 0

    @property
    def files_affected(self) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for c in self.changes:
            if c.path not in seen:
                seen.add(c.path)
                result.append(c.path)
        return result

    def add_change(self, change: ProposedChange) -> None:
        """Add a change, merging edits when the same file is modified again."""
        for existing in self.changes:
            if existing.path == change.path and existing.action == ChangeAction.modify and change.action == ChangeAction.modify:
                existing.edits.extend(change.edits)
                if change.description:
                    existing.description += "; " + change.description
                return
        self.changes.append(change)

    def to_dict(self) -> list[dict]:
        result = []
        for c in self.changes:
            d = {"path": c.path, "action": c.action.value, "description": c.description}
            if c.new_content is not None:
                d["new_content"] = c.new_content
            if c.edits:
                d["edits"] = c.edits
            result.append(d)
        return result


# ---------------------------------------------------------------------------
# Diff generation (in-memory, no disk writes)
# ---------------------------------------------------------------------------

def _read_file_content(repo_root: Path, path: str) -> Optional[str]:
    """Read current file content, returning None if it doesn't exist."""
    target = _safe_path(repo_root, path)
    if not target or not target.exists() or not target.is_file():
        return None
    try:
        return target.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None


def _apply_edits_in_memory(original: str, edits: list[dict]) -> str:
    """Apply a sequence of surgical edits to content in memory."""
    content = original
    for edit in edits:
        old = edit.get("old_string", "")
        new = edit.get("new_string", "")
        if old and old in content:
            content = content.replace(old, new, 1)
    return content


def generate_diff(repo_root: Path, change: ProposedChange) -> str:
    """Generate a unified diff string for a proposed change (no disk writes).

    Handles create (diff vs empty), modify (apply edits in-memory), delete (diff to empty).
    """
    repo_root = Path(repo_root)

    if change.action == ChangeAction.create:
        old_lines: list[str] = []
        new_lines = (change.new_content or "").splitlines(keepends=True)
        from_file = "/dev/null"
        to_file = change.path

    elif change.action == ChangeAction.delete:
        original = _read_file_content(repo_root, change.path)
        old_lines = (original or "").splitlines(keepends=True)
        new_lines = []
        from_file = change.path
        to_file = "/dev/null"

    elif change.action == ChangeAction.modify:
        original = _read_file_content(repo_root, change.path) or ""
        old_lines = original.splitlines(keepends=True)
        if change.new_content is not None:
            # Full replacement
            modified = change.new_content
        else:
            modified = _apply_edits_in_memory(original, change.edits)
        new_lines = modified.splitlines(keepends=True)
        from_file = f"a/{change.path}"
        to_file = f"b/{change.path}"

    else:
        return ""

    diff = difflib.unified_diff(
        old_lines, new_lines,
        fromfile=from_file,
        tofile=to_file,
        lineterm="",
    )
    return "\n".join(diff)


# ---------------------------------------------------------------------------
# Apply plan (Phase 2)
# ---------------------------------------------------------------------------

def apply_plan(
    repo_root: Path,
    plan: ChangePlan,
    changes_tracker: Optional[set] = None,
) -> list[str]:
    """Apply all changes in a plan to disk.

    Uses the existing run_write_file/run_edit_file/run_delete_file functions.
    Returns list of affected file paths.
    """
    repo = Path(repo_root)
    tracker = changes_tracker if changes_tracker is not None else set()
    errors: list[str] = []

    for change in plan.changes:
        if change.action == ChangeAction.create:
            result = run_write_file(repo, change.path, change.new_content or "")
            if result.startswith("Error"):
                errors.append(f"{change.path}: {result}")
            else:
                tracker.add(change.path)

        elif change.action == ChangeAction.delete:
            result = run_delete_file(repo, change.path)
            if result.startswith("Error"):
                errors.append(f"{change.path}: {result}")
            else:
                tracker.add(change.path)

        elif change.action == ChangeAction.modify:
            if change.new_content is not None:
                # Full replacement
                result = run_write_file(repo, change.path, change.new_content)
                if result.startswith("Error"):
                    errors.append(f"{change.path}: {result}")
                else:
                    tracker.add(change.path)
            else:
                for edit in change.edits:
                    result = run_edit_file(
                        repo, change.path,
                        edit.get("old_string", ""),
                        edit.get("new_string", ""),
                    )
                    if result.startswith("Error"):
                        errors.append(f"{change.path}: {result}")
                    else:
                        tracker.add(change.path)

    return sorted(tracker)
