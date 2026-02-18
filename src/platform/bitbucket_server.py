"""
Bitbucket Server / Data Center REST API 1.0 client and PR platform adapter.

Supports:
- Branch listing and default branch detection
- Pull request creation with fromRef/toRef (Server 1.0 format)
- PR commenting
- Bearer token authentication
- SSH and HTTPS URL parsing for project_key/repo_slug extraction
"""

import re
from typing import Optional
from urllib.parse import urlparse

import requests

from src.platform.pr_platform import PRPlatform


class BitbucketServerClient:
    """Client for Bitbucket Server / Data Center REST API 1.0."""

    def __init__(self, base_url: str, token: str, verify_ssl: bool = False):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.verify_ssl = verify_ssl
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        })
        self._session.verify = verify_ssl

    def _api_url(self, project_key: str, repo_slug: str, path: str = "") -> str:
        """Build a REST API 1.0 URL for the given project/repo."""
        return (
            f"{self.base_url}/rest/api/1.0/projects/{project_key}"
            f"/repos/{repo_slug}{path}"
        )

    def get_branches(self, project_key: str, repo_slug: str) -> list[dict]:
        """List branches for a repository."""
        url = self._api_url(project_key, repo_slug, "/branches")
        resp = self._session.get(url, params={"limit": 100})
        resp.raise_for_status()
        return resp.json().get("values", [])

    def get_default_branch(self, project_key: str, repo_slug: str) -> str:
        """Get the default branch name for a repository."""
        url = self._api_url(project_key, repo_slug, "/default-branch")
        resp = self._session.get(url)
        if resp.status_code == 200:
            return resp.json().get("displayId", "main")
        return "main"

    def create_pull_request(
        self,
        project_key: str,
        repo_slug: str,
        title: str,
        description: str,
        source_branch: str,
        target_branch: str,
    ) -> Optional[str]:
        """Create a pull request and return the PR URL (or None on failure)."""
        url = self._api_url(project_key, repo_slug, "/pull-requests")
        payload = {
            "title": title,
            "description": description,
            "fromRef": {
                "id": f"refs/heads/{source_branch}",
                "repository": {
                    "slug": repo_slug,
                    "project": {"key": project_key},
                },
            },
            "toRef": {
                "id": f"refs/heads/{target_branch}",
                "repository": {
                    "slug": repo_slug,
                    "project": {"key": project_key},
                },
            },
        }
        resp = self._session.post(url, json=payload)
        if resp.status_code in (200, 201):
            data = resp.json()
            pr_id = data.get("id")
            # Build browsable URL
            pr_url = (
                f"{self.base_url}/projects/{project_key}/repos/{repo_slug}"
                f"/pull-requests/{pr_id}"
            )
            return pr_url
        print(f"Bitbucket Server PR creation failed: {resp.status_code} - {resp.text}")
        return None

    def add_pr_comment(
        self, project_key: str, repo_slug: str, pr_id: int, comment: str
    ) -> bool:
        """Add a comment to an existing pull request."""
        url = self._api_url(
            project_key, repo_slug, f"/pull-requests/{pr_id}/comments"
        )
        payload = {"text": comment}
        resp = self._session.post(url, json=payload)
        return resp.status_code in (200, 201)


class BitbucketServerPR(PRPlatform):
    """PRPlatform adapter for Bitbucket Server (wraps BitbucketServerClient)."""

    def __init__(self, base_url: str, token: str, verify_ssl: bool = False):
        self._client = BitbucketServerClient(base_url, token, verify_ssl)
        self._base_url = base_url

    def _parse_repo(self, repo_url: str) -> tuple[str, str]:
        """Extract (project_key, repo_slug) from SSH or HTTPS clone URL.

        Supports:
          SSH:   ssh://git@host:7999/PROJECT/repo.git
          SSH:   git@host:7999/PROJECT/repo.git
          HTTPS: https://host/scm/PROJECT/repo.git
          HTTPS: https://host/projects/PROJECT/repos/repo/browse
        """
        # SSH: ssh://git@host:port/PROJECT/repo.git or git@host:PORT/PROJECT/repo.git
        ssh_match = re.search(r"[:/](\w+)/([\w\-]+?)(?:\.git)?$", repo_url)
        if ssh_match and ("git@" in repo_url or repo_url.startswith("ssh://")):
            return ssh_match.group(1), ssh_match.group(2)

        # HTTPS /scm/ pattern: https://host/scm/PROJECT/repo.git
        scm_match = re.search(r"/scm/(\w+)/([\w\-]+?)(?:\.git)?$", repo_url)
        if scm_match:
            return scm_match.group(1), scm_match.group(2)

        # HTTPS /projects/ pattern: https://host/projects/PROJECT/repos/REPO
        proj_match = re.search(
            r"/projects/(\w+)/repos/([\w\-]+)", repo_url
        )
        if proj_match:
            return proj_match.group(1), proj_match.group(2)

        raise ValueError(f"Cannot parse Bitbucket Server repo URL: {repo_url}")

    def create_pull_request(
        self,
        repo_url: str,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
    ) -> Optional[str]:
        project_key, repo_slug = self._parse_repo(repo_url)
        return self._client.create_pull_request(
            project_key, repo_slug, title, description, source_branch, target_branch,
        )
