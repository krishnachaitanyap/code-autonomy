"""
Orchestration bridge: JIRA stories ↔ Bitbucket Server git workflow.

Handles cloning, branching, committing, pushing, PR creation, and cleanup
for each JIRA story processed by the agent.

Uses only subprocess git commands + requests (no GitPython dependency).
"""

import logging
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.platform.bitbucket_server import BitbucketServerClient

logger = logging.getLogger(__name__)


def _git(repo_dir: str, *args: str, token: Optional[str] = None, timeout: int = 300) -> subprocess.CompletedProcess:
    """Run a git command in the given repo directory with optional Bearer token auth."""
    cmd = ["git"]
    if token:
        cmd += ["-c", f"http.extraHeader=Authorization: Bearer {token}"]
    cmd += list(args)
    logger.debug("git cmd: %s (cwd=%s)", " ".join(args), repo_dir)
    result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=timeout, cwd=repo_dir,
    )
    if result.returncode != 0:
        logger.error("git failed (exit %d): %s", result.returncode, result.stderr.strip())
    return result


def clone_bitbucket_repo(
    clone_url: str,
    target_dir: str,
    branch: str = "main",
    auth_token: Optional[str] = None,
    protocol: str = "ssh",
) -> str:
    """Clone a Bitbucket Server repository.

    Returns the path to the cloned repo directory.
    SSH uses key-based auth; HTTPS uses Bearer token via http.extraHeader.
    """
    target = Path(target_dir)
    if target.exists() and any(target.iterdir()):
        # Already cloned — just return the path
        logger.info("Repo already exists at %s, reusing", target_dir)
        return str(target)

    target.parent.mkdir(parents=True, exist_ok=True)

    cmd = ["git"]
    if protocol == "https" and auth_token:
        cmd += ["-c", f"http.extraHeader=Authorization: Bearer {auth_token}"]
    cmd += ["clone", "--branch", branch, "--depth", "1", clone_url, str(target)]

    logger.info("Cloning %s (protocol=%s, branch=%s)", clone_url, protocol, branch)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(
            f"git clone failed (exit {result.returncode}): {result.stderr.strip()}"
        )
    return str(target)


def prepare_story_branch(
    repo_dir: str,
    story_key: str,
    base_branch: str,
    auth_token: Optional[str] = None,
) -> str:
    """Create a feature branch for a story from the base branch.

    Returns the branch name (``feature/auto-{STORY_KEY}-{timestamp}``).
    """
    # Checkout base branch
    r = _git(repo_dir, "checkout", base_branch)
    if r.returncode != 0:
        # Branch might not exist locally — fetch and try again
        _git(repo_dir, "fetch", "origin", token=auth_token)
        r = _git(repo_dir, "checkout", base_branch)
        if r.returncode != 0:
            _git(repo_dir, "checkout", "-b", base_branch, f"origin/{base_branch}")

    # Pull latest
    _git(repo_dir, "pull", "origin", base_branch, token=auth_token)

    # Create feature branch
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_key = re.sub(r"[^\w\-]", "-", story_key.strip()).strip("-")
    branch_name = f"feature/auto-{safe_key}-{timestamp}"
    r = _git(repo_dir, "checkout", "-b", branch_name)
    if r.returncode != 0:
        raise RuntimeError(f"Failed to create branch {branch_name}: {r.stderr.strip()}")

    logger.info("Created branch: %s", branch_name)
    return branch_name


def commit_and_push_story(
    repo_dir: str,
    branch_name: str,
    story_key: str,
    summary: str,
    files_changed: list[str],
    auth_token: Optional[str] = None,
) -> bool:
    """Stage all changes, commit, and push the story branch.

    Returns True on success, False on failure.
    """
    try:
        # Check if there are changes to commit
        status = _git(repo_dir, "status", "--porcelain")
        if not status.stdout.strip():
            logger.info("No changes to commit for %s", story_key)
            return False

        # Stage all changes
        _git(repo_dir, "add", "-A")

        # Configure author
        _git(repo_dir, "config", "user.name", "Auto Coder")
        _git(repo_dir, "config", "user.email", "auto@coder.local")

        # Commit
        commit_msg = f"{story_key}: {summary}"
        r = _git(repo_dir, "commit", "-m", commit_msg)
        if r.returncode != 0:
            logger.error("Commit failed for %s: %s", story_key, r.stderr.strip())
            return False

        # Push
        r = _git(repo_dir, "push", "origin", branch_name, token=auth_token)
        if r.returncode != 0:
            logger.error("Push failed for %s: %s", story_key, r.stderr.strip())
            return False

        logger.info("Pushed %s to origin/%s", story_key, branch_name)
        return True
    except Exception as e:
        logger.error("Commit/push failed for %s: %s", story_key, e)
        return False


def discard_story_changes(repo_dir: str, base_branch: str) -> None:
    """Discard all uncommitted changes and return to the base branch."""
    try:
        _git(repo_dir, "checkout", base_branch)
        _git(repo_dir, "clean", "-fd")
        _git(repo_dir, "reset", "--hard")
    except Exception as e:
        logger.warning("discard_story_changes failed: %s", e)


def create_story_pr(
    bb_config: dict,
    repo_url: str,
    source_branch: str,
    target_branch: str,
    story_key: str,
    story_summary: str,
    agent_summary: str,
) -> Optional[str]:
    """Create a pull request on Bitbucket Server for a completed story.

    Returns the PR URL on success, None on failure.
    """
    client = BitbucketServerClient(
        base_url=bb_config["base_url"],
        token=bb_config["user_token"],
        verify_ssl=bb_config.get("verify_ssl", False),
    )

    project_key = bb_config["project_key"]
    repo_slug = bb_config["repo_slug"]

    title = f"{story_key}: {story_summary}"
    if len(title) > 120:
        title = title[:117] + "..."

    description = (
        f"**Story:** {story_key}\n\n"
        f"**Summary:** {story_summary}\n\n"
        f"**Agent output:**\n{agent_summary}\n\n"
        f"_Generated by code-autonomy_"
    )

    return client.create_pull_request(
        project_key, repo_slug, title, description, source_branch, target_branch,
    )
