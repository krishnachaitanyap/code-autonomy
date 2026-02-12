"""
Git Context Controller (GCC) — structured versioned memory for long-horizon tasks.

Inspired by the GCC research framework (arxiv 2508.00031), this provides Git-like
memory primitives (commit, branch, merge, context) that give agents milestone
checkpointing, exploratory branching, and multi-granularity context retrieval.

GCC is opt-in (``gcc_enabled = false`` by default) and complements the existing
WorkingMemory / KnowledgeEntry system without replacing it.

State is persisted as a single JSON file per repository at
``~/.code-autonomy/gcc/{repo_id}/state.json``.
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structure
# ---------------------------------------------------------------------------

@dataclass
class GCCState:
    """Serialisable state for one repository's GCC memory."""

    repo_id: str = ""
    current_branch: str = "main"
    commit_counter: int = 0
    main_context: str = ""                       # synthesized from milestones + recent commits
    commits: list[dict] = field(default_factory=list)        # commit log (capped)
    branches: dict[str, dict] = field(default_factory=dict)  # name -> branch data
    created_at: str = ""
    updated_at: str = ""


# ---------------------------------------------------------------------------
# GCCController
# ---------------------------------------------------------------------------

class GCCController:
    """Manages Git-like structured memory for the agent loop.

    Provides four operations:
    - **commit** — checkpoint current progress with a summary
    - **branch** — create an exploratory reasoning branch
    - **merge** — merge a branch back into main
    - **context** — retrieve stored context at various granularities

    State is persisted to ``~/.code-autonomy/gcc/{repo_id}/state.json``.
    """

    _MAX_COMMITS = 50
    _MAX_BRANCHES = 10
    _MAX_CONTEXT_CHARS = 8000

    def __init__(self, repo_id: str, storage_dir: str = "") -> None:
        self._repo_id = repo_id
        if storage_dir:
            self._base_dir = Path(os.path.expanduser(storage_dir))
        else:
            self._base_dir = Path.home() / ".code-autonomy" / "gcc"
        self._dir = self._base_dir / repo_id
        self._state_path = self._dir / "state.json"
        self._state = self._load_or_create()

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def commit(
        self,
        summary: str,
        working_memory: Optional[dict] = None,
        milestone: str = "",
    ) -> str:
        """Checkpoint current progress.

        Args:
            summary: Description of what was accomplished.
            working_memory: Optional dict snapshot of WorkingMemory notes.
            milestone: Optional milestone label (e.g. "tests passing").

        Returns:
            Confirmation message with the commit id.
        """
        self._state.commit_counter += 1
        commit_id = f"c{self._state.commit_counter:04d}"
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")

        entry: dict = {
            "commit_id": commit_id,
            "timestamp": now,
            "branch": self._state.current_branch,
            "summary": summary,
            "milestone": milestone,
            "working_memory_snapshot": working_memory or {},
        }
        self._state.commits.append(entry)

        # Cap commit history
        if len(self._state.commits) > self._MAX_COMMITS:
            self._state.commits = self._state.commits[-self._MAX_COMMITS:]

        # Rebuild main_context from milestones + recent commits
        self._rebuild_main_context()
        self.save()

        parts = [f"Committed {commit_id}: {summary}"]
        if milestone:
            parts.append(f" (milestone: {milestone})")
        return "".join(parts)

    def branch(self, name: str, purpose: str) -> str:
        """Create a new reasoning branch.

        Args:
            name: Branch name (alphanumeric + hyphens).
            purpose: Why this branch is being created.

        Returns:
            Confirmation or error message.
        """
        if name in self._state.branches:
            return f"Error: Branch '{name}' already exists."

        active_count = sum(
            1 for b in self._state.branches.values() if not b.get("merged", False)
        )
        if active_count >= self._MAX_BRANCHES:
            return f"Error: Maximum {self._MAX_BRANCHES} active branches reached. Merge or delete existing branches first."

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._state.branches[name] = {
            "name": name,
            "purpose": purpose,
            "created_at": now,
            "parent_branch": self._state.current_branch,
            "context_snapshot": self._state.main_context,
            "notes": "",
            "merged": False,
            "merged_at": "",
        }
        self._state.current_branch = name
        self.save()
        return f"Created and switched to branch '{name}' (purpose: {purpose})"

    def merge(self, branch_name: str, working_memory: Optional[dict] = None) -> str:
        """Merge a reasoning branch back into main.

        Args:
            branch_name: Name of the branch to merge.
            working_memory: Optional working memory snapshot to include in merge commit.

        Returns:
            Confirmation or error message.
        """
        if branch_name not in self._state.branches:
            return f"Error: Branch '{branch_name}' does not exist."

        branch_data = self._state.branches[branch_name]
        if branch_data.get("merged", False):
            return f"Error: Branch '{branch_name}' has already been merged."

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        branch_data["merged"] = True
        branch_data["merged_at"] = now

        # Switch back to parent branch (or main)
        parent = branch_data.get("parent_branch", "main")
        self._state.current_branch = parent

        # Auto-commit the merge
        self._state.commit_counter += 1
        commit_id = f"c{self._state.commit_counter:04d}"
        merge_summary = f"Merge branch '{branch_name}': {branch_data.get('purpose', '')}"
        notes = branch_data.get("notes", "")
        if notes:
            merge_summary += f" | Notes: {notes}"

        self._state.commits.append({
            "commit_id": commit_id,
            "timestamp": now,
            "branch": parent,
            "summary": merge_summary,
            "milestone": f"merged:{branch_name}",
            "working_memory_snapshot": working_memory or {},
        })

        if len(self._state.commits) > self._MAX_COMMITS:
            self._state.commits = self._state.commits[-self._MAX_COMMITS:]

        self._rebuild_main_context()
        self.save()
        return f"Merged branch '{branch_name}' into '{parent}' ({commit_id})"

    def context(self, scope: str = "status", branch: str = "") -> str:
        """Retrieve stored context at various granularities.

        Args:
            scope: One of 'status', 'main', 'commits', 'branch', 'all'.
            branch: Branch name (required for scope='branch').

        Returns:
            Formatted context string.
        """
        if scope == "status":
            return self._context_status()
        elif scope == "main":
            return self._state.main_context or "(no context accumulated yet)"
        elif scope == "commits":
            return self._context_commits()
        elif scope == "branch":
            return self._context_branch(branch)
        elif scope == "all":
            parts = [
                self._context_status(),
                "",
                "--- Main Context ---",
                self._state.main_context or "(empty)",
                "",
                "--- Commit Log ---",
                self._context_commits(),
            ]
            return "\n".join(parts)
        else:
            return f"Error: Unknown scope '{scope}'. Use: status, main, commits, branch, all."

    # ------------------------------------------------------------------
    # System prompt injection
    # ------------------------------------------------------------------

    def to_message_block(self) -> str:
        """Format GCC state for injection into the system prompt.

        Analogous to ``WorkingMemory.to_message_block()``.
        Returns ``""`` if no commits or branches exist yet.
        """
        if not self._state.commits and not self._state.branches:
            return ""

        parts: list[str] = []
        parts.append(f"Branch: {self._state.current_branch}")
        parts.append(f"Commits: {self._state.commit_counter}")

        # Recent milestones
        milestones = [
            c for c in self._state.commits
            if c.get("milestone") and not c["milestone"].startswith("merged:")
        ]
        if milestones:
            parts.append("Milestones:")
            for m in milestones[-5:]:
                parts.append(f"  - [{m['commit_id']}] {m['milestone']}: {m['summary'][:60]}")

        # Last 5 commits
        recent = self._state.commits[-5:]
        if recent:
            parts.append("Recent:")
            for c in recent:
                parts.append(f"  - [{c['commit_id']}] {c['summary'][:80]}")

        # Active branches
        active_branches = [
            b for b in self._state.branches.values() if not b.get("merged", False)
        ]
        if active_branches:
            parts.append("Active branches:")
            for b in active_branches:
                parts.append(f"  - {b['name']}: {b['purpose'][:60]}")

        inner = "\n".join(parts)

        # Cap size
        if len(inner) > self._MAX_CONTEXT_CHARS:
            inner = inner[:self._MAX_CONTEXT_CHARS] + "\n... (truncated)"

        return f"\n<gcc_context>\n{inner}\n</gcc_context>\n"

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        """Persist current state to disk."""
        self._state.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._dir.mkdir(parents=True, exist_ok=True)
        try:
            data = {
                "repo_id": self._state.repo_id,
                "current_branch": self._state.current_branch,
                "commit_counter": self._state.commit_counter,
                "main_context": self._state.main_context,
                "commits": self._state.commits,
                "branches": self._state.branches,
                "created_at": self._state.created_at,
                "updated_at": self._state.updated_at,
            }
            self._state_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("Failed to save GCC state: %s", exc)

    def _load_or_create(self) -> GCCState:
        """Load existing state from disk or create a fresh one."""
        if self._state_path.exists():
            try:
                data = json.loads(self._state_path.read_text(encoding="utf-8"))
                return GCCState(
                    repo_id=data.get("repo_id", self._repo_id),
                    current_branch=data.get("current_branch", "main"),
                    commit_counter=data.get("commit_counter", 0),
                    main_context=data.get("main_context", ""),
                    commits=data.get("commits", []),
                    branches=data.get("branches", {}),
                    created_at=data.get("created_at", ""),
                    updated_at=data.get("updated_at", ""),
                )
            except Exception as exc:
                logger.warning(
                    "Corrupt GCC state at %s, starting fresh: %s",
                    self._state_path, exc,
                )

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        return GCCState(
            repo_id=self._repo_id,
            created_at=now,
            updated_at=now,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _rebuild_main_context(self) -> None:
        """Rebuild main_context from milestones + recent commit summaries."""
        parts: list[str] = []

        # Milestones first
        milestones = [
            c for c in self._state.commits
            if c.get("milestone") and not c["milestone"].startswith("merged:")
        ]
        if milestones:
            parts.append("Key milestones:")
            for m in milestones[-10:]:
                parts.append(f"  - {m['milestone']}: {m['summary'][:80]}")

        # Then recent commit summaries
        recent = self._state.commits[-10:]
        if recent:
            parts.append("Recent progress:")
            for c in recent:
                parts.append(f"  - [{c['commit_id']}] {c['summary'][:80]}")

        self._state.main_context = "\n".join(parts)

    def _context_status(self) -> str:
        """Short status summary."""
        active_branches = sum(
            1 for b in self._state.branches.values() if not b.get("merged", False)
        )
        return (
            f"Branch: {self._state.current_branch} | "
            f"Commits: {self._state.commit_counter} | "
            f"Active branches: {active_branches}"
        )

    def _context_commits(self) -> str:
        """Format all commits."""
        if not self._state.commits:
            return "(no commits yet)"
        lines: list[str] = []
        for c in self._state.commits:
            milestone_tag = f" [milestone: {c['milestone']}]" if c.get("milestone") else ""
            lines.append(
                f"[{c['commit_id']}] ({c.get('branch', 'main')}) {c['summary']}{milestone_tag}"
            )
        return "\n".join(lines)

    def _context_branch(self, branch_name: str) -> str:
        """Format branch details."""
        if not branch_name:
            return "Error: branch parameter is required for scope='branch'."
        if branch_name not in self._state.branches:
            return f"Error: Branch '{branch_name}' not found."
        b = self._state.branches[branch_name]
        lines = [
            f"Branch: {b['name']}",
            f"Purpose: {b['purpose']}",
            f"Created: {b['created_at']}",
            f"Parent: {b.get('parent_branch', 'main')}",
            f"Merged: {b.get('merged', False)}",
        ]
        if b.get("merged_at"):
            lines.append(f"Merged at: {b['merged_at']}")
        if b.get("notes"):
            lines.append(f"Notes: {b['notes']}")
        if b.get("context_snapshot"):
            lines.append(f"Context snapshot:\n{b['context_snapshot'][:500]}")

        # Show commits on this branch
        branch_commits = [c for c in self._state.commits if c.get("branch") == branch_name]
        if branch_commits:
            lines.append(f"Commits on branch ({len(branch_commits)}):")
            for c in branch_commits:
                lines.append(f"  [{c['commit_id']}] {c['summary'][:80]}")

        return "\n".join(lines)
