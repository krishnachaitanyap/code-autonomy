"""
JIRA client for code-autonomy integration.

Authenticates via OAuth (ADFS), searches for stories labeled for the agent,
and provides helpers to comment on and transition issues.

All functions read from config["jira"]. Credentials fall back to
JIRA_USERNAME / JIRA_PASSWORD environment variables.
"""

import logging
import os
from typing import Any

import requests
from urllib3.exceptions import InsecureRequestWarning

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _jira_cfg(config: dict) -> dict:
    """Extract the jira section from config, raising if missing."""
    cfg = config.get("jira")
    if not cfg:
        raise ValueError(
            "Missing [jira] section in config.ini. "
            "Copy the [jira] block from config.example.ini and fill in your values."
        )
    return cfg


def _resolve_credentials(cfg: dict) -> tuple[str, str]:
    """Return (username, password), falling back to env vars."""
    username = cfg.get("username") or os.environ.get("JIRA_USERNAME", "")
    password = cfg.get("password") or os.environ.get("JIRA_PASSWORD", "")
    return username, password


def _session(cfg: dict) -> requests.Session:
    """Build a requests.Session with SSL / timeout defaults."""
    s = requests.Session()
    if not cfg.get("verify_ssl", False):
        s.verify = False
        # Suppress only the specific InsecureRequestWarning
        requests.packages.urllib3.disable_warnings(InsecureRequestWarning)  # type: ignore[attr-defined]
    return s


# ---------------------------------------------------------------------------
# OAuth token
# ---------------------------------------------------------------------------

def get_jira_token(config: dict) -> str:
    """Obtain a bearer token from the ADFS / IDA token endpoint."""
    cfg = _jira_cfg(config)
    ida_url = cfg.get("ida_url")
    if not ida_url:
        raise ValueError("jira.ida_url is required for OAuth token retrieval")

    username, password = _resolve_credentials(cfg)
    if not username or not password:
        raise ValueError(
            "JIRA credentials required. Set username/password in [jira] config "
            "or export JIRA_USERNAME / JIRA_PASSWORD env vars."
        )

    payload = {
        "grant_type": cfg.get("grant_type", "password"),
        "username": username,
        "password": password,
        "resource": cfg.get("resource", ""),
        "client_id": cfg.get("client_id", ""),
    }

    timeout = int(cfg.get("timeout", 30))
    session = _session(cfg)

    resp = session.post(ida_url, data=payload, timeout=timeout)
    resp.raise_for_status()

    token = resp.json().get("access_token")
    if not token:
        raise RuntimeError("ADFS response did not contain an access_token")
    return token


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search_jira_issues(
    config: dict,
    jql: str,
    fields: list[str] | None = None,
    max_results: int = 50,
    token: str | None = None,
) -> list[dict[str, Any]]:
    """
    Run a JQL search and return the list of issue dicts.

    If *token* is not provided, one will be fetched via get_jira_token().
    """
    cfg = _jira_cfg(config)
    base_url = cfg.get("base_url", "").rstrip("/")
    if not base_url:
        raise ValueError("jira.base_url is required")

    if token is None:
        token = get_jira_token(config)

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    payload: dict[str, Any] = {
        "jql": jql,
        "maxResults": max_results,
    }
    if fields:
        payload["fields"] = fields

    timeout = int(cfg.get("timeout", 30))
    session = _session(cfg)

    resp = session.post(
        f"{base_url}/search",
        json=payload,
        headers=headers,
        timeout=timeout,
    )
    resp.raise_for_status()

    return resp.json().get("issues", [])


# ---------------------------------------------------------------------------
# Fetch agent stories
# ---------------------------------------------------------------------------

def fetch_agent_stories(config: dict, token: str | None = None) -> list[dict[str, Any]]:
    """
    Query JIRA for stories labeled for the code agent and return normalised
    dicts with keys: key, summary, description, acceptance_criteria.
    """
    cfg = _jira_cfg(config)
    project_key = cfg.get("project_key", "")
    agent_label = cfg.get("agent_label", "code-autonomy")
    ac_field = cfg.get("acceptance_criteria_field", "customfield_11110")
    max_stories = int(cfg.get("max_stories", 50))

    jql_parts = [f'labels = "{agent_label}"']
    if project_key:
        jql_parts.insert(0, f"project = {project_key}")
    jql_parts.append("status != Done")
    jql = " AND ".join(jql_parts)

    fields = ["summary", "description", ac_field]
    raw_issues = search_jira_issues(
        config,
        jql=jql,
        fields=fields,
        max_results=max_stories,
        token=token,
    )

    stories: list[dict[str, Any]] = []
    for issue in raw_issues:
        f = issue.get("fields", {})
        stories.append({
            "key": issue.get("key", ""),
            "summary": f.get("summary", ""),
            "description": f.get("description") or "",
            "acceptance_criteria": f.get(ac_field) or "",
        })

    return stories


# ---------------------------------------------------------------------------
# Comment
# ---------------------------------------------------------------------------

def add_jira_comment(
    config: dict,
    issue_key: str,
    comment: str,
    token: str | None = None,
) -> None:
    """Post a comment on a JIRA issue."""
    cfg = _jira_cfg(config)
    base_url = cfg.get("base_url", "").rstrip("/")
    if not base_url:
        raise ValueError("jira.base_url is required")

    if token is None:
        token = get_jira_token(config)

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    timeout = int(cfg.get("timeout", 30))
    session = _session(cfg)

    resp = session.post(
        f"{base_url}/issue/{issue_key}/comment",
        json={"body": comment},
        headers=headers,
        timeout=timeout,
    )
    resp.raise_for_status()


# ---------------------------------------------------------------------------
# Transition
# ---------------------------------------------------------------------------

def transition_jira_issue(
    config: dict,
    issue_key: str,
    transition_name: str,
    token: str | None = None,
) -> bool:
    """
    Move a JIRA issue to a new status by transition name.

    Returns True if the transition was found and executed, False otherwise.
    """
    cfg = _jira_cfg(config)
    base_url = cfg.get("base_url", "").rstrip("/")
    if not base_url:
        raise ValueError("jira.base_url is required")

    if token is None:
        token = get_jira_token(config)

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    timeout = int(cfg.get("timeout", 30))
    session = _session(cfg)

    # Fetch available transitions
    resp = session.get(
        f"{base_url}/issue/{issue_key}/transitions",
        headers=headers,
        timeout=timeout,
    )
    resp.raise_for_status()

    transitions = resp.json().get("transitions", [])
    target = None
    for t in transitions:
        if t.get("name", "").lower() == transition_name.lower():
            target = t
            break

    if target is None:
        available = [t.get("name") for t in transitions]
        logger.warning(
            "Transition '%s' not found for %s. Available: %s",
            transition_name, issue_key, available,
        )
        return False

    resp = session.post(
        f"{base_url}/issue/{issue_key}/transitions",
        json={"transition": {"id": target["id"]}},
        headers=headers,
        timeout=timeout,
    )
    resp.raise_for_status()
    return True
