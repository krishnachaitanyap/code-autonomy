"""
Git operations for autonomous code generation.
Handles clone, checkout, commit, and push via subprocess (no GitPython dependency).
"""

import logging
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _git(repo_dir: str, *args: str, timeout: int = 300) -> subprocess.CompletedProcess:
    """Run a git command in *repo_dir*."""
    cmd = ["git"] + list(args)
    logger.debug("git cmd: %s (cwd=%s)", " ".join(args), repo_dir)
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, cwd=repo_dir,
    )
    if result.returncode != 0:
        logger.error("git failed (exit %d): %s", result.returncode, result.stderr.strip())
    return result


def get_repo_name(repo_url: str) -> str:
    """Extract repo name from URL (e.g., owner/repo from https://github.com/owner/repo.git)."""
    url = repo_url.rstrip("/").rstrip(".git")
    parts = url.split("/")
    if len(parts) >= 2:
        return "/".join(parts[-2:])
    return parts[-1] if parts else "repo"


def generate_branch_name(base: Optional[str] = None) -> str:
    """Generate a feature branch name with timestamp."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if base:
        safe_base = re.sub(r"[^\w\-]", "-", base.strip()).strip("-")
        return f"feature/auto-{safe_base}-{timestamp}"
    return f"feature/auto-{timestamp}"


def clone_repo(
    repo_url: str,
    target_dir: str,
    branch: str = "main",
    auth_token: Optional[str] = None,
) -> str:
    """Clone repository into target directory using subprocess.

    Returns the path to the cloned repo directory.
    """
    target = Path(target_dir)
    if target.exists() and any(target.iterdir()):
        raise FileExistsError(f"Target directory not empty: {target_dir}")

    target.parent.mkdir(parents=True, exist_ok=True)

    cmd = ["git"]
    if auth_token:
        cmd += ["-c", f"http.extraHeader=Authorization: Bearer {auth_token}"]
    cmd += ["clone", "--branch", branch, "--depth", "1", repo_url, str(target)]

    logger.info("Cloning %s (branch=%s)", repo_url, branch)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(
            f"git clone failed (exit {result.returncode}): {result.stderr.strip()}"
        )
    return str(target)


def checkout_branch(repo_dir: str, branch_name: str, create: bool = True) -> None:
    """Checkout or create a new branch."""
    if create:
        r = _git(repo_dir, "checkout", "-b", branch_name)
        if r.returncode != 0:
            raise RuntimeError(f"Failed to create branch {branch_name}: {r.stderr.strip()}")
    else:
        r = _git(repo_dir, "checkout", branch_name)
        if r.returncode != 0:
            raise RuntimeError(f"Failed to checkout branch {branch_name}: {r.stderr.strip()}")


def stage_and_commit(
    repo_dir: str,
    message: str,
    author_name: str = "Auto Coder",
    author_email: str = "auto@coder.local",
) -> None:
    """Stage all changes and commit."""
    status = _git(repo_dir, "status", "--porcelain")
    if not status.stdout.strip():
        return  # Nothing to commit

    _git(repo_dir, "add", "-A")
    _git(repo_dir, "config", "user.name", author_name)
    _git(repo_dir, "config", "user.email", author_email)

    r = _git(repo_dir, "commit", "-m", message)
    if r.returncode != 0:
        raise RuntimeError(f"Commit failed: {r.stderr.strip()}")


def push_branch(repo_dir: str, branch_name: str, remote: str = "origin") -> None:
    """Push branch to remote."""
    r = _git(repo_dir, "push", remote, branch_name)
    if r.returncode != 0:
        raise RuntimeError(f"Push failed: {r.stderr.strip()}")


def get_default_branch(repo_dir: str) -> str:
    """Get default branch (main or master) from remote."""
    r = _git(repo_dir, "ls-remote", "--symref", "origin", "HEAD")
    if r.returncode == 0 and "refs/heads/" in r.stdout:
        for line in r.stdout.splitlines():
            if line.startswith("ref:"):
                branch = line.split("refs/heads/")[-1].split()[0]
                if branch:
                    return branch
    return "main"
