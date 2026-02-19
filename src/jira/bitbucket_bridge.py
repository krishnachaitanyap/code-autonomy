"""
Orchestration bridge: JIRA stories ↔ Bitbucket Server git workflow.

Handles cloning, branching, committing, pushing, PR creation, and cleanup
for each JIRA story processed by the agent.

Uses only subprocess git commands + requests (no GitPython dependency).
"""

import logging
import re
import shutil
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


def clone_and_prepare_branch(
    clone_url: str,
    branch_name: str,
    from_branch: str = "main",
    target_dir: Optional[str] = None,
    auth_token: Optional[str] = None,
    protocol: str = "ssh",
) -> Optional[str]:
    """Clone a repository and prepare a feature branch in one step.

    1. Clone *clone_url* into *target_dir* (or a temp directory).
    2. Checkout *from_branch* (fetch if needed).
    3. Create *branch_name* from *from_branch*.

    Returns the path to the cloned repo directory, or None on failure.
    """
    import tempfile

    temp_dir = target_dir or tempfile.mkdtemp()
    target = Path(temp_dir)

    try:
        if target.exists() and any(target.iterdir()):
            # Already cloned — reuse
            logger.info("Repo already exists at %s, reusing", temp_dir)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            cmd = ["git"]
            if protocol == "https" and auth_token:
                cmd += ["-c", f"http.extraHeader=Authorization: Bearer {auth_token}"]
            cmd += ["clone", clone_url, temp_dir]

            logger.info("Cloning %s (protocol=%s)", clone_url, protocol)
            subprocess.check_call(cmd, timeout=600)

        # Checkout the target branch (fetch if not available locally)
        try:
            subprocess.check_call(["git", "checkout", branch_name], cwd=temp_dir)
        except subprocess.CalledProcessError:
            cmd = ["git", "fetch"]
            if protocol == "https" and auth_token:
                cmd = ["git", "-c", f"http.extraHeader=Authorization: Bearer {auth_token}", "fetch"]
            subprocess.check_call(cmd, cwd=temp_dir)
            subprocess.check_call(
                ["git", "checkout", "-b", branch_name, f"origin/{from_branch}"],
                cwd=temp_dir,
            )

        logger.info("Prepared branch %s from %s in %s", branch_name, from_branch, temp_dir)
        return temp_dir

    except Exception as e:
        logger.error("Error preparing branch: %s", e)
        shutil.rmtree(temp_dir, ignore_errors=True)
        return None


def commit_and_push(
    repo_dir: str,
    branch_name: str,
    commit_msg: str,
    auth_token: Optional[str] = None,
) -> bool:
    """Stage all changes, commit, and push.

    Returns True on success, False on failure.
    """
    try:
        # Check if there are changes to commit
        status = _git(repo_dir, "status", "--porcelain")
        if not status.stdout.strip():
            logger.info("No changes to commit")
            return False

        # Stage all changes
        _git(repo_dir, "add", "-A")

        # Configure author
        _git(repo_dir, "config", "user.name", "Auto Coder")
        _git(repo_dir, "config", "user.email", "auto@coder.local")

        # Commit
        r = _git(repo_dir, "commit", "-m", commit_msg)
        if r.returncode != 0:
            logger.error("Commit failed: %s", r.stderr.strip())
            return False

        # Push
        r = _git(repo_dir, "push", "origin", branch_name, token=auth_token)
        if r.returncode != 0:
            logger.error("Push failed: %s", r.stderr.strip())
            return False

        logger.info("Pushed to origin/%s", branch_name)
        return True
    except Exception as e:
        logger.error("Commit/push failed: %s", e)
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
