"""
Thread-safe in-memory LRU cache with TTL for per-repo data.

Caches consciousness, code_index, and repo_knowledge to avoid
rebuilding/reloading from disk on every request.
"""

import threading
import time
from typing import Any, Optional

# Default TTLs (seconds)
TTL_CONSCIOUSNESS = 3600   # 1 hour
TTL_CODE_INDEX = 3600      # 1 hour
TTL_REPO_KNOWLEDGE = 300   # 5 minutes

_MAX_REPOS = 32


class _CacheEntry:
    __slots__ = ("value", "timestamp")

    def __init__(self, value: Any) -> None:
        self.value = value
        self.timestamp = time.monotonic()


class RepoCache:
    """Thread-safe per-repo cache with TTL and LRU eviction."""

    def __init__(self, max_repos: int = _MAX_REPOS) -> None:
        self._max_repos = max_repos
        self._lock = threading.Lock()
        # repo_id -> {key -> _CacheEntry}
        self._data: dict[str, dict[str, _CacheEntry]] = {}
        # repo_id -> last_access_time (for LRU eviction)
        self._access: dict[str, float] = {}

    def get(self, repo_id: str, key: str, ttl_seconds: float) -> Optional[Any]:
        """Return cached value if present and not expired, else None."""
        with self._lock:
            repo_data = self._data.get(repo_id)
            if repo_data is None:
                return None
            entry = repo_data.get(key)
            if entry is None:
                return None
            if time.monotonic() - entry.timestamp > ttl_seconds:
                del repo_data[key]
                return None
            self._access[repo_id] = time.monotonic()
            return entry.value

    def put(self, repo_id: str, key: str, value: Any) -> None:
        """Store a value, evicting the oldest repo if at capacity."""
        with self._lock:
            if repo_id not in self._data:
                if len(self._data) >= self._max_repos:
                    self._evict_oldest()
                self._data[repo_id] = {}
            self._data[repo_id][key] = _CacheEntry(value)
            self._access[repo_id] = time.monotonic()

    def invalidate(self, repo_id: str, key: Optional[str] = None) -> None:
        """Clear a specific key or all keys for a repo."""
        with self._lock:
            if key is not None:
                repo_data = self._data.get(repo_id)
                if repo_data and key in repo_data:
                    del repo_data[key]
            else:
                self._data.pop(repo_id, None)
                self._access.pop(repo_id, None)

    def _evict_oldest(self) -> None:
        """Remove the least-recently-accessed repo. Caller holds _lock."""
        if not self._access:
            return
        oldest = min(self._access, key=self._access.get)  # type: ignore[arg-type]
        self._data.pop(oldest, None)
        self._access.pop(oldest, None)


# Module-level singleton
repo_cache = RepoCache()
