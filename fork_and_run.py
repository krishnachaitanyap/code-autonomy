#!/usr/bin/env python3
"""
Fork an upstream repo to your GitHub account, fix an issue or add a feature, and publish.
Usage: python fork_and_run.py <upstream_repo> [--issue N]
Example: python fork_and_run.py Dext3r-Morgan/beginner-friendly
         python fork_and_run.py davidmoten/maven-demo --issue 5
"""

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.activity import step, spinner, log_info, log_success, log_error


def fork_repo(upstream: str, token: str) -> str | None:
    """Fork upstream repo. Returns fork URL (https) or None on failure."""
    import requests

    url = f"https://api.github.com/repos/{upstream}/forks"
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    resp = requests.post(url, headers=headers, json={})

    if resp.status_code in (200, 201, 202):
        data = resp.json()
        return data.get("clone_url", "")
    if resp.status_code == 422:
        user = _get_username(token)
        if user:
            repo_name = upstream.split("/")[-1]
            return f"https://github.com/{user}/{repo_name}.git"
    print(f"Fork failed: {resp.status_code} - {resp.text[:300]}")
    return None


def _get_username(token: str) -> str | None:
    import requests
    resp = requests.get("https://api.github.com/user", headers={"Authorization": f"token {token}"})
    if resp.ok:
        return resp.json().get("login")
    return None


def get_default_branch(upstream: str, token: str) -> str:
    """Fetch default branch from GitHub API."""
    import requests
    url = f"https://api.github.com/repos/{upstream}"
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
    resp = requests.get(url, headers=headers)
    if resp.ok:
        return resp.json().get("default_branch", "main")
    return "main"


def main() -> int:
    parser = argparse.ArgumentParser(description="Fork repo, add feature/fix issue, publish PR")
    parser.add_argument("upstream", nargs="?", default="Dext3r-Morgan/beginner-friendly",
                       help="Upstream repo (owner/repo)")
    parser.add_argument("--issue", "-i", type=int, default=31,
                       help="GitHub issue number to reference in PR (default: 31)")
    parser.add_argument("--run-tests", action="store_true",
                       help="Run tests (default: skip for fork - repo may not have test suite)")
    parser.add_argument("--changes", "-c", default="changes.txt",
                       help="Path to changes.txt (e.g., examples/changes/changes_java.txt for Java)")
    parser.add_argument("--reference-pr", "-r",
                       help="GitHub PR URL to use as template for repetitive changes")
    parser.add_argument("--agent", "-a", action="store_true",
                       help="Use agent mode: AI explores codebase with read_file, grep, list_dir")
    parser.add_argument("--testing-strategy", "-t", choices=["bdd", "contract", "integration", "unit", "e2e", "soap", "auto"],
                       help="Java testing strategy for generated tests")
    args = parser.parse_args()

    upstream = args.upstream
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        try:
            from src.config_loader import load_config
            cfg = load_config()
            token = cfg.get("github_config", {}).get("auth_token", "")
        except Exception:
            pass
    if not token or (token.startswith("<") and token.endswith(">")):
        log_error("Set GITHUB_TOKEN or auth_token in config.ini [github_config]")
        return 1

    with spinner("Forking repository"):
        fork_url = fork_repo(upstream, token)
    if not fork_url:
        return 1

    log_success(f"Fork created: {fork_url}")

    with step("Getting default branch"):
        base_branch = get_default_branch(upstream, token)
    log_info(f"Base branch: {base_branch}")

    # Update config.ini
    config_path = Path(__file__).parent / "config.ini"
    config = config_path.read_text()
    config = re.sub(r'repo_url\s*=\s*.*', f'repo_url = {fork_url}', config)
    config = re.sub(r'base_branch\s*=\s*.*', f'base_branch = {base_branch}', config)
    config_path.write_text(config)
    log_success("Updated config.ini")

    # Run main - pass issue and reference PR
    os.environ["AUTO_PR_ISSUE"] = str(args.issue) if args.issue else ""
    sys.argv = [sys.argv[0], "--changes", args.changes]
    if not args.run_tests:
        sys.argv.append("--skip-tests")
    if args.reference_pr:
        sys.argv.extend(["--reference-pr", args.reference_pr])
    if args.agent:
        sys.argv.append("--agent")
    if getattr(args, "testing_strategy", None):
        sys.argv.extend(["--testing-strategy", args.testing_strategy])
    import main as main_module
    return main_module.main()


if __name__ == "__main__":
    sys.exit(main())
