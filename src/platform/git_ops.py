"""
Git operations for autonomous code generation.
Handles clone, checkout, commit, and push.
"""

import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from git import Repo
from git.exc import GitCommandError


def get_repo_name(repo_url: str) -> str:
    """Extract repo name from URL (e.g., owner/repo from https://github.com/owner/repo.git)."""
    # Remove .git suffix and trailing slashes
    url = repo_url.rstrip("/").rstrip(".git")
    # Get last two path segments (owner/repo)
    parts = url.split("/")
    if len(parts) >= 2:
        return "/".join(parts[-2:])
    return parts[-1] if parts else "repo"


def generate_branch_name(base: Optional[str] = None) -> str:
    """Generate a feature branch name with timestamp."""
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    if base:
        # Sanitize: replace spaces/special chars with hyphens
        safe_base = re.sub(r"[^\w\-]", "-", base.strip()).strip("-")
        return f"feature/auto-{safe_base}-{timestamp}"
    return f"feature/auto-{timestamp}"


def clone_repo(
    repo_url: str,
    target_dir: str,
    branch: str = "main",
    auth_token: Optional[str] = None,
) -> Repo:
    """
    Clone repository into target directory.
    Injects auth token into URL for private repos.
    """
    target = Path(target_dir)
    if target.exists() and any(target.iterdir()):
        raise FileExistsError(f"Target directory not empty: {target_dir}")

    url = repo_url
    if auth_token:
        # Inject token: https://user:TOKEN@host/owner/repo.git
        if "github.com" in repo_url:
            url = repo_url.replace("https://", f"https://x-access-token:{auth_token}@")
        elif "bitbucket.org" in repo_url:
            # Bitbucket Cloud: https://user:app_password@bitbucket.org/workspace/repo.git
            url = repo_url.replace("https://", f"https://x-token-auth:{auth_token}@")
        elif repo_url.startswith("https://"):
            # Generic HTTPS (e.g. Bitbucket Server): inject token as user
            url = repo_url.replace("https://", f"https://x-token-auth:{auth_token}@")

    repo = Repo.clone_from(url, target_dir, branch=branch, depth=1)
    return repo


def clone_repo_ssh(
    ssh_url: str,
    target_dir: str,
    branch: str = "main",
) -> Repo:
    """Clone a repository via SSH (relies on SSH key auth configured on the host).

    Uses subprocess to invoke git directly so SSH agent / key-based auth works
    without token injection.
    """
    target = Path(target_dir)
    if target.exists() and any(target.iterdir()):
        raise FileExistsError(f"Target directory not empty: {target_dir}")

    target.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["git", "clone", "--branch", branch, "--depth", "1", ssh_url, str(target)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise GitCommandError(cmd, result.returncode, result.stderr)
    return Repo(str(target))


def checkout_branch(repo: Repo, branch_name: str, create: bool = True) -> None:
    """Checkout or create a new branch."""
    if create and branch_name not in [b.name for b in repo.branches]:
        repo.git.checkout("-b", branch_name)
    else:
        repo.git.checkout(branch_name)


def stage_and_commit(repo: Repo, message: str, author_name: str = "Auto Coder", author_email: str = "auto@coder.local") -> None:
    """Stage all changes and commit."""
    if not (repo.is_dirty() or repo.untracked_files):
        return

    repo.git.add("-A")
    with repo.config_writer() as cw:
        cw.set_value("user", "name", author_name)
        cw.set_value("user", "email", author_email)
    repo.index.commit(message)


def push_branch(repo: Repo, branch_name: str, remote: str = "origin") -> None:
    """Push branch to remote."""
    origin = repo.remote(remote)
    origin.push(branch_name)


def get_default_branch(repo: Repo) -> str:
    """Get default branch (main or master) from remote."""
    try:
        origin = repo.remote("origin")
        refs = origin.refs
        for ref in refs:
            if ref.name == "origin/main":
                return "main"
            if ref.name == "origin/master":
                return "master"
    except Exception:
        pass
    return "main"
