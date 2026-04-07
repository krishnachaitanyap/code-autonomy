"""
Auth resolver: pick the right TokenProvider for a given VCS platform.

This is the *only* place callers should look up VCS credentials. It hides the
choice between "app-style" providers (GitHub App, Bitbucket Cloud OAuth) and
static fallbacks (PAT, HTTP access tokens), so service code doesn't need
provider-specific branches.

Usage:
    from src.platform.auth_resolver import get_token_provider

    provider = get_token_provider("github", config)
    clone_repo(repo_url, target, branch, auth_token=provider)
    pr = GitHubPR(provider).create_pull_request(...)

Backwards compatibility:
    If no app-style auth is configured, a ``StaticTokenProvider`` wrapping the
    existing PAT / HTTP access token is returned, so existing deployments
    continue to work unchanged.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from src.platform.token_provider import (
    BasicAuthTokenProvider,
    StaticTokenProvider,
    TokenProvider,
)

logger = logging.getLogger(__name__)


def _load_pem(github_app_cfg: dict) -> str:
    """Resolve a PEM private key from one of: inline value, file path, or env var."""
    inline = (github_app_cfg.get("private_key") or "").strip()
    if inline:
        return inline

    env_var = github_app_cfg.get("private_key_env") or ""
    if env_var:
        val = os.environ.get(env_var, "").strip()
        if val:
            return val

    path = github_app_cfg.get("private_key_path") or ""
    if path:
        p = Path(path)
        if p.exists():
            return p.read_text(encoding="utf-8")
        raise FileNotFoundError(f"GitHub App private key file not found: {path}")

    raise ValueError(
        "GitHub App is enabled but no private key was provided. "
        "Set one of: private_key, private_key_env, or private_key_path."
    )


def _resolve_secret(env_var: str, fallback: str = "") -> str:
    if env_var:
        val = os.environ.get(env_var, "")
        if val:
            return val
    return fallback


def get_token_provider(platform: str, config: dict) -> TokenProvider:
    """Return the best ``TokenProvider`` for the given VCS platform.

    Args:
        platform: ``"github"``, ``"bitbucket"`` (Bitbucket Cloud), or
            ``"bitbucket_server"``.
        config: Loaded config dict from ``config_loader.load_config``.

    Returns:
        A ``TokenProvider``. Will raise if no usable credentials are found
        for the requested platform.
    """
    platform = (platform or "github").lower()

    # ------------------------------------------------------------------ #
    # GitHub / GitHub Enterprise Server                                  #
    # ------------------------------------------------------------------ #
    if platform == "github":
        gh_app = config.get("github_app") or {}
        if gh_app.get("enabled"):
            from src.platform.providers.github_app import GitHubAppTokenProvider

            return GitHubAppTokenProvider(
                app_id=gh_app.get("app_id", ""),
                installation_id=gh_app.get("installation_id", ""),
                private_key_pem=_load_pem(gh_app),
                api_base_url=gh_app.get("api_base_url") or None,
            )

        # Fallback: static PAT (existing behavior)
        token = (
            (config.get("github_config") or {}).get("auth_token", "")
            or os.environ.get("GITHUB_TOKEN", "")
        )
        if not token:
            logger.warning(
                "No GitHub credentials configured. Set GITHUB_TOKEN or enable "
                "[github_app] for App-based auth."
            )
        return StaticTokenProvider(token)

    # ------------------------------------------------------------------ #
    # Bitbucket Cloud                                                    #
    # ------------------------------------------------------------------ #
    if platform == "bitbucket":
        bb_oauth = config.get("bitbucket_oauth") or {}
        if bb_oauth.get("enabled"):
            from src.platform.providers.bitbucket_cloud_oauth import (
                BitbucketCloudOAuthProvider,
            )

            client_secret = (
                bb_oauth.get("client_secret")
                or _resolve_secret(bb_oauth.get("client_secret_env", ""))
            )
            return BitbucketCloudOAuthProvider(
                client_key=bb_oauth.get("client_key", ""),
                client_secret=client_secret,
            )

        # Fallback: HTTP access token (Bearer) or app password (Basic)
        http_token = os.environ.get("BITBUCKET_HTTP_ACCESS_TOKEN", "")
        if http_token:
            return StaticTokenProvider(http_token)

        app_password = os.environ.get("BITBUCKET_APP_PASSWORD", "")
        username = os.environ.get("BITBUCKET_USERNAME", "")
        if app_password and username:
            return BasicAuthTokenProvider(username, app_password)

        # Last resort: whatever is in [github_config].auth_token (legacy)
        legacy = (config.get("github_config") or {}).get("auth_token", "")
        if legacy:
            return StaticTokenProvider(legacy)

        logger.warning("No Bitbucket Cloud credentials configured.")
        return StaticTokenProvider("")

    # ------------------------------------------------------------------ #
    # Bitbucket Server / Data Center                                     #
    # ------------------------------------------------------------------ #
    if platform == "bitbucket_server":
        # No App equivalent exists. Use a project-scoped HTTP access token.
        bb_cfg = config.get("bitbucket") or {}
        token = (
            bb_cfg.get("user_token", "")
            or os.environ.get("BITBUCKET_HTTP_ACCESS_TOKEN", "")
            or os.environ.get("BITBUCKET_SERVER_TOKEN", "")
        )
        if not token:
            logger.warning(
                "No Bitbucket Server credentials configured. Set "
                "BITBUCKET_HTTP_ACCESS_TOKEN or [bitbucket].user_token."
            )
        return StaticTokenProvider(token)

    raise ValueError(f"Unknown VCS platform: {platform}")
