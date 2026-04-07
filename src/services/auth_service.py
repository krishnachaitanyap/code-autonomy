"""
Auth service — OIDC SSO flow, JWT session tokens, and user management.

Supports any OpenID Connect provider (Okta, Azure AD, Keycloak, Ping, etc.).
When ``[auth].provider`` is ``none``, all auth functions return ``None`` so
the application runs in open-access mode (useful for dev / POC environments).

Architecture:
    Browser ──login──▶ /api/auth/login
                         │
                         ▼  302 redirect with state+nonce
                       IdP authorize endpoint
                         │
                         ▼  user authenticates
                       /api/auth/callback?code=...
                         │
                         ▼  exchange code → ID token
                       _upsert_user()  ───▶ users table
                         │
                         ▼  sign HS256 JWT
                       Set-Cookie: ca_session=...
                         │
                         ▼  subsequent API calls
                       auth middleware in app.py validates JWT,
                       attaches request.state.user

Roles are derived from SSO group membership at login time using the
``admin_groups`` and ``developer_groups`` config lists. Admins can override
roles after creation via the ``/api/auth/users/{id}/role`` endpoint.
"""

import hashlib
import logging
import secrets
import time
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import Request

logger = logging.getLogger(__name__)

# JWT and OIDC dependencies are optional — only needed when provider = oidc.
# Importing them at module top would force every dev install to pull in
# python-jose + cryptography even when SSO is disabled, so we import lazily
# and surface a friendly error message at the call site if they're missing.
try:
    from jose import jwt, JWTError
except ImportError:
    jwt = None  # type: ignore[assignment]
    JWTError = Exception  # type: ignore[assignment,misc]

try:
    from authlib.integrations.requests_client import OAuth2Session
except ImportError:
    OAuth2Session = None  # type: ignore[assignment,misc]


class AuthService:
    """Handles OIDC authentication flow and JWT session management."""

    def __init__(self, config: dict) -> None:
        self._auth_cfg = config.get("auth", {})
        self._provider = self._auth_cfg.get("provider", "none")
        # If no session secret is configured, generate a random one at startup.
        # NOTE: this means JWTs are invalidated on every server restart. For
        # production, set [auth].session_secret in config.ini (or env var
        # AUTH_SESSION_SECRET) to a stable value so sessions survive restarts.
        self._secret = self._auth_cfg.get("session_secret") or secrets.token_hex(32)
        self._ttl_hours = int(self._auth_cfg.get("session_ttl_hours", 24))
        # OIDC discovery doc is fetched lazily on first login and cached.
        self._oidc_metadata: Optional[dict] = None

    @property
    def is_enabled(self) -> bool:
        return self._provider != "none"

    # ------------------------------------------------------------------
    # OIDC discovery
    # ------------------------------------------------------------------

    def _get_oidc_metadata(self) -> dict:
        """Fetch and cache OIDC discovery document."""
        if self._oidc_metadata is not None:
            return self._oidc_metadata
        issuer = self._auth_cfg.get("oidc_issuer_url", "").rstrip("/")
        if not issuer:
            raise ValueError("oidc_issuer_url not configured")
        import requests as http_requests
        resp = http_requests.get(f"{issuer}/.well-known/openid-configuration", timeout=10)
        resp.raise_for_status()
        self._oidc_metadata = resp.json()
        return self._oidc_metadata

    # ------------------------------------------------------------------
    # Login URL
    # ------------------------------------------------------------------

    def get_login_url(self, state: Optional[str] = None) -> str:
        """Build the OIDC authorization URL."""
        meta = self._get_oidc_metadata()
        auth_endpoint = meta["authorization_endpoint"]
        client_id = self._auth_cfg["oidc_client_id"]
        redirect_uri = self._auth_cfg["oidc_redirect_uri"]
        state = state or secrets.token_urlsafe(32)
        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": "openid email profile groups",
            "state": state,
        }
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        return f"{auth_endpoint}?{qs}"

    # ------------------------------------------------------------------
    # Callback — exchange code for tokens
    # ------------------------------------------------------------------

    def handle_callback(self, code: str, state: str) -> dict:
        """Exchange authorization code for tokens, upsert user, return JWT."""
        meta = self._get_oidc_metadata()
        token_endpoint = meta["token_endpoint"]

        import requests as http_requests
        token_resp = http_requests.post(
            token_endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self._auth_cfg["oidc_redirect_uri"],
                "client_id": self._auth_cfg["oidc_client_id"],
                "client_secret": self._auth_cfg.get("oidc_client_secret", ""),
            },
            timeout=10,
        )
        token_resp.raise_for_status()
        tokens = token_resp.json()

        # Decode ID token to extract claims (skip signature verification for
        # tokens we just received from the IdP over HTTPS)
        id_token = tokens.get("id_token", "")
        if jwt is None:
            raise RuntimeError("python-jose is required for OIDC auth. Install with: pip install python-jose[cryptography]")
        claims = jwt.get_unverified_claims(id_token)

        email = claims.get(self._auth_cfg.get("claim_email", "email"), "")
        name = claims.get(self._auth_cfg.get("claim_name", "name"), "")
        groups = claims.get(self._auth_cfg.get("claim_groups", "groups"), [])
        subject = claims.get("sub", "")

        if not email:
            raise ValueError("OIDC token missing email claim")

        # Map role from groups
        role = self.map_role_from_groups(groups)

        # Upsert user in database
        user = self._upsert_user(
            email=email,
            display_name=name,
            sso_subject=subject,
            sso_provider=self._auth_cfg.get("oidc_issuer_url", ""),
            role=role,
            groups=groups,
        )

        # Generate JWT session token
        session_token = self._create_session_token(user)
        return {"token": session_token, "user": user}

    # ------------------------------------------------------------------
    # JWT management
    # ------------------------------------------------------------------

    def _create_session_token(self, user: dict) -> str:
        """Create a signed JWT session token."""
        if jwt is None:
            raise RuntimeError("python-jose is required for JWT session tokens")
        now = int(time.time())
        payload = {
            "sub": user["id"],
            "email": user["email"],
            "role": user["role"],
            "team_id": user.get("team_id") or "",
            "iat": now,
            "exp": now + (self._ttl_hours * 3600),
        }
        return jwt.encode(payload, self._secret, algorithm="HS256")

    def validate_token(self, token: str) -> Optional[dict]:
        """Verify JWT signature and expiry. Returns claims dict or None."""
        if jwt is None:
            return None
        try:
            claims = jwt.decode(token, self._secret, algorithms=["HS256"])
            return claims
        except (JWTError, Exception):
            return None

    def get_current_user(self, request: Request) -> Optional[dict]:
        """Extract and validate user from request cookie or Authorization header."""
        if not self.is_enabled:
            return None

        # Try cookie first, then Authorization header
        token = request.cookies.get("ca_session")
        if not token:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]

        if not token:
            return None

        claims = self.validate_token(token)
        if not claims:
            return None

        # Look up full user from DB
        return self._get_user_by_id(claims["sub"])

    # ------------------------------------------------------------------
    # Role mapping
    # ------------------------------------------------------------------

    def map_role_from_groups(self, groups: list[str]) -> str:
        """Map SSO groups to application role.

        Precedence: admin > developer > viewer (default). The first matching
        group wins. Configure ``[auth].admin_groups`` and ``developer_groups``
        as comma-separated lists in config.ini.

        Note: this is only used at *first login*. Once a user exists in the
        DB, an admin can override their role via the API and that override
        persists across re-logins (we still call this on every login, but
        admin-issued role changes can be re-applied as needed).
        """
        admin_groups = self._auth_cfg.get("admin_groups", [])
        developer_groups = self._auth_cfg.get("developer_groups", [])

        if isinstance(admin_groups, str):
            admin_groups = [g.strip() for g in admin_groups.split(",") if g.strip()]
        if isinstance(developer_groups, str):
            developer_groups = [g.strip() for g in developer_groups.split(",") if g.strip()]

        for group in groups:
            if group in admin_groups:
                return "admin"
        for group in groups:
            if group in developer_groups:
                return "developer"

        # Default: developer (most permissive non-admin role)
        return "developer"

    # ------------------------------------------------------------------
    # User persistence
    # ------------------------------------------------------------------

    def _upsert_user(
        self,
        email: str,
        display_name: str,
        sso_subject: str,
        sso_provider: str,
        role: str,
        groups: list[str],
    ) -> dict:
        """Create or update user record on SSO login."""
        from src.data.database import get_session
        from src.data.models import User

        with get_session() as db:
            user = db.query(User).filter(User.email == email).first()
            if user is None:
                user = User(
                    email=email,
                    display_name=display_name,
                    sso_subject=sso_subject,
                    sso_provider=sso_provider,
                    role=role,
                )
                db.add(user)
            else:
                user.display_name = display_name or user.display_name
                user.sso_subject = sso_subject or user.sso_subject
                user.sso_provider = sso_provider or user.sso_provider
                # Only update role from SSO if not manually overridden
                user.role = role
            user.last_login_at = datetime.now(timezone.utc)
            db.flush()
            return user.to_dict()

    def _get_user_by_id(self, user_id: str) -> Optional[dict]:
        """Fetch user by ID."""
        from src.data.database import get_session
        from src.data.models import User

        with get_session() as db:
            user = db.get(User, user_id)
            if user and user.is_active:
                return user.to_dict()
            return None

    def list_users(self) -> list[dict]:
        """List all users."""
        from src.data.database import get_session
        from src.data.models import User

        with get_session() as db:
            users = db.query(User).order_by(User.created_at.desc()).all()
            return [u.to_dict() for u in users]

    def update_user_role(self, user_id: str, role: str) -> Optional[dict]:
        """Update a user's role. Returns updated user or None."""
        if role not in ("admin", "developer", "viewer"):
            raise ValueError(f"Invalid role: {role}")

        from src.data.database import get_session
        from src.data.models import User

        with get_session() as db:
            user = db.get(User, user_id)
            if not user:
                return None
            user.role = role
            db.flush()
            return user.to_dict()

    def deactivate_user(self, user_id: str) -> Optional[dict]:
        """Deactivate a user account."""
        from src.data.database import get_session
        from src.data.models import User

        with get_session() as db:
            user = db.get(User, user_id)
            if not user:
                return None
            user.is_active = not user.is_active
            db.flush()
            return user.to_dict()
