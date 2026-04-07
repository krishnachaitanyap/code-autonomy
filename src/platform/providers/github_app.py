"""
GitHub App installation token provider.

GitHub Apps authenticate by signing a short-lived JWT with the App's RSA
private key, then exchanging that JWT for a 1-hour installation access token
scoped to a specific installation (org or user).

Reference:
  https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-an-installation-access-token-for-a-github-app

This provider caches the installation token and refreshes it ~5 minutes before
expiry. It is thread-safe.
"""

from __future__ import annotations

import logging
import time
from threading import Lock
from typing import Optional

from src.platform.token_provider import TokenProvider

logger = logging.getLogger(__name__)


# Hard-coded API base for github.com. For GitHub Enterprise Server, override
# via the ``api_base_url`` constructor argument (e.g. https://ghe.example.com/api/v3).
_DEFAULT_API_BASE = "https://api.github.com"

# Refresh the cached token this many seconds before its actual expiry, so that
# in-flight requests don't race a 401.
_REFRESH_SAFETY_MARGIN_SECONDS = 300  # 5 minutes


class GitHubAppTokenProvider(TokenProvider):
    """Generates and caches GitHub App installation tokens.

    Args:
        app_id: The numeric GitHub App ID (from the App settings page).
        installation_id: The numeric installation ID for the org/user where
            the App is installed. Find via ``GET /app/installations``.
        private_key_pem: The PEM-encoded RSA private key generated for the
            App. Pass the file *contents*, not a path.
        api_base_url: Override for GitHub Enterprise Server. Defaults to
            ``https://api.github.com``.
    """

    def __init__(
        self,
        app_id: str,
        installation_id: str,
        private_key_pem: str,
        api_base_url: Optional[str] = None,
    ):
        if not app_id:
            raise ValueError("GitHubAppTokenProvider: app_id is required")
        if not installation_id:
            raise ValueError("GitHubAppTokenProvider: installation_id is required")
        if not private_key_pem:
            raise ValueError("GitHubAppTokenProvider: private_key_pem is required")

        self._app_id = str(app_id)
        self._installation_id = str(installation_id)
        self._private_key = private_key_pem
        self._api_base = (api_base_url or _DEFAULT_API_BASE).rstrip("/")

        self._cached_token: Optional[str] = None
        self._expires_at: float = 0.0
        self._lock = Lock()

    # ------------------------------------------------------------------ #
    # JWT generation                                                     #
    # ------------------------------------------------------------------ #
    def _generate_jwt(self) -> str:
        """Sign a short-lived JWT (max 10 minutes) with the App's private key."""
        try:
            import jwt  # PyJWT — requires the [crypto] extra for RS256
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "PyJWT with cryptography extras is required for GitHub App auth. "
                "Install with: pip install 'pyjwt[crypto]>=2.8.0'"
            ) from exc

        now = int(time.time())
        payload = {
            # iat is back-dated by 60s to tolerate clock skew between us and GitHub.
            "iat": now - 60,
            # exp must be <= 10 minutes in the future per GitHub's spec.
            "exp": now + 540,
            "iss": self._app_id,
        }
        return jwt.encode(payload, self._private_key, algorithm="RS256")

    # ------------------------------------------------------------------ #
    # Installation token exchange                                        #
    # ------------------------------------------------------------------ #
    def _fetch_installation_token(self) -> tuple[str, float]:
        """Exchange the App JWT for a 1-hour installation token."""
        import requests

        jwt_token = self._generate_jwt()
        url = (
            f"{self._api_base}/app/installations/"
            f"{self._installation_id}/access_tokens"
        )
        resp = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {jwt_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=15,
        )
        if resp.status_code != 201:
            raise RuntimeError(
                f"GitHub App token exchange failed "
                f"(status={resp.status_code}): {resp.text}"
            )
        data = resp.json()
        token = data["token"]
        # Use the server-provided expiry if present; otherwise fall back to ~1 hour.
        # Format: "2026-04-07T12:00:00Z"
        expires_in = 3600
        if "expires_at" in data:
            try:
                from datetime import datetime, timezone
                expires_dt = datetime.fromisoformat(
                    data["expires_at"].replace("Z", "+00:00")
                )
                expires_in = max(
                    60, int(expires_dt.timestamp() - time.time())
                )
            except Exception:  # pragma: no cover — fall back silently
                pass
        return token, time.time() + expires_in

    # ------------------------------------------------------------------ #
    # TokenProvider interface                                            #
    # ------------------------------------------------------------------ #
    def get_token(self) -> str:
        with self._lock:
            now = time.time()
            if (
                self._cached_token
                and now < self._expires_at - _REFRESH_SAFETY_MARGIN_SECONDS
            ):
                return self._cached_token

            logger.info(
                "Refreshing GitHub App installation token "
                "(app_id=%s, installation_id=%s)",
                self._app_id,
                self._installation_id,
            )
            token, expires_at = self._fetch_installation_token()
            self._cached_token = token
            self._expires_at = expires_at
            return token

    def get_auth_header(self) -> str:
        # GitHub installation tokens are used as Bearer tokens, both for the
        # REST API and as the password in HTTPS git clone URLs.
        return f"Bearer {self.get_token()}"
