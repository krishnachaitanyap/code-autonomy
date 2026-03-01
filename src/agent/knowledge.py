"""
Agent knowledge system — persistent memory across runs.

Two layers:
1. **WorkingMemory** — in-process dict surviving context compression (within a run).
2. **KnowledgeEntry** — persistent record per repo (across runs), stored in
   local JSON files or AWS OpenSearch.

Backends:
- FileKnowledgeStore  — default, writes ``~/.code-autonomy/knowledge/{hash}.json``
- AWSOpenSearchKnowledgeStore — uses boto3 SigV4 auth against AWS-managed OpenSearch
"""

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_MAX_CHANGE_HISTORY = 20
_MAX_RUN_OUTCOMES = 50
_MAX_ERROR_FIX_PATTERNS = 100

# Repo knowledge file conventions
_REPO_KNOWLEDGE_DIR = ".code-autonomy"
_REPO_KNOWLEDGE_FILE = ".code-autonomy.md"
_REPO_KNOWLEDGE_ALT_FILE = "AGENT.md"
_REPO_KNOWLEDGE_MAX_CHARS = 10_000


# ===================================================================
# 1a. WorkingMemory
# ===================================================================

class WorkingMemory:
    """In-process key→content note store that survives context compression."""

    def __init__(self) -> None:
        self._notes: dict[str, str] = {}

    def update(self, key: str, content: str) -> str:
        """Write or overwrite a note. Returns confirmation string."""
        self._notes[key] = content
        return f"Memory updated: '{key}' ({len(content)} chars)"

    def read_all(self) -> str:
        """Render all notes as Markdown."""
        if not self._notes:
            return "(no notes in working memory)"
        lines: list[str] = ["## Working Memory"]
        for k, v in self._notes.items():
            lines.append(f"### {k}")
            lines.append(v)
            lines.append("")
        return "\n".join(lines)

    def to_message_block(self) -> str:
        """Format for injection into the system prompt."""
        if not self._notes:
            return ""
        inner = self.read_all()
        return f"\n<working_memory>\n{inner}\n</working_memory>\n"

    def to_dict(self) -> dict[str, str]:
        """Export for persistence."""
        return dict(self._notes)

    def is_empty(self) -> bool:
        return len(self._notes) == 0


# ===================================================================
# 1b. KnowledgeEntry
# ===================================================================

@dataclass
class KnowledgeEntry:
    """Persistent knowledge record for a single repository."""

    repo_id: str = ""
    repo_url: str = ""
    updated_at: str = ""
    project_overview: str = ""
    key_patterns: str = ""
    file_notes: str = ""
    change_history: list[dict[str, Any]] = field(default_factory=list)
    notes: dict[str, str] = field(default_factory=dict)
    # --- Feedback loop fields ---
    run_outcomes: list[dict[str, Any]] = field(default_factory=list)
    error_fix_patterns: list[dict[str, Any]] = field(default_factory=list)

    def to_context_string(self) -> str:
        """Render as context block for the agent's initial prompt."""
        parts: list[str] = ["## Prior Knowledge from previous runs"]

        if self.project_overview:
            parts.append(f"### Project Overview\n{self.project_overview}")
        if self.key_patterns:
            parts.append(f"### Key Patterns\n{self.key_patterns}")
        if self.file_notes:
            parts.append(f"### File Notes\n{self.file_notes}")
        if self.notes:
            for k, v in self.notes.items():
                if k not in ("project_overview", "key_patterns", "file_notes"):
                    parts.append(f"### {k}\n{v}")
        if self.change_history:
            parts.append("### Recent Changes")
            for ch in self.change_history[-5:]:
                parts.append(f"- {ch.get('date', '?')}: {ch.get('summary', '?')}")

        # Include learned error→fix patterns (top 5 by success_count)
        if self.error_fix_patterns:
            top_patterns = sorted(
                self.error_fix_patterns, key=lambda p: p.get("success_count", 0), reverse=True
            )[:5]
            parts.append("### Learned Error→Fix Patterns")
            for pat in top_patterns:
                sig = pat.get("error_signature", "?")
                fix = pat.get("fix_description", "?")
                count = pat.get("success_count", 0)
                parts.append(f"- Error: `{sig}` → Fix: {fix} (worked {count}x)")

        # Include recent run success rate
        if self.run_outcomes:
            recent = self.run_outcomes[-10:]
            successes = sum(1 for r in recent if r.get("success"))
            parts.append(f"### Run History: {successes}/{len(recent)} recent runs succeeded")

        # Only return if there's actual content beyond the header
        if len(parts) <= 1:
            return ""
        return "\n\n".join(parts)

    def record_outcome(
        self,
        *,
        success: bool,
        summary: str = "",
        files_changed: Optional[list[str]] = None,
        tools_used: Optional[dict[str, int]] = None,
        error_type: str = "",
        error_signature: str = "",
        fix_description: str = "",
    ) -> None:
        """Record the outcome of an agent run for learning."""
        outcome = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "success": success,
            "summary": summary[:500],
            "files_changed": (files_changed or [])[:20],
            "tools_used": tools_used or {},
            "error_type": error_type,
        }
        self.run_outcomes.append(outcome)
        if len(self.run_outcomes) > _MAX_RUN_OUTCOMES:
            self.run_outcomes = self.run_outcomes[-_MAX_RUN_OUTCOMES:]

        # Learn error→fix pattern from successful recovery
        if success and error_signature and fix_description:
            self._record_error_fix(error_signature, fix_description)

        self.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def record_error_fix(
        self,
        error_signature: str,
        fix_description: str,
    ) -> None:
        """Record a successful error→fix pattern for future reference."""
        self._record_error_fix(error_signature, fix_description)
        self.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def _record_error_fix(self, error_signature: str, fix_description: str) -> None:
        """Internal: upsert an error→fix pattern."""
        # Normalize signature (first 200 chars, stripped)
        sig = error_signature.strip()[:200]
        if not sig:
            return

        # Check if a similar pattern already exists (exact match on signature)
        for pat in self.error_fix_patterns:
            if pat.get("error_signature") == sig:
                pat["success_count"] = pat.get("success_count", 0) + 1
                pat["fix_description"] = fix_description  # update with latest fix
                pat["last_used"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
                return

        # New pattern
        self.error_fix_patterns.append({
            "error_signature": sig,
            "fix_description": fix_description[:500],
            "success_count": 1,
            "last_used": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })
        if len(self.error_fix_patterns) > _MAX_ERROR_FIX_PATTERNS:
            # Evict lowest success_count patterns
            self.error_fix_patterns.sort(key=lambda p: p.get("success_count", 0), reverse=True)
            self.error_fix_patterns = self.error_fix_patterns[:_MAX_ERROR_FIX_PATTERNS]

    def get_fix_suggestions(self, error_text: str) -> list[dict[str, Any]]:
        """Return error→fix patterns whose signature appears in the error text."""
        if not self.error_fix_patterns or not error_text:
            return []
        suggestions = []
        error_lower = error_text.lower()
        for pat in self.error_fix_patterns:
            sig = pat.get("error_signature", "")
            if sig and sig.lower() in error_lower:
                suggestions.append(pat)
        # Sort by success_count descending
        suggestions.sort(key=lambda p: p.get("success_count", 0), reverse=True)
        return suggestions[:5]

    def merge_working_memory(
        self,
        working: WorkingMemory,
        summary: str = "",
        files_changed: Optional[list[str]] = None,
    ) -> None:
        """Merge working memory notes into this persistent entry."""
        wm_dict = working.to_dict()

        # Promote well-known keys to structured fields
        if "project_overview" in wm_dict:
            self.project_overview = wm_dict.pop("project_overview")
        if "key_patterns" in wm_dict:
            self.key_patterns = wm_dict.pop("key_patterns")
        if "file_notes" in wm_dict:
            self.file_notes = wm_dict.pop("file_notes")

        # Remaining notes go into the general notes dict
        for k, v in wm_dict.items():
            self.notes[k] = v

        # Record change in history (capped)
        if summary or files_changed:
            self.change_history.append({
                "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "summary": summary,
                "files_changed": files_changed or [],
            })
            if len(self.change_history) > _MAX_CHANGE_HISTORY:
                self.change_history = self.change_history[-_MAX_CHANGE_HISTORY:]

        self.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo_id": self.repo_id,
            "repo_url": self.repo_url,
            "updated_at": self.updated_at,
            "project_overview": self.project_overview,
            "key_patterns": self.key_patterns,
            "file_notes": self.file_notes,
            "change_history": self.change_history,
            "notes": self.notes,
            "run_outcomes": self.run_outcomes,
            "error_fix_patterns": self.error_fix_patterns,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KnowledgeEntry":
        return cls(
            repo_id=data.get("repo_id", ""),
            repo_url=data.get("repo_url", ""),
            updated_at=data.get("updated_at", ""),
            project_overview=data.get("project_overview", ""),
            key_patterns=data.get("key_patterns", ""),
            file_notes=data.get("file_notes", ""),
            change_history=data.get("change_history", []),
            notes=data.get("notes", {}),
            run_outcomes=data.get("run_outcomes", []),
            error_fix_patterns=data.get("error_fix_patterns", []),
        )


# ===================================================================
# 1c. FileKnowledgeStore
# ===================================================================

class FileKnowledgeStore:
    """Stores knowledge as JSON files in ``~/.code-autonomy/knowledge/``."""

    def __init__(self, storage_dir: str = "") -> None:
        if storage_dir:
            self._dir = Path(os.path.expanduser(storage_dir))
        else:
            self._dir = Path.home() / ".code-autonomy" / "knowledge"

    def save(self, entry: KnowledgeEntry) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"{entry.repo_id}.json"
        path.write_text(json.dumps(entry.to_dict(), indent=2), encoding="utf-8")
        logger.info("Knowledge saved to %s", path)

    def load(self, repo_id: str) -> Optional[KnowledgeEntry]:
        path = self._dir / f"{repo_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return KnowledgeEntry.from_dict(data)
        except Exception as exc:
            logger.warning("Failed to load knowledge from %s: %s", path, exc)
            return None


# ===================================================================
# 1d. AWSOpenSearchKnowledgeStore
# ===================================================================

class AWSOpenSearchKnowledgeStore:
    """Stores knowledge in AWS-managed OpenSearch Service with IAM auth."""

    def __init__(
        self,
        opensearch_url: str,
        index: str = "agent_knowledge",
        aws_region: str = "",
    ) -> None:
        self._url = opensearch_url.rstrip("/")
        self._index = index
        self._region = aws_region
        self._client: Any = None

    def _get_client(self) -> Any:
        """Lazy-init: create OpenSearch client with SigV4 auth."""
        if self._client is not None:
            return self._client

        import boto3
        from opensearchpy import OpenSearch, RequestsHttpConnection
        from requests_aws4auth import AWS4Auth

        session = boto3.Session()
        credentials = session.get_credentials().get_frozen_credentials()
        region = self._region or session.region_name or "us-east-1"

        aws4auth = AWS4Auth(
            credentials.access_key,
            credentials.secret_key,
            region,
            "es",
            session_token=credentials.token,
        )

        self._client = OpenSearch(
            hosts=[self._url],
            http_auth=aws4auth,
            use_ssl=self._url.startswith("https"),
            verify_certs=True,
            connection_class=RequestsHttpConnection,
        )

        # Create index if it doesn't exist
        if not self._client.indices.exists(index=self._index):
            self._client.indices.create(index=self._index, body={
                "settings": {"number_of_shards": 1, "number_of_replicas": 0},
            })
            logger.info("Created OpenSearch index: %s", self._index)

        return self._client

    def save(self, entry: KnowledgeEntry) -> None:
        client = self._get_client()
        client.index(
            index=self._index,
            id=entry.repo_id,
            body=entry.to_dict(),
            refresh=True,
        )
        logger.info("Knowledge saved to OpenSearch: %s/%s", self._index, entry.repo_id)

    def load(self, repo_id: str) -> Optional[KnowledgeEntry]:
        client = self._get_client()
        try:
            resp = client.get(index=self._index, id=repo_id, ignore=[404])
            if resp.get("found"):
                return KnowledgeEntry.from_dict(resp["_source"])
            return None
        except Exception as exc:
            logger.warning("Failed to load from OpenSearch: %s", exc)
            return None


# ===================================================================
# 1e. Factory + helpers
# ===================================================================

def compute_repo_id(repo_path: str = "", repo_url: str = "") -> str:
    """Stable SHA-256 hash (16 hex chars) identifying a repository."""
    key = repo_url or repo_path or "unknown"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def get_knowledge_store(config: Optional[dict] = None) -> "FileKnowledgeStore | AWSOpenSearchKnowledgeStore":
    """Select the knowledge backend based on ``[knowledge]`` config."""
    if config is None:
        return FileKnowledgeStore()

    kcfg = config.get("knowledge", {})
    backend = kcfg.get("backend", "file").lower()

    if backend == "opensearch":
        url = kcfg.get("opensearch_url", "")
        if not url:
            logger.warning("OpenSearch backend selected but no URL configured; falling back to file")
            return FileKnowledgeStore(kcfg.get("storage_dir", ""))
        return AWSOpenSearchKnowledgeStore(
            opensearch_url=url,
            index=kcfg.get("opensearch_index", "agent_knowledge"),
            aws_region=kcfg.get("aws_region", ""),
        )

    return FileKnowledgeStore(kcfg.get("storage_dir", ""))


def load_knowledge(
    config: Optional[dict],
    repo_path: str,
    repo_url: str,
) -> Optional[KnowledgeEntry]:
    """Load persistent knowledge for a repository (returns None if not found)."""
    try:
        repo_id = compute_repo_id(repo_path, repo_url)
        store = get_knowledge_store(config)
        return store.load(repo_id)
    except Exception as exc:
        logger.warning("Could not load knowledge: %s", exc)
        return None


def save_knowledge(
    config: Optional[dict],
    repo_path: str,
    repo_url: str,
    working_memory: WorkingMemory,
    summary: str = "",
    files_changed: Optional[list[str]] = None,
) -> None:
    """Save knowledge: merge working memory into persistent entry, then persist."""
    try:
        repo_id = compute_repo_id(repo_path, repo_url)
        store = get_knowledge_store(config)

        # Load existing or create new entry
        entry = store.load(repo_id) or KnowledgeEntry(repo_id=repo_id, repo_url=repo_url)
        entry.merge_working_memory(working_memory, summary, files_changed)
        store.save(entry)
    except Exception as exc:
        logger.warning("Could not save knowledge (non-fatal): %s", exc)


def save_knowledge_with_outcome(
    config: Optional[dict],
    repo_path: str,
    repo_url: str,
    working_memory: WorkingMemory,
    *,
    success: bool,
    summary: str = "",
    files_changed: Optional[list[str]] = None,
    tools_used: Optional[dict[str, int]] = None,
    error_type: str = "",
    error_signature: str = "",
    fix_description: str = "",
) -> None:
    """Save knowledge with outcome data: merges working memory + records run outcome."""
    try:
        repo_id = compute_repo_id(repo_path, repo_url)
        store = get_knowledge_store(config)

        entry = store.load(repo_id) or KnowledgeEntry(repo_id=repo_id, repo_url=repo_url)
        entry.merge_working_memory(working_memory, summary, files_changed)
        entry.record_outcome(
            success=success,
            summary=summary,
            files_changed=files_changed,
            tools_used=tools_used,
            error_type=error_type,
            error_signature=error_signature,
            fix_description=fix_description,
        )
        store.save(entry)
    except Exception as exc:
        logger.warning("Could not save knowledge with outcome (non-fatal): %s", exc)


def get_fix_suggestions(
    config: Optional[dict],
    repo_path: str,
    repo_url: str,
    error_text: str,
) -> list[dict[str, Any]]:
    """Look up known error→fix patterns for the given error text."""
    try:
        repo_id = compute_repo_id(repo_path, repo_url)
        store = get_knowledge_store(config)
        entry = store.load(repo_id)
        if entry:
            return entry.get_fix_suggestions(error_text)
    except Exception as exc:
        logger.warning("Could not look up fix suggestions: %s", exc)
    return []


# ===================================================================
# 1f. Repo Knowledge Files (.code-autonomy.md / AGENT.md)
# ===================================================================

def load_repo_knowledge(repo_path: str) -> str:
    """Load repo knowledge from convention files in the repository root.

    Discovery order (first match wins):
    1. ``.code-autonomy/`` directory — all ``*.md`` files, alphabetically
    2. ``.code-autonomy.md`` — single file
    3. ``AGENT.md`` — alternative single file

    Returns a formatted markdown string ready for injection into context,
    or ``""`` if nothing is found.
    """
    root = Path(repo_path)
    if not root.is_dir():
        return ""

    # Priority 1: directory of .md files
    knowledge_dir = root / _REPO_KNOWLEDGE_DIR
    if knowledge_dir.is_dir():
        result = _load_from_directory(knowledge_dir)
        if result:
            return _cap_length(result)

    # Priority 2: .code-autonomy.md
    knowledge_file = root / _REPO_KNOWLEDGE_FILE
    if knowledge_file.is_file():
        result = _load_single_file(knowledge_file)
        if result:
            return _cap_length(result)

    # Priority 3: AGENT.md
    alt_file = root / _REPO_KNOWLEDGE_ALT_FILE
    if alt_file.is_file():
        result = _load_single_file(alt_file)
        if result:
            return _cap_length(result)

    return ""


def _load_single_file(path: Path) -> str:
    """Read a single repo knowledge file and wrap with a header."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace").strip()
    except Exception as exc:
        logger.warning("Could not read repo knowledge file %s: %s", path, exc)
        return ""

    if not content:
        return ""

    return f"\n\n## Repo Knowledge ({path.name})\n\n{content}\n"


def _load_from_directory(directory: Path) -> str:
    """Concatenate all *.md files in a directory, alphabetically."""
    md_files = sorted(directory.glob("*.md"))
    if not md_files:
        return ""

    parts: list[str] = ["\n\n## Repo Knowledge"]
    for md_file in md_files:
        try:
            content = md_file.read_text(encoding="utf-8", errors="replace").strip()
        except Exception as exc:
            logger.warning("Could not read %s: %s", md_file, exc)
            continue
        if not content:
            continue
        parts.append(f"\n### {md_file.name}\n\n{content}")

    # Only return if we found actual content beyond the header
    if len(parts) <= 1:
        return ""

    return "\n".join(parts) + "\n"


def _cap_length(text: str) -> str:
    """Truncate repo knowledge to prevent oversized context."""
    if len(text) <= _REPO_KNOWLEDGE_MAX_CHARS:
        return text
    logger.warning(
        "Repo knowledge truncated from %d to %d chars",
        len(text),
        _REPO_KNOWLEDGE_MAX_CHARS,
    )
    return text[:_REPO_KNOWLEDGE_MAX_CHARS] + "\n\n[... truncated — repo knowledge exceeded 10,000 chars]\n"


# ===================================================================
# 2. Checkpointing (resume from incomplete runs)
# ===================================================================

def compute_requirement_hash(requirements: str) -> str:
    """SHA-256 of normalized requirement text (first 16 hex chars)."""
    normalized = " ".join(requirements.strip().split())
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


@dataclass
class Checkpoint:
    """Snapshot of an incomplete agent run for resumption."""

    repo_id: str = ""
    repo_url: str = ""
    requirement_hash: str = ""
    requirements_text: str = ""
    created_at: str = ""
    files_changed: list[str] = field(default_factory=list)
    summary: str = ""
    pending_work: str = ""
    working_memory: dict[str, str] = field(default_factory=dict)
    turns_used: int = 0
    max_turns: int = 0
    summarization_calls_used: int = 0
    testing_turns_used: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo_id": self.repo_id,
            "repo_url": self.repo_url,
            "requirement_hash": self.requirement_hash,
            "requirements_text": self.requirements_text,
            "created_at": self.created_at,
            "files_changed": self.files_changed,
            "summary": self.summary,
            "pending_work": self.pending_work,
            "working_memory": self.working_memory,
            "turns_used": self.turns_used,
            "max_turns": self.max_turns,
            "summarization_calls_used": self.summarization_calls_used,
            "testing_turns_used": self.testing_turns_used,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Checkpoint":
        return cls(
            repo_id=data.get("repo_id", ""),
            repo_url=data.get("repo_url", ""),
            requirement_hash=data.get("requirement_hash", ""),
            requirements_text=data.get("requirements_text", ""),
            created_at=data.get("created_at", ""),
            files_changed=data.get("files_changed", []),
            summary=data.get("summary", ""),
            pending_work=data.get("pending_work", ""),
            working_memory=data.get("working_memory", {}),
            turns_used=data.get("turns_used", 0),
            max_turns=data.get("max_turns", 0),
            summarization_calls_used=data.get("summarization_calls_used", 0),
            testing_turns_used=data.get("testing_turns_used", 0),
        )

    def to_context_string(self) -> str:
        """Render as context block for injection into the agent prompt on resume."""
        lines: list[str] = ["## Checkpoint from previous incomplete run"]
        lines.append(f"Previous run used {self.turns_used}/{self.max_turns} turns before stopping.")

        if self.files_changed:
            lines.append(f"\n### Files already changed ({len(self.files_changed)})")
            for f in self.files_changed:
                lines.append(f"  - {f}")

        if self.summary:
            lines.append(f"\n### What was accomplished\n{self.summary}")

        if self.pending_work:
            lines.append(f"\n### What still needs to be done\n{self.pending_work}")

        if self.working_memory:
            lines.append("\n### Working memory from previous run")
            for k, v in self.working_memory.items():
                lines.append(f"#### {k}\n{v}")

        return "\n".join(lines)


# ===================================================================
# 2a. FileCheckpointStore
# ===================================================================

class FileCheckpointStore:
    """Stores checkpoints as JSON files in ``~/.code-autonomy/checkpoints/``."""

    def __init__(self, storage_dir: str = "") -> None:
        if storage_dir:
            self._dir = Path(os.path.expanduser(storage_dir))
        else:
            self._dir = Path.home() / ".code-autonomy" / "checkpoints"

    def save(self, checkpoint: Checkpoint) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._dir / f"{checkpoint.repo_id}.json"
        path.write_text(json.dumps(checkpoint.to_dict(), indent=2), encoding="utf-8")
        logger.info("Checkpoint saved to %s", path)

    def load(self, repo_id: str) -> Optional[Checkpoint]:
        path = self._dir / f"{repo_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return Checkpoint.from_dict(data)
        except Exception as exc:
            logger.warning("Failed to load checkpoint from %s: %s", path, exc)
            return None

    def clear(self, repo_id: str) -> None:
        path = self._dir / f"{repo_id}.json"
        if path.exists():
            path.unlink()
            logger.info("Checkpoint cleared: %s", path)


# ===================================================================
# 2b. AWSOpenSearchCheckpointStore
# ===================================================================

class AWSOpenSearchCheckpointStore:
    """Stores checkpoints in AWS-managed OpenSearch Service with IAM auth."""

    def __init__(
        self,
        opensearch_url: str,
        index: str = "agent_checkpoints",
        aws_region: str = "",
    ) -> None:
        self._url = opensearch_url.rstrip("/")
        self._index = index
        self._region = aws_region
        self._client: Any = None

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client

        import boto3
        from opensearchpy import OpenSearch, RequestsHttpConnection
        from requests_aws4auth import AWS4Auth

        session = boto3.Session()
        credentials = session.get_credentials().get_frozen_credentials()
        region = self._region or session.region_name or "us-east-1"

        aws4auth = AWS4Auth(
            credentials.access_key,
            credentials.secret_key,
            region,
            "es",
            session_token=credentials.token,
        )

        self._client = OpenSearch(
            hosts=[self._url],
            http_auth=aws4auth,
            use_ssl=self._url.startswith("https"),
            verify_certs=True,
            connection_class=RequestsHttpConnection,
        )

        if not self._client.indices.exists(index=self._index):
            self._client.indices.create(index=self._index, body={
                "settings": {"number_of_shards": 1, "number_of_replicas": 0},
            })
            logger.info("Created OpenSearch index: %s", self._index)

        return self._client

    def save(self, checkpoint: Checkpoint) -> None:
        client = self._get_client()
        client.index(
            index=self._index,
            id=checkpoint.repo_id,
            body=checkpoint.to_dict(),
            refresh=True,
        )
        logger.info("Checkpoint saved to OpenSearch: %s/%s", self._index, checkpoint.repo_id)

    def load(self, repo_id: str) -> Optional[Checkpoint]:
        client = self._get_client()
        try:
            resp = client.get(index=self._index, id=repo_id, ignore=[404])
            if resp.get("found"):
                return Checkpoint.from_dict(resp["_source"])
            return None
        except Exception as exc:
            logger.warning("Failed to load checkpoint from OpenSearch: %s", exc)
            return None

    def clear(self, repo_id: str) -> None:
        client = self._get_client()
        try:
            client.delete(index=self._index, id=repo_id, ignore=[404], refresh=True)
            logger.info("Checkpoint cleared from OpenSearch: %s/%s", self._index, repo_id)
        except Exception as exc:
            logger.warning("Failed to clear checkpoint from OpenSearch: %s", exc)


# ===================================================================
# 2c. Checkpoint factory + helpers
# ===================================================================

def get_checkpoint_store(config: Optional[dict] = None) -> "FileCheckpointStore | AWSOpenSearchCheckpointStore":
    """Select the checkpoint backend based on ``[knowledge]`` config."""
    if config is None:
        return FileCheckpointStore()

    kcfg = config.get("knowledge", {})
    backend = kcfg.get("backend", "file").lower()

    if backend == "opensearch":
        url = kcfg.get("opensearch_url", "")
        if not url:
            return FileCheckpointStore(kcfg.get("storage_dir", ""))
        return AWSOpenSearchCheckpointStore(
            opensearch_url=url,
            index=kcfg.get("checkpoint_index", "agent_checkpoints"),
            aws_region=kcfg.get("aws_region", ""),
        )

    return FileCheckpointStore(kcfg.get("storage_dir", ""))


def save_checkpoint(
    config: Optional[dict],
    repo_path: str,
    repo_url: str,
    requirements: str,
    files_changed: list[str],
    working_memory: "WorkingMemory | dict[str, str]",
    turns_used: int = 0,
    max_turns: int = 0,
    summary: str = "",
    pending_work: str = "",
    summarization_calls_used: int = 0,
    testing_turns_used: int = 0,
) -> Checkpoint:
    """Create and persist a checkpoint for an incomplete agent run."""
    repo_id = compute_repo_id(repo_path, repo_url)
    req_hash = compute_requirement_hash(requirements)

    wm_dict: dict[str, str]
    if isinstance(working_memory, WorkingMemory):
        wm_dict = working_memory.to_dict()
    else:
        wm_dict = dict(working_memory)

    checkpoint = Checkpoint(
        repo_id=repo_id,
        repo_url=repo_url,
        requirement_hash=req_hash,
        requirements_text=requirements[:2000],
        created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        files_changed=files_changed,
        summary=summary,
        pending_work=pending_work,
        working_memory=wm_dict,
        turns_used=turns_used,
        max_turns=max_turns,
        summarization_calls_used=summarization_calls_used,
        testing_turns_used=testing_turns_used,
    )

    try:
        store = get_checkpoint_store(config)
        store.save(checkpoint)
    except Exception as exc:
        logger.warning("Could not save checkpoint (non-fatal): %s", exc)

    return checkpoint


def load_checkpoint(
    config: Optional[dict],
    repo_path: str,
    repo_url: str,
) -> Optional[Checkpoint]:
    """Load the most recent checkpoint for a repository (returns None if not found)."""
    try:
        repo_id = compute_repo_id(repo_path, repo_url)
        store = get_checkpoint_store(config)
        return store.load(repo_id)
    except Exception as exc:
        logger.warning("Could not load checkpoint: %s", exc)
        return None


def clear_checkpoint(
    config: Optional[dict],
    repo_path: str,
    repo_url: str,
) -> None:
    """Remove the checkpoint for a repository (called on successful completion)."""
    try:
        repo_id = compute_repo_id(repo_path, repo_url)
        store = get_checkpoint_store(config)
        store.clear(repo_id)
    except Exception as exc:
        logger.warning("Could not clear checkpoint (non-fatal): %s", exc)
