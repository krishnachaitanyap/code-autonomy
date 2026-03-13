"""
Thread-safe in-session file I/O cache with mtime invalidation.

Caches file contents and directory listings to avoid repeated disk I/O
during a single agent session. Uses mtime checks for content cache and
key-based lookup for directory listings.
"""

import threading
from pathlib import Path
from typing import Optional


class FileIOCache:
    """In-session file I/O cache with mtime invalidation."""

    def __init__(self, max_files: int = 500, max_dirs: int = 100) -> None:
        self._file_cache: dict[str, tuple[float, str]] = {}  # path → (mtime, content)
        self._dir_cache: dict[tuple, list[Path]] = {}  # (root, exts) → file list
        self._max_files = max_files
        self._max_dirs = max_dirs
        self._lock = threading.Lock()

    def read_file(self, path: Path) -> Optional[str]:
        """Read a file, returning cached content if mtime hasn't changed."""
        key = str(path)
        try:
            current_mtime = path.stat().st_mtime
        except OSError:
            return None

        with self._lock:
            if key in self._file_cache:
                cached_mtime, cached_content = self._file_cache[key]
                if cached_mtime == current_mtime:
                    return cached_content

        # Read from disk
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return None

        with self._lock:
            if len(self._file_cache) >= self._max_files:
                # Evict oldest entries (simple strategy: clear half)
                keys = list(self._file_cache.keys())
                for k in keys[: len(keys) // 2]:
                    del self._file_cache[k]
            self._file_cache[key] = (current_mtime, content)

        return content

    def list_directory(
        self,
        repo_root: Path,
        skip_dirs: set,
        extensions: Optional[set] = None,
    ) -> list[Path]:
        """Return a cached recursive file listing, filtered by extensions."""
        cache_key = (str(repo_root), frozenset(extensions or set()))

        with self._lock:
            if cache_key in self._dir_cache:
                return self._dir_cache[cache_key]

        # Walk the directory
        result: list[Path] = []
        try:
            for f in repo_root.rglob("*"):
                if not f.is_file():
                    continue
                try:
                    rel_parts = f.relative_to(repo_root).parts
                except ValueError:
                    continue
                if any(p in skip_dirs for p in rel_parts):
                    continue
                if extensions and f.suffix not in extensions:
                    continue
                result.append(f)
        except Exception:
            pass

        with self._lock:
            if len(self._dir_cache) >= self._max_dirs:
                self._dir_cache.clear()
            self._dir_cache[cache_key] = result

        return result

    def invalidate_file(self, path: Path) -> None:
        """Remove a file from the cache (call after write/edit/delete)."""
        key = str(path)
        with self._lock:
            self._file_cache.pop(key, None)
            # Also invalidate directory caches since file list may have changed
            self._dir_cache.clear()

    def reset(self) -> None:
        """Clear all caches."""
        with self._lock:
            self._file_cache.clear()
            self._dir_cache.clear()


# ---------------------------------------------------------------------------
# Thread-local session cache — each concurrent session gets its own instance
# ---------------------------------------------------------------------------

import threading

_thread_local = threading.local()


def get_session_cache() -> FileIOCache:
    """Return the session-level file cache (per-thread, lazy)."""
    cache = getattr(_thread_local, "file_cache", None)
    if cache is None:
        cache = FileIOCache()
        _thread_local.file_cache = cache
    return cache


def reset_session_cache() -> None:
    """Create a fresh cache instance for this thread (called at session start)."""
    _thread_local.file_cache = FileIOCache()
