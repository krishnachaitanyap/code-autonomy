"""
Bitbucket Cloud OAuth 2.0 token provider (client credentials grant).

Bitbucket Cloud's closest analogue to a GitHub App is an "OAuth Consumer"
configured at the workspace level. Using the *client credentials* grant, the
backend exchanges its consumer key + secret for a 2-hour access token that
can be used as a Bearer credential for both the REST API and HTTPS clones.

Reference:
  https://support.atlassian.com/bitbucket-cloud/docs/use-oauth-on-bitbucket-cloud/

This provider caches the access token and refreshes ~5 minutes before expiry.
It is thread-safe.
"""

from __future__ import annotations

import logging
import time
from threading import Lock
from typing import Optional

from src.platform.token_provider import TokenProvider

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://bitbucket.org/site/oauth2/access_token"
_REFRESH_SAFETY_MARGIN_SECONDS = 300


class BitbucketCloudOAuthProvider(TokenProvider):
    """Bitbucket Cloud OAuth 2.0 client-credentials token provider.

    Args:
        client_key: The OAuth Consumer's "Key" (from workspace settings).
        client_secret: The OAuth Consumer's "Secret".

    Notes:
        - Tokens last 2 hours by default and are refreshed automatically.
        - The consumer must be configured with at least these scopes:
          ``repository:write``, ``pullrequest:write``.
        - This grant authenticates as the *consumer*, not as a user, so all
          actions appear under the consumer's identity. Use commit author
          override (``git config user.email``) for human attribution.
    """

    def __init__(self, client_key: str, client_secret: str):
        if not client_key:
            raise ValueError("BitbucketCloudOAuthProvider: client_key is required")
        if not client_secret:
            raise ValueError("BitbucketCloudOAuthProvider: client_secret is required")
        self._key = client_key
        self._secret = client_secret
        self._cached_token: Optional[str] = None
        self._expires_at: float = 0.0
        self._lock = Lock()

    def _fetch_token(self) -> tuple[str, float]:
        import requests

        resp = requests.post(
            _TOKEN_URL,
            data={"grant_type": "client_credentials"},
            auth=(self._key, self._secret),
            timeout=15,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Bitbucket Cloud OAuth token exchange failed "
                f"(status={resp.status_code}): {resp.text}"
            )
        data = resp.json()
        token = data["access_token"]
        expires_in = int(data.get("expires_in", 7200))
        return token, time.time() + expires_in

    def get_token(self) -> str:
        with self._lock:
            now = time.time()
            if (
                self._cached_token
                and now < self._expires_at - _REFRESH_SAFETY_MARGIN_SECONDS
            ):
                return self._cached_token

            logger.info("Refreshing Bitbucket Cloud OAuth access token")
            token, expires_at = self._fetch_token()
            self._cached_token = token
            self._expires_at = expires_at
            return token
