"""
Token providers for VCS authentication.

Provides a uniform interface for git/PR clients to obtain auth credentials
without caring whether the underlying source is a static PAT, a GitHub App
installation token, an OAuth client-credentials grant, or a Bitbucket Server
HTTP access token.

Design goals:
- Single interface (TokenProvider) consumed by git_ops.py and pr_platform.py
- Providers may cache and refresh tokens internally
- Auth scheme (Bearer / Basic) is owned by the provider, not the caller
- Backwards compatible: a plain ``str`` is still accepted via ``coerce_provider``
"""

from __future__ import annotations

import base64
from abc import ABC, abstractmethod
from typing import Callable, Optional, Union


class TokenProvider(ABC):
    """Returns a fresh auth token. Implementations may cache and refresh."""

    @abstractmethod
    def get_token(self) -> str:
        """Return a valid (non-expired) token."""

    def get_auth_header(self) -> str:
        """Return the value for the HTTP ``Authorization`` header.

        Defaults to ``Bearer <token>``. Override for Basic auth or other
        schemes.
        """
        return f"Bearer {self.get_token()}"

    def __call__(self) -> str:
        # Convenience: providers can be passed where a callable[[], str] is expected.
        return self.get_token()


class StaticTokenProvider(TokenProvider):
    """Wraps a static, pre-issued token (PAT, HTTP access token, etc.).

    No refresh logic — the token is returned verbatim. Used as the default
    fallback when no "app-style" auth is configured.
    """

    def __init__(self, token: str):
        if token is None:
            token = ""
        self._token = token

    def get_token(self) -> str:
        return self._token


class BasicAuthTokenProvider(TokenProvider):
    """HTTP Basic auth provider for legacy username + password/app-password flows.

    Used by Bitbucket Cloud app passwords. The HTTP header value is
    ``Basic base64(username:password)``.
    """

    def __init__(self, username: str, password: str):
        self._username = username
        self._password = password

    def get_token(self) -> str:
        # For Basic auth there is no "token" — return the password so callers
        # that only need a credential string still work.
        return self._password

    def get_auth_header(self) -> str:
        encoded = base64.b64encode(
            f"{self._username}:{self._password}".encode("utf-8")
        ).decode("ascii")
        return f"Basic {encoded}"


# A "token source" is anything we can resolve into a TokenProvider:
# - a TokenProvider instance (preferred)
# - a plain string (legacy callers)
# - a zero-arg callable returning a string
# - None (no auth)
TokenSource = Union[TokenProvider, str, Callable[[], str], None]


def coerce_provider(source: TokenSource) -> Optional[TokenProvider]:
    """Normalize any supported token source into a ``TokenProvider``.

    Returns ``None`` if the source is ``None`` or an empty string, so callers
    can use ``if provider:`` to decide whether to inject auth headers.
    """
    if source is None:
        return None
    if isinstance(source, TokenProvider):
        return source
    if isinstance(source, str):
        return StaticTokenProvider(source) if source else None
    if callable(source):
        # Wrap the callable in a thin provider so the contract is uniform.
        class _CallableProvider(TokenProvider):
            def get_token(self) -> str:
                return source() or ""

        return _CallableProvider()
    raise TypeError(f"Unsupported token source type: {type(source).__name__}")
