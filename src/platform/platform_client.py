"""
Unified REST API client for Git read operations (branch listing, default branch).

Uses platform-specific REST APIs instead of ``git ls-remote`` to avoid hangs
on authenticated repos.  Falls back to git CLI only for local repos.
"""

import logging
import os
from abc import ABC, abstractmethod
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)


class PlatformClient(ABC):
    """Abstract base for platform-specific Git read operations."""

    @abstractmethod
    def list_branches(self, repo_url: str) -> list[str]:
        """Return branch names for the given repository."""

    @abstractmethod
    def get_default_branch(self, repo_url: str) -> str:
        """Return the default branch name for the given repository."""


class GitHubClient(PlatformClient):
    """GitHub branch operations via PyGithub."""

    def __init__(self, token: str):
        self._token = token

    def _get_gh(self):
        from github import Github

        if self._token:
            return Github(self._token)
        return Github()

    @staticmethod
    def _parse_repo(repo_url: str) -> str:
        """https://github.com/owner/repo.git -> owner/repo"""
        parsed = urlparse(repo_url)
        path = parsed.path.strip("/").replace(".git", "")
        return path

    def list_branches(self, repo_url: str) -> list[str]:
        repo_name = self._parse_repo(repo_url)
        repo = self._get_gh().get_repo(repo_name)
        return sorted(b.name for b in repo.get_branches())

    def get_default_branch(self, repo_url: str) -> str:
        repo_name = self._parse_repo(repo_url)
        repo = self._get_gh().get_repo(repo_name)
        return repo.default_branch


class BitbucketCloudClient(PlatformClient):
    """Bitbucket Cloud branch operations via REST 2.0 API."""

    def __init__(self, token: str):
        self._token = token

    @staticmethod
    def _parse_repo(repo_url: str) -> tuple[str, str]:
        """https://bitbucket.org/workspace/repo.git -> (workspace, repo)"""
        parsed = urlparse(repo_url)
        path = parsed.path.strip("/").replace(".git", "")
        parts = path.split("/")
        if len(parts) >= 2:
            return parts[0], parts[1]
        raise ValueError(f"Cannot parse Bitbucket Cloud repo URL: {repo_url}")

    def _get(self, url: str, params: dict | None = None) -> requests.Response:
        resp = requests.get(
            url,
            params=params,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/json",
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp

    def list_branches(self, repo_url: str) -> list[str]:
        workspace, slug = self._parse_repo(repo_url)
        url = f"https://api.bitbucket.org/2.0/repositories/{workspace}/{slug}/refs/branches"
        branches: list[str] = []
        while url:
            data = self._get(url).json()
            for branch in data.get("values", []):
                branches.append(branch["name"])
            url = data.get("next")
        return sorted(branches)

    def get_default_branch(self, repo_url: str) -> str:
        workspace, slug = self._parse_repo(repo_url)
        url = f"https://api.bitbucket.org/2.0/repositories/{workspace}/{slug}"
        data = self._get(url).json()
        return data.get("mainbranch", {}).get("name", "main")


class BitbucketServerAdapter(PlatformClient):
    """Bitbucket Server branch operations via REST API 1.0.

    Uses plain requests.get with Bearer auth, matching the proven pattern
    for Bitbucket Server / Data Center instances.
    """

    def __init__(self, token: str, base_url: str):
        self._token = token
        self._base_url = base_url

    def list_branches(self, repo_url: str) -> list[str]:
        from src.platform.bitbucket_server import parse_bitbucket_server_url

        project_key, repo_slug = parse_bitbucket_server_url(repo_url)
        api_url = (
            f"{self._base_url}/rest/api/1.0/projects/{project_key}"
            f"/repos/{repo_slug}/branches"
        )
        headers = {"Authorization": f"Bearer {self._token}"}
        logger.debug("Fetching branches from: %s", api_url)
        try:
            response = requests.get(api_url, headers=headers)
            response.raise_for_status()
            data = response.json()
            logger.debug("API response: %s", data)
            branches = [branch["displayId"] for branch in data.get("values", [])]
            logger.debug("Fetched branches: %s", branches)
            return branches
        except requests.exceptions.RequestException as e:
            logger.error("Failed to fetch branches: %s", e)
            return []

    def get_default_branch(self, repo_url: str) -> str:
        from src.platform.bitbucket_server import parse_bitbucket_server_url

        project_key, repo_slug = parse_bitbucket_server_url(repo_url)
        api_url = (
            f"{self._base_url}/rest/api/1.0/projects/{project_key}"
            f"/repos/{repo_slug}/default-branch"
        )
        headers = {"Authorization": f"Bearer {self._token}"}
        try:
            response = requests.get(api_url, headers=headers)
            if response.status_code == 200:
                return response.json().get("displayId", "main")
        except requests.exceptions.RequestException as e:
            logger.error("Failed to fetch default branch: %s", e)
        return "main"


class LocalGitClient(PlatformClient):
    """Falls back to git CLI for local repositories."""

    def list_branches(self, repo_url: str) -> list[str]:
        from src.platform.git_ops import list_branches

        return list_branches(repo_url)

    def get_default_branch(self, repo_url: str) -> str:
        from src.platform.git_ops import get_default_branch

        return get_default_branch(repo_url)


def _is_bitbucket_cloud(repo_url: str) -> bool:
    """Return True if the URL points to Bitbucket Cloud (bitbucket.org)."""
    if not repo_url:
        return False
    parsed = urlparse(repo_url)
    hostname = (parsed.hostname or "").lower()
    return hostname == "bitbucket.org"


def _resolve_token(platform: str) -> str:
    """Resolve auth token from environment variables based on platform."""
    if platform == "github":
        return os.environ.get("GITHUB_TOKEN", "")
    if platform in ("bitbucket", "bitbucket_server"):
        return (
            os.environ.get("BITBUCKET_HTTP_ACCESS_TOKEN", "")
            or os.environ.get("BITBUCKET_APP_PASSWORD", "")
            or os.environ.get("BITBUCKET_SERVER_TOKEN", "")
        )
    return ""


def _extract_base_url(repo_url: str) -> str:
    """Extract scheme://host[:port] from a repo URL for Bitbucket Server."""
    parsed = urlparse(repo_url)
    base = f"{parsed.scheme}://{parsed.hostname}"
    if parsed.port:
        base += f":{parsed.port}"
    return base


def get_platform_client(platform: str, repo_url: str = "") -> PlatformClient:
    """Factory that returns the appropriate PlatformClient for a platform.

    Auth tokens are resolved from environment variables automatically.
    When platform is "bitbucket" but the URL is not bitbucket.org,
    auto-detects it as a Bitbucket Server instance.
    """
    # Auto-detect: platform="bitbucket" with non-bitbucket.org URL → server
    if platform == "bitbucket" and repo_url and not _is_bitbucket_cloud(repo_url):
        platform = "bitbucket_server"

    token = _resolve_token(platform)

    if platform == "github":
        return GitHubClient(token)
    if platform == "bitbucket":
        return BitbucketCloudClient(token)
    if platform == "bitbucket_server":
        base_url = _extract_base_url(repo_url)
        return BitbucketServerAdapter(token, base_url)
    # Default: local git
    return LocalGitClient()
