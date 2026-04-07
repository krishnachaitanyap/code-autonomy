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
