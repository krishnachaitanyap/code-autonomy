"""
Pull Request creation for GitHub and Bitbucket.
"""

from abc import ABC, abstractmethod
from typing import Optional
from urllib.parse import urlparse


class PRPlatform(ABC):
    """Abstract base for PR creation."""

    @abstractmethod
    def create_pull_request(
        self,
        repo_url: str,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
    ) -> Optional[str]:
        """Create PR and return URL."""
        pass


class GitHubPR(PRPlatform):
    """GitHub PR creation via PyGithub."""

    def __init__(self, token: str):
        from github import Github

        self._gh = Github(token)
        self._token = token

    def _parse_repo(self, repo_url: str) -> str:
        # https://github.com/owner/repo.git -> owner/repo
        parsed = urlparse(repo_url)
        path = parsed.path.strip("/").replace(".git", "")
        return path

    def create_pull_request(
        self,
        repo_url: str,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
    ) -> Optional[str]:
        try:
            repo_name = self._parse_repo(repo_url)
            repo = self._gh.get_repo(repo_name)
            pr = repo.create_pull(
                title=title,
                body=description,
                head=source_branch,
                base=target_branch,
            )
            return pr.html_url
        except Exception as e:
            print(f"GitHub PR creation failed: {e}")
            return None


class BitbucketPR(PRPlatform):
    """Bitbucket PR creation via REST API.

    Supports two auth modes:
    - HTTP access token (Bearer auth) — preferred, set via BITBUCKET_HTTP_ACCESS_TOKEN
    - App password (Basic auth) — legacy, set via BITBUCKET_APP_PASSWORD with username
    """

    def __init__(self, token: str, username: Optional[str] = None):
        self._token = token
        self._username = username or "x-token-auth"
        # HTTP access tokens are typically longer than app passwords
        # and don't require a username for API calls (use Bearer auth)
        self._use_bearer = not username or username == "x-token-auth"

    def _parse_repo(self, repo_url: str) -> tuple[str, str]:
        # https://bitbucket.org/workspace/repo.git -> workspace, repo
        parsed = urlparse(repo_url)
        path = parsed.path.strip("/").replace(".git", "")
        parts = path.split("/")
        if len(parts) >= 2:
            return parts[0], parts[1]
        raise ValueError(f"Cannot parse Bitbucket repo URL: {repo_url}")

    def create_pull_request(
        self,
        repo_url: str,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str,
    ) -> Optional[str]:
        import requests

        workspace, repo_slug = self._parse_repo(repo_url)
        url = f"https://api.bitbucket.org/2.0/repositories/{workspace}/{repo_slug}/pullrequests"

        payload = {
            "title": title,
            "description": description,
            "source": {"branch": {"name": source_branch}},
            "destination": {"branch": {"name": target_branch}},
        }

        if self._use_bearer:
            resp = requests.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type": "application/json",
                },
            )
        else:
            resp = requests.post(
                url,
                json=payload,
                auth=(self._username, self._token),
                headers={"Content-Type": "application/json"},
            )

        if resp.status_code in (200, 201):
            data = resp.json()
            links = data.get("links", {})
            return links.get("html", {}).get("href") or data.get("link", {}).get("href")
        print(f"Bitbucket PR creation failed: {resp.status_code} - {resp.text}")
        return None


def get_pr_platform(platform: str, auth_token: str, **kwargs) -> PRPlatform:
    """Factory for PR platform.

    For ``bitbucket_server``, pass ``base_url`` and optionally ``verify_ssl``
    via *kwargs*.
    """
    if platform == "github":
        return GitHubPR(auth_token)
    if platform == "bitbucket":
        return BitbucketPR(auth_token)
    if platform == "bitbucket_server":
        from src.platform.bitbucket_server import BitbucketServerPR
        base_url = kwargs.get("base_url", "")
        verify_ssl = kwargs.get("verify_ssl", False)
        return BitbucketServerPR(base_url, auth_token, verify_ssl)
    raise ValueError(f"Unsupported platform: {platform}")
