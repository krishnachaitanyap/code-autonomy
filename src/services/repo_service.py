"""
RepoService — repository registration, consciousness, and code index management.

Wraps existing git operations, consciousness building, and code index building.
"""

import logging
import os
from pathlib import Path
from typing import Optional

from src.agent.knowledge import compute_repo_id

logger = logging.getLogger(__name__)


class RepoService:
    """Service for repository management."""

    def register_repo(
        self,
        repo_path: str,
        platform: str = "local",
        repo_url: str = "",
    ) -> "Repo":
        """Register a repository in the database.

        Args:
            repo_path: Local filesystem path to the repo.
            platform: "github", "bitbucket", or "local".
            repo_url: Remote URL (if any).

        Returns:
            Repo ORM model.
        """
        from src.data.database import get_session, init_db
        from src.data.repositories import RepoRepository

        init_db()
        repo_id = compute_repo_id(repo_path, repo_url)

        with get_session() as db:
            return RepoRepository(db).get_or_create(
                repo_id=repo_id,
                url=repo_url,
                local_path=str(Path(repo_path).resolve()) if repo_path else "",
                platform=platform,
            )

    def get_repo(self, repo_id: str) -> Optional["Repo"]:
        """Get a registered repo by ID."""
        from src.data.database import get_session
        from src.data.repositories import RepoRepository

        with get_session() as db:
            return RepoRepository(db).get_by_id(repo_id)

    def list_repos(self) -> list:
        """List all registered repos."""
        try:
            from src.data.database import get_session
            from src.data.repositories import RepoRepository

            with get_session() as db:
                return RepoRepository(db).list_all()
        except Exception:
            return []

    def ensure_local_clone(
        self,
        repo_id: str,
        branch: str = "main",
        config: dict | None = None,
    ) -> str:
        """Ensure the repo has a local clone. Clone if needed. Returns local path.

        Raises:
            ValueError: If the repo has no URL and no valid local_path.
        """
        from src.data.database import get_session, init_db
        from src.data.repositories import RepoRepository
        from src.platform.git_ops import clone_repo
        from src.platform.platform_client import _resolve_token

        init_db()

        with get_session() as db:
            repo = RepoRepository(db).get_by_id(repo_id)
            if repo is None:
                raise ValueError(f"Repository not found: {repo_id}")

            # Already has a valid local path
            if repo.local_path and os.path.isdir(repo.local_path):
                return repo.local_path

            # Need a URL to clone from
            if not repo.url:
                raise ValueError(
                    f"Repository {repo_id} has no local_path and no URL to clone from."
                )

            # Determine clone target directory
            work_dir = (config or {}).get("workflow", {}).get("work_dir", "./workspace")
            clone_target = str(Path(work_dir) / "repos" / repo_id)

            # If the clone target already exists (previous clone), reuse it
            if os.path.isdir(clone_target) and os.path.isdir(
                os.path.join(clone_target, ".git")
            ):
                logger.info("Reusing existing clone at %s", clone_target)
                RepoRepository(db).update(repo_id, local_path=clone_target)
                return clone_target

            # Resolve auth token for the platform
            token = _resolve_token(repo.platform)

            logger.info(
                "Auto-cloning %s (branch=%s) into %s", repo.url, branch, clone_target,
            )
            try:
                clone_repo(
                    repo_url=repo.url,
                    target_dir=clone_target,
                    branch=branch,
                    auth_token=token or None,
                )
            except Exception as exc:
                raise ValueError(
                    f"Failed to clone {repo.url}: {exc}"
                ) from exc

            # Persist the local_path so future requests skip cloning
            RepoRepository(db).update(repo_id, local_path=clone_target)
            logger.info("Clone complete. Updated repo %s local_path=%s", repo_id, clone_target)
            return clone_target

    def build_consciousness(
        self,
        repo_path: str,
        config: Optional[dict] = None,
        repo_url: str = "",
        force_rebuild: bool = False,
    ) -> "ProjectConsciousness":
        """Build or load project consciousness for a repo.

        Args:
            repo_path: Path to the repository.
            config: Full config dict (optional).
            repo_url: Remote URL (optional).
            force_rebuild: Force a full rebuild.

        Returns:
            ProjectConsciousness dataclass.
        """
        from src.consciousness.core import build_consciousness as _build
        from src.consciousness.core import build_or_load_consciousness

        if config:
            return build_or_load_consciousness(
                repo_path, config, repo_url=repo_url, force_rebuild=force_rebuild
            )
        return _build(repo_path, repo_url)

    def build_code_index(
        self,
        repo_path: str,
        config: dict,
        repo_url: str = "",
        consciousness: Optional["ProjectConsciousness"] = None,
    ) -> Optional["CodeIndex"]:
        """Build or load the code index for a repo.

        Returns:
            CodeIndex or None if building fails.
        """
        try:
            from src.code_index import build_or_load_code_index

            return build_or_load_code_index(
                repo_path, config, repo_url=repo_url,
                consciousness=consciousness,
            )
        except Exception as exc:
            logger.warning("Could not build code index: %s", exc)
            return None

    def get_symbols(
        self,
        repo_path: str,
        config: dict,
        repo_url: str = "",
        file_path: Optional[str] = None,
    ) -> list:
        """Get symbol table entries for a repo.

        Args:
            file_path: Optional filter to specific file.

        Returns:
            List of SymbolEntry dicts.
        """
        code_index = self.build_code_index(repo_path, config, repo_url)
        if code_index is None or code_index.symbol_table is None:
            return []

        if file_path:
            entries = code_index.symbol_table.get_by_file(file_path)
        else:
            entries = list(code_index.symbol_table._entries.values())

        return [
            {
                "fqn": e.fqn,
                "name": e.name,
                "file_path": e.file_path,
                "symbol_type": e.symbol_type,
                "line_start": e.line_start,
                "line_end": e.line_end,
                "signature": e.signature,
                "parent_class": e.parent_class,
            }
            for e in entries[:500]  # Cap to prevent huge responses
        ]
