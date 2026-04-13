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
        # In-memory ADFS token cache (Section 5.4 of the SSO spec). Process-
        # local and volatile — lost on restart, not shared across instances.
        # Keyed by user_id (SID). Each entry: {token_data, cached_at, expires_at}.
        self._token_cache: dict[str, dict] = {}
        # Push the configured secret into jwt_service so the middleware can
        # decode Bearer tokens without re-reading config.
        try:
            from src.services import jwt_service as _jwt_service

            _jwt_service.set_secret(self._secret)
        except Exception:  # pragma: no cover
            pass

    @property
    def is_enabled(self) -> bool:
        return self._provider != "none"

    @property
    def is_adfs(self) -> bool:
        return self._provider == "adfs"

    @property
    def is_oidc(self) -> bool:
        return self._provider == "oidc"

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
        """Extract and validate user from request cookie or Authorization header.

        ADFS deployments only use the ``Authorization: Bearer`` header (the
        token lives in localStorage and is sent explicitly by the frontend).
        OIDC deployments accept either the httpOnly ``ca_session`` cookie or
        the Bearer header.
        """
        if not self.is_enabled:
            return None

        # ADFS: Bearer header is the only supported transport.
        # OIDC: prefer cookie (httpOnly is more secure), fall back to Bearer.
        token = ""
        if self.is_oidc:
            token = request.cookies.get("ca_session", "")
        if not token:
            auth_header = request.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]

        if not token:
            return None

        # Both providers use the same HS256 secret for internal session JWTs.
        # Use jwt_service so we don't depend on the (lazily imported) jose
        # binding being initialized on this AuthService instance.
        from src.services.jwt_service import decode_access_token

        claims = decode_access_token(token)
        if not claims:
            return None

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
        sid: Optional[str] = None,
        first_name: str = "",
        last_name: str = "",
        full_name: str = "",
    ) -> dict:
        """Create or update user record on SSO login.

        For ADFS the SID claim becomes the canonical user identifier and is
        stored in both ``sid`` and (for backwards compatibility with the OIDC
        path) ``sso_subject``. ``first_name`` / ``last_name`` / ``full_name``
        come from ADFS-specific claims and are blank for OIDC.
        """
        from src.data.database import get_session
        from src.data.models import User

        # ADFS uses SID as the unique identifier; OIDC uses sub. Default sid
        # to sso_subject so a single column suffices for downstream queries.
        sid = sid or sso_subject

        with get_session() as db:
            # Prefer SID lookup for ADFS so renaming an email doesn't create
            # duplicate rows. Fall back to email for OIDC and first-time logins.
            user = None
            if sid:
                user = db.query(User).filter(User.sid == sid).first()
            if user is None:
                user = db.query(User).filter(User.email == email).first()

            if user is None:
                user = User(
                    email=email,
                    display_name=display_name or full_name,
                    sso_subject=sso_subject,
                    sso_provider=sso_provider,
                    sid=sid,
                    first_name=first_name,
                    last_name=last_name,
                    full_name=full_name,
                    role=role,
                )
                db.add(user)
            else:
                user.email = email or user.email
                user.display_name = display_name or full_name or user.display_name
                user.sso_subject = sso_subject or user.sso_subject
                user.sso_provider = sso_provider or user.sso_provider
                user.sid = sid or user.sid
                user.first_name = first_name or user.first_name
                user.last_name = last_name or user.last_name
                user.full_name = full_name or user.full_name
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

    # ==================================================================
    # ADFS browser-initiated flow (Section 4–7 of the SSO spec)
    # ==================================================================
    #
    # Activated when [auth].provider == "adfs". The browser builds the
    # authorize URL itself after fetching this config and redirects to ADFS.
    # ADFS calls back to /api/auth/sso/callback, where we exchange the code,
    # cache the decoded claims, issue our internal HS256 JWT, and redirect
    # the browser to the frontend with token + user as query params.

    # ----- (4.2) Browser-facing config endpoint --------------------------

    def get_sso_config(self) -> dict:
        """Return the public SSO config the frontend uses to build the
        authorize URL itself.

        This is what ``GET /api/auth/sso/config`` returns. It must NOT
        contain any secret material — only the values the browser legitimately
        needs (and that ADFS itself will see in the redirect anyway).
        """
        if not self.is_adfs:
            return {"enabled": self.is_enabled, "provider": self._provider}
        return {
            "enabled": True,
            "provider": "adfs",
            "client_id": self._auth_cfg.get("adfs_client_id", ""),
            "redirect_uri": self._auth_cfg.get("adfs_redirect_uri", ""),
            "authorization_url": self._auth_cfg.get("adfs_authorization_url", ""),
            "resource": self._auth_cfg.get("adfs_resource", ""),
        }

    def build_adfs_authorize_url(self, state: str) -> str:
        """Backend fallback for building the ADFS authorize URL.

        Used by ``GET /api/auth/sso/auth?state=...`` when the frontend cannot
        build the URL itself (Section 4.2 fallback in the spec).
        """
        from urllib.parse import urlencode

        params = {
            "client_id": self._auth_cfg.get("adfs_client_id", ""),
            "response_type": "code",
            "redirect_uri": self._auth_cfg.get("adfs_redirect_uri", ""),
            "response_mode": "query",
            "resource": self._auth_cfg.get("adfs_resource", ""),
            "scope": "openid",
            "state": state,
        }
        base = self._auth_cfg.get("adfs_authorization_url", "")
        return f"{base}?{urlencode(params)}"

    # ----- (5.1) Token exchange ------------------------------------------

    def exchange_code_for_token(self, code: str) -> dict:
        """Exchange an authorization code at the ADFS token endpoint.

        Public-client flow — NO ``client_secret`` is sent. ADFS is configured
        with the matching public client RPT. Returns the raw token response
        dict from ADFS (typically ``access_token``, ``token_type``,
        ``expires_in``, ``refresh_token``).
        """
        import requests as http_requests

        token_url = self._auth_cfg.get("adfs_token_url", "")
        if not token_url:
            raise ValueError("adfs_token_url not configured")

        resp = http_requests.post(
            token_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self._auth_cfg.get("adfs_redirect_uri", ""),
                "client_id": self._auth_cfg.get("adfs_client_id", ""),
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"ADFS token exchange failed (status={resp.status_code}): {resp.text}"
            )
        return resp.json()

    # ----- (5.2) User identity extraction --------------------------------

    def get_user_info(self, token_payload: dict) -> dict:
        """Decode the ADFS access token's claims (without signature verify)
        and map them to our internal user dict.

        ADFS issues an access token that is itself a JWT. We trust it because
        we just received it from ADFS over HTTPS in step 5.1 — verifying the
        signature would require fetching the ADFS signing keys (a
        meaningful operational burden). For higher assurance, configure the
        backend to call ``/adfs/oauth2/userinfo`` instead; this method
        deliberately matches the simpler reference spec.

        Required claim: ``SID``. If missing, raises ValueError so the
        callback handler can return ``?error=user_info_failed``.
        """
        if jwt is None:
            raise RuntimeError(
                "python-jose is required for ADFS auth. "
                "Install with: pip install 'python-jose[cryptography]>=3.3.0'"
            )

        access_token = token_payload.get("access_token", "")
        if not access_token:
            raise ValueError("ADFS token response missing access_token")

        claims = jwt.get_unverified_claims(access_token)

        sid = claims.get("SID") or claims.get("sid") or ""
        if not sid:
            raise ValueError("ADFS access token missing SID claim")

        first_name = claims.get("FirstName") or claims.get("given_name") or ""
        last_name = claims.get("LastName") or claims.get("family_name") or ""
        email = claims.get("email") or claims.get("upn") or ""
        full_name = (
            claims.get("name")
            or f"{first_name} {last_name}".strip()
            or email
        )

        # ADFS group claims may be a single string or a list, depending on
        # the RPT claim rule. Normalize to a list for the role mapper.
        groups_claim = claims.get(
            self._auth_cfg.get("claim_groups", "groups"), []
        )
        if isinstance(groups_claim, str):
            groups = [groups_claim]
        elif isinstance(groups_claim, list):
            groups = [str(g) for g in groups_claim]
        else:
            groups = []

        return {
            "user_id": sid,
            "sid": sid,
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
            "full_name": full_name,
            "groups": groups,
        }

    # ----- (5.3) Internal API JWT ----------------------------------------

    def create_internal_jwt(self, user_id: str, expires_in: int = 3600) -> str:
        """Issue our HS256 internal session JWT carrying ``sub=user_id``.

        Delegates to ``jwt_service`` so the WebSocket route and middleware
        can validate tokens without importing the full AuthService.
        """
        from src.services.jwt_service import create_access_token

        return create_access_token({"sub": user_id}, expires_in=expires_in)

    # ----- (5.4) Server-side ADFS token cache ----------------------------

    def cache_token(self, user_id: str, token_data: dict) -> None:
        """Store the full ADFS token payload in the in-memory cache.

        Applies a 5-minute safety buffer before the actual ADFS expiry, so
        callers don't get a fresh-looking token that's about to expire.
        """
        import time as _time

        expires_in = int(token_data.get("expires_in", 3600))
        # 5-min safety buffer per Section 5.4
        effective_ttl = max(60, expires_in - 300)
        self._token_cache[user_id] = {
            "token_data": token_data,
            "cached_at": _time.time(),
            "expires_at": _time.time() + effective_ttl,
        }

    def get_cached_token(self, user_id: str) -> Optional[dict]:
        """Return the cached token if still valid (and not within the buffer)."""
        import time as _time

        entry = self._token_cache.get(user_id)
        if not entry:
            return None
        if _time.time() >= entry["expires_at"]:
            self._token_cache.pop(user_id, None)
            return None
        return entry["token_data"]

    def invalidate_token(self, user_id: str) -> bool:
        """Remove a user's cached token. Returns True if something was removed."""
        return self._token_cache.pop(user_id, None) is not None

    # ----- High-level orchestration --------------------------------------

    def handle_adfs_callback(self, code: str) -> dict:
        """Run the full ADFS callback pipeline.

        1. Exchange the code at the ADFS token endpoint
        2. Decode and map claims
        3. Cache the ADFS token payload server-side
        4. Upsert the user in the local DB
        5. Issue our internal HS256 JWT

        Returns ``{"token": <jwt>, "user": <user_dict>}`` ready for the
        callback HTTP handler to URL-encode and redirect with.
        """
        token_payload = self.exchange_code_for_token(code)
        info = self.get_user_info(token_payload)
        user_id = info["user_id"]

        self.cache_token(user_id, token_payload)

        role = self.map_role_from_groups(info.get("groups", []))
        user = self._upsert_user(
            email=info["email"],
            display_name=info["full_name"],
            sso_subject=user_id,
            sso_provider=self._auth_cfg.get("adfs_authorization_url", "adfs"),
            role=role,
            groups=info.get("groups", []),
            sid=user_id,
            first_name=info["first_name"],
            last_name=info["last_name"],
            full_name=info["full_name"],
        )

        jwt_token = self.create_internal_jwt(
            user_id=user["id"],
            expires_in=int(token_payload.get("expires_in", 3600)),
        )
        return {"token": jwt_token, "user": user}
