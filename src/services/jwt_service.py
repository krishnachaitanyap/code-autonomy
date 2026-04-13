"""
JWT helper module — extracted so the auth middleware can encode/decode
internal session tokens without importing the full :class:`AuthService`.

Used by both auth providers:
- ``provider = oidc``  → AuthService.handle_callback issues a JWT here
- ``provider = adfs``  → AuthService.create_internal_jwt issues a JWT here
- middleware in src/api/app.py validates Bearer tokens via decode_access_token
- WebSocket endpoint in src/api/routes/sessions.py validates ?token=

Algorithm: HS256 with the ``[auth].session_secret`` config value (falls back
to ``AUTH_SESSION_SECRET`` env var, then a random key generated at process
start — random keys mean sessions don't survive restarts, so production
deployments MUST set the secret explicitly).
"""

from __future__ import annotations

import logging
import os
import secrets
import time
from typing import Optional

logger = logging.getLogger(__name__)

# python-jose is the same JWT library used by AuthService. We import it
# lazily so dev installs without OIDC enabled don't pay the import cost.
try:
    from jose import jwt as _jose_jwt
    from jose import JWTError as _JoseJWTError
except ImportError:  # pragma: no cover
    _jose_jwt = None  # type: ignore[assignment]
    _JoseJWTError = Exception  # type: ignore[assignment,misc]


# Process-wide cached secret. Resolved on first use from config or env, so the
# auth middleware doesn't need to plumb the config dict through every call.
_cached_secret: Optional[str] = None


def _resolve_secret() -> str:
    """Return the HS256 signing secret, caching it after the first lookup.

    Resolution order:
      1. Process-wide cached value (set by ``set_secret`` at startup)
      2. ``AUTH_SESSION_SECRET`` environment variable
      3. A random 64-char hex string (dev fallback — sessions are
         invalidated on every restart)
    """
    global _cached_secret
    if _cached_secret:
        return _cached_secret

    env_secret = os.environ.get("AUTH_SESSION_SECRET", "").strip()
    if env_secret:
        _cached_secret = env_secret
        return _cached_secret

    logger.warning(
        "No AUTH_SESSION_SECRET configured — generating a random session "
        "secret. JWTs will be invalidated on every server restart. Set "
        "AUTH_SESSION_SECRET (or [auth].session_secret in config.ini) for "
        "stable sessions."
    )
    _cached_secret = secrets.token_hex(32)
    return _cached_secret


def set_secret(secret: str) -> None:
    """Override the cached HS256 secret.

    Called by the application's startup code (lifespan handler in
    ``src/api/app.py``) so that values from ``[auth].session_secret`` in
    ``config.ini`` take precedence over the env-var fallback.
    """
    global _cached_secret
    if secret:
        _cached_secret = secret


def create_access_token(data: dict, expires_in: int = 3600) -> str:
    """Sign a short-lived HS256 JWT carrying the given claims.

    Args:
        data: Custom claims (must include ``sub`` for downstream consumers).
        expires_in: TTL in seconds. Defaults to 1 hour, matching ADFS's
            default ``expires_in``.

    Raises:
        RuntimeError: if python-jose is not installed.
    """
    if _jose_jwt is None:
        raise RuntimeError(
            "python-jose is required for JWT auth. "
            "Install with: pip install 'python-jose[cryptography]>=3.3.0'"
        )
    now = int(time.time())
    payload = {
        **data,
        "iat": now,
        "exp": now + max(60, int(expires_in)),
    }
    return _jose_jwt.encode(payload, _resolve_secret(), algorithm="HS256")


def decode_access_token(token: str) -> Optional[dict]:
    """Verify the HS256 signature and expiry. Returns claims or ``None``.

    Returns ``None`` (rather than raising) so callers can use a simple
    truthiness check — auth middleware fast-paths a 401 in that case.
    """
    if _jose_jwt is None or not token:
        return None
    try:
        return _jose_jwt.decode(token, _resolve_secret(), algorithms=["HS256"])
    except (_JoseJWTError, Exception) as exc:
        logger.debug("JWT decode failed: %s", exc)
        return None
