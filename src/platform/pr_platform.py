"""
Pull Request creation for GitHub and Bitbucket.

Authentication:
    All PR adapters accept a ``TokenSource`` (TokenProvider, str, callable, or
    None). When a refreshing provider is passed (GitHubAppTokenProvider,
    BitbucketCloudOAuthProvider), each PR API call resolves a fresh token, so
    long-lived service processes never operate on an expired credential.
"""

from abc import ABC, abstractmethod
from typing import Optional
from urllib.parse import urlparse

from src.platform.token_provider import (
    StaticTokenProvider,
    TokenProvider,
    TokenSource,
    coerce_provider,
)


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
    """GitHub PR creation via PyGithub.

    Accepts either a static token (legacy) or a ``TokenProvider``. A new
    PyGithub client is constructed per call so refreshing providers always
    use a fresh installation token.
    """

    def __init__(self, token: TokenSource):
        provider = coerce_provider(token)
        if provider is None:
            provider = StaticTokenProvider("")
        self._provider: TokenProvider = provider

    @property
    def _token(self) -> str:
        # Backwards-compat shim for callers that read ``.token`` directly.
        return self._provider.get_token()

    def _client(self):
        from github import Github

        return Github(self._provider.get_token())

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
            repo = self._client().get_repo(repo_name)
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
    """Bitbucket Cloud PR creation via REST API.

    Auth modes (in priority order):
    - ``TokenProvider`` (preferred): GitHub-App-style refreshing OAuth provider
      from ``BitbucketCloudOAuthProvider``, or any other provider that yields
      a Bearer token.
    - HTTP access token (Bearer auth): pass the token string directly.
    - App password (Basic auth): pass the password as ``token`` and the user
      as ``username`` — uses HTTP Basic via ``BasicAuthTokenProvider``.
    """

    def __init__(self, token: TokenSource, username: Optional[str] = None):
        # Username + token combo means legacy app-password (Basic auth).
        if username and username != "x-token-auth" and isinstance(token, str):
            from src.platform.token_provider import BasicAuthTokenProvider

            self._provider: TokenProvider = BasicAuthTokenProvider(username, token)
        else:
            provider = coerce_provider(token)
            if provider is None:
                provider = StaticTokenProvider("")
            self._provider = provider
        self._username = username or "x-token-auth"

    @property
    def _token(self) -> str:
        return self._provider.get_token()

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

        # The provider owns the auth scheme (Bearer for OAuth/HTTP-token,
        # Basic for legacy app-password) so we just inject the resolved header.
        resp = requests.post(
            url,
            json=payload,
            headers={
                "Authorization": self._provider.get_auth_header(),
                "Content-Type": "application/json",
            },
        )

        if resp.status_code in (200, 201):
            data = resp.json()
            links = data.get("links", {})
            return links.get("html", {}).get("href") or data.get("link", {}).get("href")
        print(f"Bitbucket PR creation failed: {resp.status_code} - {resp.text}")
        return None


def get_pr_platform(platform: str, auth_token: TokenSource, **kwargs) -> PRPlatform:
    """Factory for PR platform.

    ``auth_token`` may be a static token (legacy callers) or a
    ``TokenProvider`` instance for refreshing GitHub App / Bitbucket OAuth
    credentials.

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
