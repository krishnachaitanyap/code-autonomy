"""
Bitbucket Server / Data Center REST API 1.0 client and PR platform adapter.

Supports:
- Branch listing and default branch detection
- Pull request creation with fromRef/toRef (Server 1.0 format)
- PR commenting
- Bearer token authentication
- SSH and HTTPS URL parsing for project_key/repo_slug extraction
"""

import logging
import re
from typing import Optional
from urllib.parse import urlparse

import requests

from src.platform.pr_platform import PRPlatform
from src.platform.token_provider import (
    StaticTokenProvider,
    TokenProvider,
    TokenSource,
    coerce_provider,
)

logger = logging.getLogger(__name__)


class BitbucketServerClient:
    """Client for Bitbucket Server / Data Center REST API 1.0."""

    def __init__(self, base_url: str, token: TokenSource, verify_ssl: bool = False):
        # Extract just scheme://host:port (strip any trailing path)
        parsed = urlparse(base_url.rstrip("/"))
        self.base_url = f"{parsed.scheme}://{parsed.hostname}"
        if parsed.port:
            self.base_url += f":{parsed.port}"
        provider = coerce_provider(token)
        if provider is None:
            provider = StaticTokenProvider("")
        self._provider: TokenProvider = provider
        self.verify_ssl = verify_ssl
        self._session = requests.Session()
        self._session.headers.update({"Content-Type": "application/json"})
        self._session.verify = verify_ssl

    @property
    def token(self) -> str:
        # Backwards-compat for any caller reading ``.token`` directly.
        return self._provider.get_token()

    def _auth_headers(self) -> dict:
        """Resolve the Authorization header for a single request.

        Called per-request so refreshing providers always hand out a fresh
        token (no auth cached on the long-lived ``requests.Session``).
        """
        return {"Authorization": self._provider.get_auth_header()}

    def _api_url(self, project_key: str, repo_slug: str, path: str = "") -> str:
        """Build a REST API 1.0 URL for the given project/repo.

        Example: https://host/rest/api/1.0/projects/PROJ/repos/my-repo/branches
        """
        return (
            f"{self.base_url}/rest/api/1.0/projects/{project_key}"
            f"/repos/{repo_slug}{path}"
        )

    def get_branches(self, project_key: str, repo_slug: str) -> list[dict]:
        """List branches for a repository."""
        url = self._api_url(project_key, repo_slug, "/branches")
        logger.debug("Fetching branches from: %s", url)
        resp = self._session.get(url, params={"limit": 100}, headers=self._auth_headers())
        resp.raise_for_status()
        data = resp.json()
        branches = [b["displayId"] for b in data.get("values", [])]
        logger.debug("Fetched branches: %s", branches)
        return data.get("values", [])

    def get_default_branch(self, project_key: str, repo_slug: str) -> str:
        """Get the default branch name for a repository."""
        url = self._api_url(project_key, repo_slug, "/default-branch")
        resp = self._session.get(url, headers=self._auth_headers())
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
        logger.debug("Creating PR at: %s", url)
        logger.debug("PR payload: %s", payload)
        resp = self._session.post(url, json=payload, headers=self._auth_headers())
        if resp.status_code in (200, 201):
            data = resp.json()
            pr_id = data.get("id")
            # Build browsable URL
            pr_url = (
                f"{self.base_url}/projects/{project_key}/repos/{repo_slug}"
                f"/pull-requests/{pr_id}"
            )
            logger.info("PR created: %s", pr_url)
            return pr_url
        logger.error("PR creation failed: %s - %s", resp.status_code, resp.text)
        return None

    def add_pr_comment(
        self, project_key: str, repo_slug: str, pr_id: int, comment: str
    ) -> bool:
        """Add a comment to an existing pull request."""
        url = self._api_url(
            project_key, repo_slug, f"/pull-requests/{pr_id}/comments"
        )
        payload = {"text": comment}
        resp = self._session.post(url, json=payload, headers=self._auth_headers())
        return resp.status_code in (200, 201)


def parse_bitbucket_server_url(repo_url: str) -> tuple[str, str]:
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


class BitbucketServerPR(PRPlatform):
    """PRPlatform adapter for Bitbucket Server (wraps BitbucketServerClient).

    ``token`` accepts a static token (legacy) or a ``TokenProvider``. Bitbucket
    Server / Data Center has no GitHub-App equivalent — in practice this will
    be a long-lived HTTP access token, but the provider abstraction lets us
    plug in a future rotation mechanism without touching callers.
    """

    def __init__(self, base_url: str, token: TokenSource, verify_ssl: bool = False):
        self._client = BitbucketServerClient(base_url, token, verify_ssl)
        self._base_url = base_url

    def _parse_repo(self, repo_url: str) -> tuple[str, str]:
        return parse_bitbucket_server_url(repo_url)

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
