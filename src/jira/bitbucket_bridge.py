"""
Orchestration bridge: JIRA stories ↔ Bitbucket Server git workflow.

Handles cloning, branching, committing, pushing, PR creation, and cleanup
for each JIRA story processed by the agent.
"""

import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from git import Repo
from git.exc import GitCommandError

from src.platform.git_ops import clone_repo, clone_repo_ssh, stage_and_commit, push_branch
from src.platform.bitbucket_server import BitbucketServerClient


def clone_bitbucket_repo(
    clone_url: str,
    target_dir: str,
    branch: str = "main",
    auth_token: Optional[str] = None,
    protocol: str = "ssh",
) -> Repo:
    """Clone a Bitbucket Server repository.

    Uses SSH clone (key-based auth) when *protocol* is ``'ssh'``, otherwise
    uses HTTPS with Bearer token via ``http.extraHeader`` (bypasses credential
    helpers like wincred/manager).
    """
    target = Path(target_dir)
    if target.exists() and any(target.iterdir()):
        # Already cloned — just open it
        return Repo(str(target))

    target.parent.mkdir(parents=True, exist_ok=True)

    if protocol == "ssh":
        return clone_repo_ssh(clone_url, target_dir, branch=branch)
    else:
        return _clone_https_bearer(clone_url, target_dir, branch=branch, token=auth_token)


def _clone_https_bearer(
    https_url: str,
    target_dir: str,
    branch: str = "main",
    token: Optional[str] = None,
) -> Repo:
    """Clone via HTTPS using Bearer token in http.extraHeader.

    This avoids URL-embedded credentials which are overridden by system
    credential helpers (wincred, osxkeychain, manager) on many machines.
    """
    target = Path(target_dir)
    target.parent.mkdir(parents=True, exist_ok=True)

    cmd = ["git"]
    if token:
        cmd += ["-c", f"http.extraHeader=Authorization: Bearer {token}"]
    cmd += ["clone", "--branch", branch, "--depth", "1", https_url, str(target)]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise GitCommandError(cmd, result.returncode, result.stderr)
    return Repo(str(target))


def prepare_story_branch(
    repo: Repo,
    story_key: str,
    base_branch: str,
    auth_token: Optional[str] = None,
) -> str:
    """Create a feature branch for a story from the base branch.

    Returns the branch name (``feature/auto-{STORY_KEY}-{timestamp}``).
    """
    # Ensure we're on the base branch first
    repo.git.checkout(base_branch)

    # Pull with Bearer token if provided (bypasses credential helpers)
    if auth_token:
        cmd = [
            "git", "-c", f"http.extraHeader=Authorization: Bearer {auth_token}",
            "pull", "origin", base_branch,
        ]
        subprocess.run(
            cmd, capture_output=True, text=True, timeout=120,
            cwd=str(repo.working_dir),
        )
    else:
        repo.git.pull("origin", base_branch)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safe_key = re.sub(r"[^\w\-]", "-", story_key.strip()).strip("-")
    branch_name = f"feature/auto-{safe_key}-{timestamp}"
    repo.git.checkout("-b", branch_name)
    return branch_name


def commit_and_push_story(
    repo: Repo,
    branch_name: str,
    story_key: str,
    summary: str,
    files_changed: list[str],
    auth_token: Optional[str] = None,
) -> bool:
    """Stage all changes, commit, and push the story branch.

    When *auth_token* is provided, uses Bearer token header for the push
    (bypasses credential helpers).  Returns True on success, False on failure.
    """
    try:
        if not (repo.is_dirty() or repo.untracked_files):
            return False  # Nothing to commit

        commit_msg = f"{story_key}: {summary}"
        stage_and_commit(repo, commit_msg)

        if auth_token:
            # Push with Bearer token header (bypasses wincred/osxkeychain)
            cmd = [
                "git", "-c", f"http.extraHeader=Authorization: Bearer {auth_token}",
                "push", "origin", branch_name,
            ]
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120,
                cwd=str(repo.working_dir),
            )
            if result.returncode != 0:
                raise GitCommandError(cmd, result.returncode, result.stderr)
        else:
            push_branch(repo, branch_name)
        return True
    except (GitCommandError, Exception) as e:
        print(f"Commit/push failed for {story_key}: {e}")
        return False


def discard_story_changes(repo: Repo, base_branch: str) -> None:
    """Discard all uncommitted changes and return to the base branch."""
    try:
        repo.git.checkout(base_branch)
        repo.git.clean("-fd")
        repo.git.reset("--hard")
    except GitCommandError as e:
        print(f"Warning: discard_story_changes failed: {e}")


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
    # Truncate title to a reasonable length
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
