"""
Git operations for autonomous code generation.
Handles clone, checkout, commit, and push via subprocess (no GitPython dependency).
"""

import logging
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Env overrides to suppress credential prompts (Windows CredentialHelperSelector, etc.)
_GIT_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": ""}


def _git(repo_dir: str, *args: str, timeout: int = 300) -> subprocess.CompletedProcess:
    """Run a git command in *repo_dir*."""
    cmd = ["git"] + list(args)
    logger.debug("git cmd: %s (cwd=%s)", " ".join(args), repo_dir)
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, cwd=repo_dir, env=_GIT_ENV,
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

    cmd = ["git", "-c", "core.longpaths=true"]
    if auth_token:
        cmd += ["-c", f"http.extraHeader=Authorization: Bearer {auth_token}"]
    cmd += ["clone", "--branch", branch, "--depth", "1", repo_url, str(target)]

    logger.info("Cloning %s (branch=%s)", repo_url, branch)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        # "Clone succeeded, but checkout failed" (exit 128) is OK on Windows
        # when some files have paths exceeding 260 chars.  The .git/ data is
        # complete; only a few working-tree files are missing.
        git_dir = target / ".git"
        if git_dir.is_dir():
            logger.warning(
                "Clone partial (exit %d): some long-path files missing from "
                "working tree. Continuing with available files.", result.returncode,
            )
        else:
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


def list_branches(repo_dir: str) -> list[str]:
    """List all local and remote branches, returning unique short names sorted."""
    branches: set[str] = set()

    # Local branches
    r = _git(repo_dir, "branch", "--format=%(refname:short)")
    if r.returncode == 0:
        for line in r.stdout.splitlines():
            name = line.strip()
            if name:
                branches.add(name)

    # Remote branches (strip "origin/" prefix, skip HEAD)
    r = _git(repo_dir, "branch", "-r", "--format=%(refname:short)")
    if r.returncode == 0:
        for line in r.stdout.splitlines():
            name = line.strip()
            if name and "HEAD" not in name:
                # "origin/main" -> "main"
                short = name.split("/", 1)[1] if "/" in name else name
                branches.add(short)

    return sorted(branches)


def list_remote_branches(repo_url: str, auth_token: Optional[str] = None) -> list[str]:
    """List branches from a remote repository URL without cloning."""
    cmd = ["git"]
    if auth_token:
        cmd += ["-c", f"http.extraHeader=Authorization: Bearer {auth_token}"]
    cmd += ["ls-remote", "--heads", repo_url]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            logger.warning("git ls-remote failed for %s: %s", repo_url, result.stderr.strip())
            return []
        branches: list[str] = []
        for line in result.stdout.splitlines():
            # Format: <sha>\trefs/heads/<branch>
            parts = line.strip().split("\t")
            if len(parts) == 2 and parts[1].startswith("refs/heads/"):
                branch = parts[1].replace("refs/heads/", "")
                branches.append(branch)
        return sorted(branches)
    except Exception as exc:
        logger.warning("Failed to list remote branches for %s: %s", repo_url, exc)
        return []


def get_current_branch(repo_dir: str) -> str:
    """Get the currently checked-out branch in the workspace. Returns '' if detached or error."""
    r = _git(repo_dir, "rev-parse", "--abbrev-ref", "HEAD")
    if r.returncode == 0:
        branch = r.stdout.strip()
        return branch if branch != "HEAD" else ""  # "HEAD" means detached
    return ""


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
