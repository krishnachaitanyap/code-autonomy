"""
Credential resolution and Kerberos authentication helpers for custom tools.

Credentials can come from two sources:
1. Direct entry — stored in DB via CustomTool.credential_config
2. Config profile — references a [tool_cred_*] section in config.ini

The LLM never sees credential values. This module is used only by the
execution layer (tools.py) to inject authenticated environments into
subprocess calls.
"""

import hashlib
import logging
import os
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)

# Secret fields that should never appear in API responses or LLM prompts
_SECRET_FIELDS = {"password", "token", "keytab_path"}

# Non-secret fields safe to include in sanitized responses
_SAFE_FIELDS = {"username", "realm", "kdc", "principal", "base_url"}

# Connection detail fields — always safe to expose
_CONNECTION_FIELDS = {
    "connection_type", "host", "port", "database", "schema", "service_name",
    "ssl_enabled", "extra_params",
    "mcp_transport", "mcp_command", "mcp_server_name",
}


def resolve_tool_credentials(cred_config: dict, agent_config: dict) -> dict:
    """Resolve credential_config to actual credential values.

    Resolution paths:
    - **Direct**: credentials stored inline in cred_config (from DB)
    - **Config profile**: cred_config["config_section"] references a profile
      from agent_config["tool_credentials"] (loaded from config.ini)

    Empty fields fall back to env vars: ``{PROFILE_NAME_UPPER}_{FIELD_UPPER}``

    Returns a resolved credential dict with all available fields populated.
    """
    if not cred_config:
        return {}

    auth_type = cred_config.get("auth_type", "none")
    if auth_type == "none":
        return {}

    resolved: dict = {"auth_type": auth_type}

    # If referencing a config.ini profile, merge profile values as base
    config_section = cred_config.get("config_section")
    if config_section:
        tool_creds = agent_config.get("tool_credentials", {})
        profile = tool_creds.get(config_section, {})
        resolved.update(profile)
        # Override auth_type from the actual profile if present
        resolved["auth_type"] = profile.get("auth_type", auth_type)
        env_prefix = config_section.upper()
    else:
        env_prefix = auth_type.upper()

    # All resolvable fields (auth + connection)
    _all_fields = (
        "realm", "kdc", "principal", "keytab_path",
        "username", "password", "token", "base_url",
        "host", "port", "database", "schema", "service_name",
        "ssl_enabled", "extra_params",
        "mcp_transport", "mcp_command", "mcp_server_name",
    )

    # Overlay direct DB values (non-empty only)
    for key in _all_fields:
        val = cred_config.get(key)
        if val:
            resolved[key] = val

    # Copy connection_type directly
    if cred_config.get("connection_type"):
        resolved["connection_type"] = cred_config["connection_type"]

    # Env var fallback for any still-empty fields
    for key in _all_fields:
        if not resolved.get(key):
            env_val = os.environ.get(f"{env_prefix}_{key.upper()}", "")
            if env_val:
                resolved[key] = env_val

    return resolved


def build_authenticated_env(resolved_creds: dict, base_env: Optional[dict] = None) -> dict:
    """Build a subprocess environment dict with credential-related vars injected.

    Args:
        resolved_creds: Output of resolve_tool_credentials()
        base_env: Base environment to extend (defaults to os.environ)

    Returns:
        New env dict suitable for subprocess.run(env=...)
    """
    env = dict(base_env or os.environ)
    auth_type = resolved_creds.get("auth_type", "none")

    if auth_type == "kerberos":
        # Per-tool Kerberos ticket cache to prevent cross-tool interference
        principal = resolved_creds.get("principal", "")
        cache_hash = hashlib.md5(principal.encode()).hexdigest()[:12]
        cache_path = f"/tmp/krb5cc_tool_{cache_hash}"

        if resolved_creds.get("realm") and resolved_creds.get("kdc"):
            env["KRB5_CONFIG"] = _generate_krb5_conf(resolved_creds)
        env["KRB5CCNAME"] = f"FILE:{cache_path}"
        if resolved_creds.get("keytab_path"):
            env["KRB5_KTNAME"] = resolved_creds["keytab_path"]

    elif auth_type == "basic":
        if resolved_creds.get("username"):
            env["TOOL_AUTH_USERNAME"] = resolved_creds["username"]
        if resolved_creds.get("password"):
            env["TOOL_AUTH_PASSWORD"] = resolved_creds["password"]

    elif auth_type == "bearer":
        if resolved_creds.get("token"):
            env["TOOL_BEARER_TOKEN"] = resolved_creds["token"]

    # Inject connection details as env vars for subprocess tools
    conn_type = resolved_creds.get("connection_type", "")
    if conn_type:
        env["TOOL_CONNECTION_TYPE"] = conn_type
    for key in ("host", "port", "database", "schema", "service_name"):
        val = resolved_creds.get(key)
        if val:
            env[f"TOOL_DB_{key.upper()}"] = str(val)
    if resolved_creds.get("ssl_enabled"):
        env["TOOL_DB_SSL"] = resolved_creds["ssl_enabled"]
    if resolved_creds.get("extra_params"):
        env["TOOL_DB_EXTRA_PARAMS"] = resolved_creds["extra_params"]

    # MCP connection details
    for key in ("mcp_transport", "mcp_command", "mcp_server_name"):
        val = resolved_creds.get(key)
        if val:
            env[f"TOOL_{key.upper()}"] = val

    return env


def ensure_kerberos_ticket(
    resolved_creds: dict,
    cwd: Optional[str] = None,
    timeout: int = 30,
) -> tuple[bool, str]:
    """Ensure a valid Kerberos ticket exists, obtaining one if needed.

    Checks existing ticket via ``klist -s`` (exit 0 = valid).
    If invalid, runs ``kinit -kt {keytab_path} {principal}``.

    Returns:
        (True, "Kerberos ticket obtained/valid") or (False, "kinit failed: ...")
    """
    principal = resolved_creds.get("principal", "")
    keytab = resolved_creds.get("keytab_path", "")

    if not principal or not keytab:
        return False, "Missing principal or keytab_path for Kerberos auth"

    env = build_authenticated_env(resolved_creds)

    # Check if existing ticket is valid
    try:
        result = subprocess.run(
            ["klist", "-s"],
            env=env,
            capture_output=True,
            timeout=10,
            cwd=cwd,
        )
        if result.returncode == 0:
            return True, "Kerberos ticket valid"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass  # klist not available or timed out — try kinit

    # Obtain new ticket
    try:
        result = subprocess.run(
            ["kinit", "-kt", keytab, principal],
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
        if result.returncode == 0:
            return True, "Kerberos ticket obtained"
        detail = (result.stderr or result.stdout or "").strip()
        return False, f"kinit failed (exit {result.returncode}): {detail}"
    except subprocess.TimeoutExpired:
        return False, f"kinit timed out after {timeout}s"
    except FileNotFoundError:
        return False, "kinit not found — Kerberos tools not installed"
    except Exception as exc:
        return False, f"kinit error: {exc}"


def test_credentials(resolved_creds: dict) -> dict:
    """Test whether resolved credentials are functional.

    - Kerberos: runs kinit + klist
    - Basic/Bearer: HEAD request to base_url

    Returns:
        {"status": "ok"} or {"status": "error", "detail": "..."}
    """
    auth_type = resolved_creds.get("auth_type", "none")

    if auth_type == "none":
        return {"status": "ok", "detail": "No authentication configured"}

    if auth_type == "kerberos":
        ok, msg = ensure_kerberos_ticket(resolved_creds)
        return {"status": "ok" if ok else "error", "detail": msg}

    # Basic / Bearer — try HEAD request to base_url
    base_url = resolved_creds.get("base_url")
    if not base_url:
        return {"status": "error", "detail": "No base_url configured for credential test"}

    try:
        import urllib.request
        import urllib.error

        req = urllib.request.Request(base_url, method="HEAD")
        if auth_type == "bearer":
            token = resolved_creds.get("token", "")
            req.add_header("Authorization", f"Bearer {token}")
        elif auth_type == "basic":
            import base64
            username = resolved_creds.get("username", "")
            password = resolved_creds.get("password", "")
            credentials = base64.b64encode(f"{username}:{password}".encode()).decode()
            req.add_header("Authorization", f"Basic {credentials}")

        urllib.request.urlopen(req, timeout=15)
        return {"status": "ok", "detail": f"{auth_type} authentication successful"}
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return {"status": "error", "detail": f"Authentication failed (HTTP 401)"}
        if e.code == 403:
            return {"status": "error", "detail": f"Authorization denied (HTTP 403)"}
        # Other HTTP errors (404, 405, etc.) may still mean auth worked
        return {"status": "ok", "detail": f"{auth_type} auth accepted (HTTP {e.code})"}
    except Exception as exc:
        return {"status": "error", "detail": f"Connection error: {exc}"}


def _generate_krb5_conf(resolved_creds: dict) -> str:
    """Generate a temporary krb5.conf file for the given realm/kdc and return its path."""
    realm = resolved_creds.get("realm", "")
    kdc = resolved_creds.get("kdc", "")

    conf_hash = hashlib.md5(f"{realm}:{kdc}".encode()).hexdigest()[:12]
    conf_path = f"/tmp/krb5_tool_{conf_hash}.conf"

    # Write only if not already present (idempotent)
    if not os.path.exists(conf_path):
        content = f"""[libdefaults]
    default_realm = {realm}
    dns_lookup_realm = false
    dns_lookup_kdc = false

[realms]
    {realm} = {{
        kdc = {kdc}
        admin_server = {kdc}
    }}
"""
        with open(conf_path, "w") as f:
            f.write(content)

    return conf_path
