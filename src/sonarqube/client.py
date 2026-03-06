"""
SonarQube REST API client.

Provides helpers for fetching code quality measures, quality gate status,
and deriving project keys from repository metadata.
"""

import logging
import re
from typing import Any

import requests

logger = logging.getLogger(__name__)


def _auth_headers(config: dict) -> dict[str, str]:
    """Return authorization headers for SonarQube REST calls."""
    token = config.get("token", "")
    return {"Authorization": f"Bearer {token}"}


def fetch_measures(
    config: dict,
    project_key: str,
) -> dict[str, Any]:
    """Fetch component measures from SonarQube.

    Queries ``GET /api/measures/component`` for the given project key and
    returns a flat dict mapping metric name to its value (cast to float
    where possible).
    """
    base_url = config.get("base_url", "").rstrip("/")
    if not base_url or not project_key:
        return {}

    metric_keys = ",".join([
        "coverage",
        "line_coverage",
        "branch_coverage",
        "bugs",
        "vulnerabilities",
        "code_smells",
        "ncloc",
        "duplicated_lines_density",
    ])

    url = f"{base_url}/api/measures/component"
    params = {
        "component": project_key,
        "metricKeys": metric_keys,
    }

    try:
        resp = requests.get(
            url,
            params=params,
            headers=_auth_headers(config),
            verify=config.get("verify_ssl", False),
            timeout=config.get("timeout", 30),
        )
        resp.raise_for_status()
        data = resp.json()

        measures = {}
        for m in data.get("component", {}).get("measures", []):
            metric = m.get("metric", "")
            value = m.get("value", "")
            try:
                measures[metric] = float(value)
            except (ValueError, TypeError):
                measures[metric] = value
        return measures
    except Exception as exc:
        logger.error("SonarQube fetch_measures failed for %s: %s", project_key, exc)
        return {}


def fetch_quality_gate(
    config: dict,
    project_key: str,
) -> dict[str, Any]:
    """Fetch quality gate status from SonarQube.

    Queries ``GET /api/qualitygates/project_status`` and returns a dict
    with ``status`` (OK/WARN/ERROR) and ``conditions`` list.
    """
    base_url = config.get("base_url", "").rstrip("/")
    if not base_url or not project_key:
        return {}

    url = f"{base_url}/api/qualitygates/project_status"
    params = {"projectKey": project_key}

    try:
        resp = requests.get(
            url,
            params=params,
            headers=_auth_headers(config),
            verify=config.get("verify_ssl", False),
            timeout=config.get("timeout", 30),
        )
        resp.raise_for_status()
        data = resp.json()

        project_status = data.get("projectStatus", {})
        return {
            "status": project_status.get("status", "NONE"),
            "conditions": project_status.get("conditions", []),
        }
    except Exception as exc:
        logger.error("SonarQube fetch_quality_gate failed for %s: %s", project_key, exc)
        return {}


def derive_project_key(
    config: dict,
    repo_url: str,
    repo_name: str,
) -> str:
    """Derive SonarQube project key from config pattern or repo name.

    If ``project_key_pattern`` is set in config, substitutes ``{repo_name}``
    into it.  Otherwise falls back to a sanitised version of the repo name.
    """
    pattern = config.get("project_key_pattern", "")
    if pattern:
        name = repo_name or repo_url.rstrip("/").split("/")[-1].replace(".git", "")
        return pattern.replace("{repo_name}", name)

    # Fallback: derive from repo URL or name
    name = repo_name or repo_url.rstrip("/").split("/")[-1].replace(".git", "")
    # Sanitise: replace non-alphanumeric (except . - _) with _
    return re.sub(r"[^a-zA-Z0-9._-]", "_", name)
