"""API routes for SSO authentication and user management.

Endpoints exposed under ``/api/auth``:

  Authentication flow (OIDC Authorization Code grant):
    GET  /login        — redirect the browser to the SSO IdP authorize URL
    GET  /callback     — IdP redirects here with ?code=... ; we exchange the
                         code for tokens, upsert the user, and set an httpOnly
                         session cookie (``ca_session``).
    POST /logout       — clear the session cookie
    GET  /me           — return the currently authenticated user (or 401)

  User management (admin role only):
    GET  /users                       — list all users
    PUT  /users/{id}/role             — change a user's role
    PUT  /users/{id}/toggle-active    — activate/deactivate a user

The actual business logic lives in :class:`src.services.auth_service.AuthService`.
This module is just the FastAPI router that exposes it over HTTP.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])

# Lazily initialized auth service (set from app.py lifespan).
# We use a module-level singleton instead of a FastAPI dependency because the
# auth middleware in app.py needs to reach into this module from outside the
# normal request lifecycle.
_auth_service = None


def get_auth_service():
    """Get the global auth service instance."""
    global _auth_service
    if _auth_service is None:
        try:
            from src.services.config_service import ConfigService
            config = ConfigService().load_config()
        except Exception:
            config = {}
        from src.services.auth_service import AuthService
        _auth_service = AuthService(config)
    return _auth_service


def set_auth_service(service):
    """Set the global auth service instance (called from app.py)."""
    global _auth_service
    _auth_service = service


# ---------------------------------------------------------------------------
# Login / Callback / Logout
# ---------------------------------------------------------------------------

@router.get("/login")
async def login(request: Request):
    """Redirect to SSO provider for authentication."""
    auth = get_auth_service()
    if not auth.is_enabled:
        raise HTTPException(status_code=400, detail="Authentication not configured (provider=none)")
    url = auth.get_login_url()
    return RedirectResponse(url=url)


@router.get("/callback")
async def callback(request: Request, code: str = "", state: str = ""):
    """Handle SSO callback — exchange code for tokens and set session cookie.

    Called by the IdP after the user successfully authenticates. We:
      1. Exchange the auth code for an ID token + access token
      2. Decode the ID token to extract email/name/groups claims
      3. Upsert the user in our local DB (creating on first login)
      4. Generate our own short-lived JWT session token (HS256, signed with
         the server's session_secret)
      5. Set it as an httpOnly cookie and redirect to the UI root
    """
    auth = get_auth_service()
    if not auth.is_enabled:
        raise HTTPException(status_code=400, detail="Authentication not configured")

    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    try:
        result = auth.handle_callback(code, state)
    except Exception as exc:
        logger.exception("SSO callback failed: %s", exc)
        raise HTTPException(status_code=401, detail=f"Authentication failed: {exc}")

    # Set httpOnly session cookie and redirect to UI
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        key="ca_session",
        value=result["token"],
        httponly=True,
        samesite="lax",
        max_age=auth._ttl_hours * 3600,
        path="/",
    )
    return response


@router.get("/me")
async def get_current_user(request: Request):
    """Return the current authenticated user."""
    auth = get_auth_service()
    if not auth.is_enabled:
        return {"user": None, "auth_enabled": False}

    user = auth.get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"user": user, "auth_enabled": True}


@router.post("/logout")
async def logout(request: Request):
    """Clear the session cookie."""
    response = JSONResponse(content={"status": "logged_out"})
    response.delete_cookie("ca_session", path="/")
    return response


# ---------------------------------------------------------------------------
# User Management (admin only)
# ---------------------------------------------------------------------------

def _require_admin(request: Request):
    """Check that the current user is an admin.

    When auth is disabled (provider=none), this is a no-op so dev/POC
    deployments aren't blocked. In production, set [auth].provider=oidc
    so this check is enforced.
    """
    auth = get_auth_service()
    if not auth.is_enabled:
        return  # No auth = no restriction
    user = auth.get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")


@router.get("/users")
async def list_users(request: Request):
    """List all users (admin only)."""
    _require_admin(request)
    auth = get_auth_service()
    users = auth.list_users()
    return {"users": users, "total": len(users)}


@router.put("/users/{user_id}/role")
async def update_user_role(request: Request, user_id: str, role: str):
    """Change a user's role (admin only)."""
    _require_admin(request)
    auth = get_auth_service()
    try:
        user = auth.update_user_role(user_id, role)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.put("/users/{user_id}/toggle-active")
async def toggle_user_active(request: Request, user_id: str):
    """Activate/deactivate a user account (admin only)."""
    _require_admin(request)
    auth = get_auth_service()
    user = auth.deactivate_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# ===========================================================================
# ADFS browser-initiated SSO flow (Section 4–7 of the SSO spec)
# ===========================================================================
#
# These endpoints implement the browser-driven flow used when
# [auth].provider = adfs. The flow is:
#
#   Browser ── GET /api/auth/sso/config ──────► Backend
#           ◄── { client_id, redirect_uri,
#                  authorization_url, resource } ──
#   Browser builds ADFS authorize URL itself, redirects
#   ADFS ── 302 with code ───────────────────► Browser
#   Browser ── GET /api/auth/sso/callback?code=... ──► Backend
#                                           Backend exchanges code,
#                                           caches claims, issues JWT
#   Backend ── 302 /?token=...&user=... ────► Browser
#   Browser stores in localStorage, sends Bearer header on subsequent calls

import json
import secrets
from urllib.parse import urlencode


def _frontend_url(auth_cfg: dict) -> str:
    """Resolve the frontend root URL for post-callback redirects."""
    return (auth_cfg.get("adfs_frontend_url") or "/").rstrip("/") or "/"


def _redirect_with_error(auth_cfg: dict, error: str) -> RedirectResponse:
    """Build a 302 to the frontend with ``?error=...``."""
    base = _frontend_url(auth_cfg)
    sep = "&" if "?" in base else "?"
    return RedirectResponse(url=f"{base}{sep}error={error}", status_code=302)


@router.get("/sso/config")
async def sso_config(request: Request):
    """Return the public SSO config the frontend uses to build the
    ADFS authorize URL itself.

    Safe to expose — only contains values that ADFS will see in the
    redirect anyway. No secrets.
    """
    auth = get_auth_service()
    return auth.get_sso_config()


@router.get("/sso/auth")
async def sso_auth_fallback(state: str = ""):
    """Backend fallback redirect to the ADFS authorize URL.

    Used by the frontend if it cannot build the URL itself (e.g. config
    fetch failed or the browser blocked the build). Generates a fresh
    state parameter if none was supplied.
    """
    auth = get_auth_service()
    if not auth.is_adfs:
        raise HTTPException(status_code=400, detail="ADFS provider not configured")
    state = state or secrets.token_urlsafe(32)
    return RedirectResponse(url=auth.build_adfs_authorize_url(state), status_code=302)


@router.get("/sso/callback")
async def sso_callback_get(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
):
    """Browser callback path — ADFS redirects HERE after authentication.

    On success, redirects the browser to the frontend with token + user as
    query params (per the spec). On any failure, redirects with
    ``?error=...`` so the frontend can show a friendly message.
    """
    auth = get_auth_service()
    auth_cfg = auth._auth_cfg

    if not auth.is_adfs:
        raise HTTPException(status_code=400, detail="ADFS provider not configured")

    # ADFS itself reported an error (e.g. user denied consent)
    if error:
        return _redirect_with_error(auth_cfg, "auth_failed")

    if not code:
        return _redirect_with_error(auth_cfg, "auth_failed")

    try:
        result = auth.handle_adfs_callback(code)
    except ValueError as exc:
        # SID missing or other claim mapping failure (Section 5.2)
        logger.warning("ADFS callback user_info_failed: %s", exc)
        return _redirect_with_error(auth_cfg, "user_info_failed")
    except Exception as exc:
        logger.exception("ADFS callback failed: %s", exc)
        return _redirect_with_error(auth_cfg, "callback_failed")

    # 302 to frontend with token + URL-encoded user JSON.
    # NOTE: tokens in query strings are logged by load balancers and proxies.
    # The frontend immediately calls history.replaceState() to scrub the URL.
    base = _frontend_url(auth_cfg)
    sep = "&" if "?" in base else "?"
    user_json = json.dumps(result["user"], separators=(",", ":"))
    qs = urlencode({"token": result["token"], "user": user_json})
    return RedirectResponse(url=f"{base}{sep}{qs}", status_code=302)


@router.post("/sso/callback")
async def sso_callback_post(request: Request):
    """API-style variant of /sso/callback returning JSON instead of 302.

    For non-browser clients (CLI, mobile, server-to-server) that want to
    drive the SSO flow themselves. Body: ``{"code": "...", "state": "..."}``.
    """
    auth = get_auth_service()
    if not auth.is_adfs:
        raise HTTPException(status_code=400, detail="ADFS provider not configured")

    body = await request.json()
    code = body.get("code", "")
    if not code:
        raise HTTPException(status_code=400, detail="Missing 'code' in request body")

    try:
        return auth.handle_adfs_callback(code)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=f"user_info_failed: {exc}")
    except Exception as exc:
        logger.exception("ADFS callback failed: %s", exc)
        raise HTTPException(status_code=500, detail="callback_failed")


@router.post("/sso/logout")
async def sso_logout(user_id: str = ""):
    """Invalidate the server-side cached ADFS token for ``user_id``.

    The internal JWT itself is not revoked — JWTs are stateless. The
    frontend should also clear localStorage. This endpoint exists to evict
    the cached ADFS access token / refresh token from the in-memory cache
    so that any future ``/sso/validate`` calls return false.
    """
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing user_id")
    auth = get_auth_service()
    removed = auth.invalidate_token(user_id)
    return {"status": "logged_out", "cache_evicted": removed}


@router.get("/sso/validate")
async def sso_validate(user_id: str = ""):
    """Check whether the server-side cache still has a valid ADFS token
    for the given ``user_id``.

    Used by integration tests and ops tooling. Not part of the normal
    request path — the auth middleware uses Bearer JWT validation, not
    this endpoint.
    """
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing user_id")
    auth = get_auth_service()
    cached = auth.get_cached_token(user_id)
    return {
        "valid": cached is not None,
        "user_id": user_id,
    }
