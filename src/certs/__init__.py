"""
JKS / PKCS12 certificate inspection — tool schemas, dispatcher, and CERTS_TOOLS list.

Provides three agent tools:

    cert_find       — find all keystore files (.jks, .p12, .keystore, etc.) in the repo
    cert_list       — list aliases / entries in a keystore
    cert_details    — full certificate info: expiry, subject, issuer, fingerprints
"""

import json
import logging
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Common keystore extensions
_KEYSTORE_EXTENSIONS = {".jks", ".p12", ".pfx", ".keystore", ".truststore", ".pkcs12"}

# Default passwords to try (in order)
_DEFAULT_PASSWORDS = ["changeit", "changeme", "password", ""]


# ---------------------------------------------------------------------------
# Helper: build an OpenAI function-calling tool schema
# ---------------------------------------------------------------------------

def _tool(name: str, description: str, params: dict, required: list[str] | None = None) -> dict:
    schema: dict = {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": params},
        },
    }
    if required:
        schema["function"]["parameters"]["required"] = required
    return schema


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

_CERT_FIND_SCHEMA = _tool(
    "cert_find",
    "Find all Java KeyStore and PKCS12 certificate files (.jks, .p12, .pfx, "
    ".keystore, .truststore) in the repository. Call this FIRST to discover "
    "which keystores exist before listing or inspecting certificates.",
    {
        "path": {
            "type": "string",
            "description": "Subdirectory to search (relative to repo root). "
            "Omit to search the entire repository.",
        },
    },
)

_CERT_LIST_SCHEMA = _tool(
    "cert_list",
    "List all aliases (certificate entries) in a Java KeyStore or PKCS12 file. "
    "Returns alias names, types, and creation dates.",
    {
        "keystore_path": {
            "type": "string",
            "description": "Path to the keystore file (relative to repo root).",
        },
        "password": {
            "type": "string",
            "description": "Keystore password. If omitted, common defaults are tried "
            "(changeit, changeme, password, empty).",
        },
        "storetype": {
            "type": "string",
            "description": "Store type: JKS, PKCS12, etc. Auto-detected from extension if omitted.",
        },
    },
    required=["keystore_path"],
)

_CERT_DETAILS_SCHEMA = _tool(
    "cert_details",
    "Get full certificate details for a specific alias in a keystore: subject, "
    "issuer, validity period (not-before / not-after), serial number, and "
    "fingerprints (SHA-256, SHA-1).",
    {
        "keystore_path": {
            "type": "string",
            "description": "Path to the keystore file (relative to repo root).",
        },
        "alias": {
            "type": "string",
            "description": "Certificate alias to inspect (from cert_list results).",
        },
        "password": {
            "type": "string",
            "description": "Keystore password. If omitted, common defaults are tried.",
        },
        "storetype": {
            "type": "string",
            "description": "Store type: JKS, PKCS12, etc. Auto-detected from extension if omitted.",
        },
    },
    required=["keystore_path", "alias"],
)

CERTS_TOOLS = [
    _CERT_FIND_SCHEMA,
    _CERT_LIST_SCHEMA,
    _CERT_DETAILS_SCHEMA,
]

CERTS_TOOL_NAMES = {
    "cert_find",
    "cert_list",
    "cert_details",
}


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------

def _safe_path(repo_root: str, relative: str) -> Optional[str]:
    """Resolve *relative* under *repo_root* and verify it doesn't escape."""
    base = Path(repo_root).resolve()
    target = (base / relative).resolve()
    if not str(target).startswith(str(base)):
        return None
    return str(target)


# ---------------------------------------------------------------------------
# Store-type and password helpers
# ---------------------------------------------------------------------------

def _detect_storetype(path: str) -> str:
    """Guess the storetype from file extension."""
    ext = Path(path).suffix.lower()
    if ext in (".p12", ".pfx", ".pkcs12"):
        return "PKCS12"
    return "JKS"


def _try_passwords(
    keystore_path: str,
    storetype: str,
    extra_args: list[str] | None = None,
    explicit_password: str | None = None,
) -> tuple[Optional[str], Optional[str]]:
    """Try passwords against keytool; return (output, password_used) or (None, None)."""
    passwords = [explicit_password] if explicit_password is not None else list(_DEFAULT_PASSWORDS)
    for pwd in passwords:
        cmd = [
            "keytool", "-list",
            "-keystore", keystore_path,
            "-storepass", pwd,
            "-storetype", storetype,
        ]
        if extra_args:
            cmd.extend(extra_args)
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0:
                return result.stdout, pwd
        except subprocess.TimeoutExpired:
            continue
    return None, None


# ---------------------------------------------------------------------------
# Result formatting
# ---------------------------------------------------------------------------

def _structured_table(title: str, rows: list[dict]) -> str:
    """Build a structured result envelope + plain markdown table."""
    if not rows:
        return json.dumps({
            "__structured": True, "format": "table",
            "title": title, "columns": [], "rows": [], "total": 0,
        })

    columns = list(rows[0].keys())
    clean_rows = [{c: r.get(c, "") for c in columns} for r in rows]

    envelope = json.dumps({
        "__structured": True,
        "format": "table",
        "title": title,
        "columns": columns,
        "rows": clean_rows,
        "total": len(clean_rows),
    })

    # Plain markdown table for the LLM to reason about
    md_lines = [f"\n\n**{title}** ({len(clean_rows)} rows)\n"]
    md_lines.append("| " + " | ".join(columns) + " |")
    md_lines.append("| " + " | ".join("---" for _ in columns) + " |")
    for row in clean_rows[:20]:
        vals = [str(row.get(c, ""))[:80] for c in columns]
        md_lines.append("| " + " | ".join(vals) + " |")
    if len(clean_rows) > 20:
        md_lines.append(f"\n... and {len(clean_rows) - 20} more rows")

    return envelope + "\n".join(md_lines)


# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------

def execute_certs_tool(repo_root: str, tool_name: str, args: dict) -> str:
    """Execute a certificate inspection tool and return the result string."""
    # Check keytool availability once
    if not shutil.which("keytool"):
        return (
            "Error: keytool not found. Ensure a JDK is installed and "
            "keytool is on the PATH."
        )

    try:
        if tool_name == "cert_find":
            return _execute_find(repo_root, args)
        if tool_name == "cert_list":
            return _execute_list(repo_root, args)
        if tool_name == "cert_details":
            return _execute_details(repo_root, args)
        return f"Error: Unknown certs tool: {tool_name}"
    except Exception as exc:
        logger.error("Certs tool %s failed: %s", tool_name, exc, exc_info=True)
        return f"Error: {tool_name} failed — {exc}"


# ---------------------------------------------------------------------------
# cert_find — locate keystore files
# ---------------------------------------------------------------------------

def _execute_find(repo_root: str, args: dict) -> str:
    subdir = args.get("path", "")
    if subdir:
        search_root = _safe_path(repo_root, subdir)
        if search_root is None:
            return "Error: path escapes the repository root."
    else:
        search_root = repo_root

    found: list[dict] = []
    for dirpath, _dirnames, filenames in os.walk(search_root):
        for fname in filenames:
            ext = Path(fname).suffix.lower()
            if ext in _KEYSTORE_EXTENSIONS:
                full = os.path.join(dirpath, fname)
                rel = os.path.relpath(full, repo_root)
                size_kb = round(os.path.getsize(full) / 1024, 1)
                storetype = _detect_storetype(fname)
                found.append({
                    "File": rel,
                    "Type": storetype,
                    "Size (KB)": str(size_kb),
                })

    if not found:
        search_label = subdir if subdir else "repository"
        return f"No keystore files found in {search_label}."

    return _structured_table("Keystore Files", found)


# ---------------------------------------------------------------------------
# cert_list — list aliases in a keystore
# ---------------------------------------------------------------------------

_ALIAS_RE = re.compile(
    r"^(.+?),\s*(\w[\w\s]*\w|\w),\s*(.+)$", re.MULTILINE,
)


def _execute_list(repo_root: str, args: dict) -> str:
    ks_rel = args.get("keystore_path", "")
    if not ks_rel:
        return "Error: keystore_path is required."

    ks_path = _safe_path(repo_root, ks_rel)
    if ks_path is None:
        return "Error: keystore_path escapes the repository root."
    if not os.path.isfile(ks_path):
        return f"Error: keystore file not found: {ks_rel}"

    storetype = args.get("storetype") or _detect_storetype(ks_path)
    explicit_pwd = args.get("password")

    output, pwd_used = _try_passwords(ks_path, storetype, explicit_password=explicit_pwd)
    if output is None:
        if explicit_pwd is not None:
            return f"Error: incorrect password for {ks_rel}."
        return (
            f"Error: could not open {ks_rel} — none of the default passwords "
            f"worked (changeit, changeme, password, empty). "
            f"Please provide the password explicitly."
        )

    # Parse keytool -list output
    rows: list[dict] = []
    for m in _ALIAS_RE.finditer(output):
        alias = m.group(1).strip()
        entry_type = m.group(2).strip()
        date_str = m.group(3).strip()
        # Skip header noise
        if alias.lower().startswith("keystore type") or alias.lower().startswith("keystore provider"):
            continue
        rows.append({
            "Alias": alias,
            "Entry Type": entry_type,
            "Date": date_str,
        })

    if not rows:
        return f"Keystore {ks_rel} is empty (no aliases found)."

    return _structured_table(f"Aliases in {ks_rel}", rows)


# ---------------------------------------------------------------------------
# cert_details — full cert info for one alias
# ---------------------------------------------------------------------------

def _execute_details(repo_root: str, args: dict) -> str:
    ks_rel = args.get("keystore_path", "")
    alias = args.get("alias", "")
    if not ks_rel:
        return "Error: keystore_path is required."
    if not alias:
        return "Error: alias is required."

    ks_path = _safe_path(repo_root, ks_rel)
    if ks_path is None:
        return "Error: keystore_path escapes the repository root."
    if not os.path.isfile(ks_path):
        return f"Error: keystore file not found: {ks_rel}"

    storetype = args.get("storetype") or _detect_storetype(ks_path)
    explicit_pwd = args.get("password")

    # Use -v flag for verbose output with full cert details
    passwords = [explicit_pwd] if explicit_pwd is not None else list(_DEFAULT_PASSWORDS)
    output = None
    for pwd in passwords:
        cmd = [
            "keytool", "-list", "-v",
            "-keystore", ks_path,
            "-storepass", pwd,
            "-storetype", storetype,
            "-alias", alias,
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if result.returncode == 0:
                output = result.stdout
                break
        except subprocess.TimeoutExpired:
            continue

    if output is None:
        if explicit_pwd is not None:
            return f"Error: could not read alias '{alias}' — incorrect password or alias not found."
        return (
            f"Error: could not read alias '{alias}' in {ks_rel} — "
            f"none of the default passwords worked. Please provide the password explicitly."
        )

    # Parse the verbose keytool output into structured fields
    details = _parse_cert_verbose(output)
    details["Alias"] = alias
    details["Keystore"] = ks_rel

    # Check expiry status
    not_after = details.get("Not After", "")
    if not_after:
        try:
            # keytool date format varies; try common formats
            for fmt in ("%a %b %d %H:%M:%S %Z %Y", "%b %d, %Y", "%Y-%m-%d"):
                try:
                    expiry = datetime.strptime(not_after.strip(), fmt)
                    days_left = (expiry - datetime.now()).days
                    if days_left < 0:
                        details["Status"] = f"EXPIRED ({abs(days_left)} days ago)"
                    elif days_left < 30:
                        details["Status"] = f"EXPIRING SOON ({days_left} days)"
                    else:
                        details["Status"] = f"Valid ({days_left} days remaining)"
                    break
                except ValueError:
                    continue
        except Exception:
            pass

    rows = [details]
    return _structured_table(f"Certificate: {alias}", rows)


def _parse_cert_verbose(output: str) -> dict:
    """Parse keytool -list -v output into a dict of key fields."""
    info: dict = {}
    field_map = {
        "Owner": "Subject",
        "Issuer": "Issuer",
        "Serial number": "Serial Number",
        "Valid from": "Not Before",
        "until": "Not After",
        "SHA256": "SHA-256 Fingerprint",
        "SHA1": "SHA-1 Fingerprint",
        "Signature algorithm name": "Signature Algorithm",
        "Subject Public Key Algorithm": "Key Algorithm",
        "Entry type": "Entry Type",
        "Creation date": "Creation Date",
    }

    for line in output.splitlines():
        line = line.strip()
        # Handle "Valid from: ... until: ..." on one line
        if "Valid from:" in line and "until:" in line:
            parts = line.split("until:")
            from_part = parts[0].replace("Valid from:", "").strip()
            until_part = parts[1].strip() if len(parts) > 1 else ""
            info["Not Before"] = from_part
            info["Not After"] = until_part
            continue

        for key, label in field_map.items():
            if line.lower().startswith(key.lower() + ":"):
                val = line.split(":", 1)[1].strip()
                info[label] = val
                break
            # Handle fingerprint lines like "SHA256: AB:CD:..."
            if key in ("SHA256", "SHA1") and key in line.upper():
                idx = line.upper().find(key)
                if idx >= 0:
                    val = line[idx:].split(":", 1)
                    if len(val) > 1:
                        info[label] = val[1].strip()
                    break

    return info
