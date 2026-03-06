"""
Splunk REST API client.

Provides helpers for authenticating, running one-shot and async searches,
and listing/running saved searches via the Splunk REST API.
"""

import logging
import time
import xml.etree.ElementTree as ET
from typing import Any, Optional

import requests

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Session key cache (avoid re-authenticating every call)
# ---------------------------------------------------------------------------

_session_cache: dict[str, tuple[str, float]] = {}
_SESSION_TTL = 55 * 60  # 55 minutes (Splunk tokens last 60 min)


def get_session_key(config: dict) -> str:
    """Authenticate against Splunk and return a session key.

    The key is cached for 55 minutes to avoid repeated auth round-trips.
    """
    base_url = config["base_url"].rstrip("/")
    cache_key = f"{base_url}:{config.get('username', '')}"

    cached = _session_cache.get(cache_key)
    if cached:
        key, ts = cached
        if time.time() - ts < _SESSION_TTL:
            return key

    url = f"{base_url}/services/auth/login"
    resp = requests.post(
        url,
        data={
            "username": config["username"],
            "password": config["password"],
            "output_mode": "json",
        },
        verify=config.get("verify_ssl", False),
        timeout=config.get("timeout", 30),
    )
    resp.raise_for_status()
    key = resp.json()["sessionKey"]
    _session_cache[cache_key] = (key, time.time())
    return key


def _auth_headers(config: dict) -> dict[str, str]:
    """Return authorization headers for Splunk REST calls."""
    key = get_session_key(config)
    return {"Authorization": f"Splunk {key}"}


# ---------------------------------------------------------------------------
# One-shot search (blocking, best for small result sets)
# ---------------------------------------------------------------------------

def run_search_oneshot(
    config: dict,
    spl: str,
    earliest: Optional[str] = None,
    latest: Optional[str] = None,
    max_results: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Run a one-shot (blocking) search via ``/search/jobs/export``.

    Returns a list of result dicts.
    """
    base_url = config["base_url"].rstrip("/")
    app = config.get("app", "search")
    url = f"{base_url}/servicesNS/nobody/{app}/search/jobs/export"

    params = {
        "search": spl if spl.strip().startswith("|") else f"search {spl}",
        "earliest_time": earliest or config.get("default_earliest", "-24h"),
        "latest_time": latest or config.get("default_latest", "now"),
        "output_mode": "json",
        "count": max_results or config.get("max_results", 1000),
    }

    resp = requests.get(
        url,
        params=params,
        headers=_auth_headers(config),
        verify=config.get("verify_ssl", False),
        timeout=config.get("timeout", 30) * 2,  # exports can be slow
        stream=True,
    )
    resp.raise_for_status()

    # The export endpoint returns NDJSON (one JSON object per line)
    import json

    results = []
    for line in resp.iter_lines(decode_unicode=True):
        if not line:
            continue
        try:
            obj = json.loads(line)
            if "result" in obj:
                results.append(obj["result"])
        except json.JSONDecodeError:
            continue

    return results


# ---------------------------------------------------------------------------
# Async search (create job → poll → fetch results)
# ---------------------------------------------------------------------------

def run_search_async(
    config: dict,
    spl: str,
    earliest: Optional[str] = None,
    latest: Optional[str] = None,
    max_results: Optional[int] = None,
    poll_interval: float = 2.0,
    max_wait: float = 300.0,
) -> list[dict[str, Any]]:
    """Run an async search: create job, poll until done, fetch results."""
    base_url = config["base_url"].rstrip("/")
    app = config.get("app", "search")
    headers = _auth_headers(config)
    verify = config.get("verify_ssl", False)
    timeout = config.get("timeout", 30)

    # 1. Create job
    create_url = f"{base_url}/servicesNS/nobody/{app}/search/jobs"
    data = {
        "search": spl if spl.strip().startswith("|") else f"search {spl}",
        "earliest_time": earliest or config.get("default_earliest", "-24h"),
        "latest_time": latest or config.get("default_latest", "now"),
        "output_mode": "json",
    }
    resp = requests.post(create_url, data=data, headers=headers, verify=verify, timeout=timeout)
    resp.raise_for_status()
    sid = resp.json().get("sid")
    if not sid:
        raise RuntimeError("Splunk did not return a search job SID")

    # 2. Poll for completion
    status_url = f"{base_url}/servicesNS/nobody/{app}/search/jobs/{sid}"
    elapsed = 0.0
    while elapsed < max_wait:
        time.sleep(poll_interval)
        elapsed += poll_interval
        r = requests.get(
            status_url,
            params={"output_mode": "json"},
            headers=headers, verify=verify, timeout=timeout,
        )
        r.raise_for_status()
        entry = r.json().get("entry", [{}])[0]
        content = entry.get("content", {})
        if content.get("isDone"):
            break
    else:
        raise TimeoutError(f"Splunk search job {sid} did not complete within {max_wait}s")

    # 3. Fetch results
    max_count = max_results or config.get("max_results", 1000)
    results_url = f"{base_url}/servicesNS/nobody/{app}/search/jobs/{sid}/results"
    r = requests.get(
        results_url,
        params={"output_mode": "json", "count": max_count},
        headers=headers, verify=verify, timeout=timeout,
    )
    r.raise_for_status()
    return r.json().get("results", [])


# ---------------------------------------------------------------------------
# Saved searches
# ---------------------------------------------------------------------------

def list_saved_searches(config: dict) -> list[dict[str, str]]:
    """List available saved searches/reports.

    Returns a list of ``{name, description, search}`` dicts.
    """
    base_url = config["base_url"].rstrip("/")
    app = config.get("app", "search")
    url = f"{base_url}/servicesNS/nobody/{app}/saved/searches"

    resp = requests.get(
        url,
        params={"output_mode": "json", "count": 100},
        headers=_auth_headers(config),
        verify=config.get("verify_ssl", False),
        timeout=config.get("timeout", 30),
    )
    resp.raise_for_status()

    entries = resp.json().get("entry", [])
    results = []
    for entry in entries:
        content = entry.get("content", {})
        results.append({
            "name": entry.get("name", ""),
            "description": content.get("description", ""),
            "search": content.get("search", ""),
        })
    return results


def run_saved_search(
    config: dict,
    name: str,
    max_results: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Dispatch a saved search by name, poll until done, and return results."""
    base_url = config["base_url"].rstrip("/")
    app = config.get("app", "search")
    headers = _auth_headers(config)
    verify = config.get("verify_ssl", False)
    timeout = config.get("timeout", 30)

    # Dispatch
    dispatch_url = f"{base_url}/servicesNS/nobody/{app}/saved/searches/{requests.utils.quote(name, safe='')}/dispatch"
    resp = requests.post(
        dispatch_url,
        data={"output_mode": "json"},
        headers=headers, verify=verify, timeout=timeout,
    )
    resp.raise_for_status()
    sid = resp.json().get("sid") or resp.text.strip()
    if not sid:
        raise RuntimeError(f"Splunk did not return SID for saved search '{name}'")

    # Poll
    status_url = f"{base_url}/servicesNS/nobody/{app}/search/jobs/{sid}"
    for _ in range(150):
        time.sleep(2.0)
        r = requests.get(
            status_url,
            params={"output_mode": "json"},
            headers=headers, verify=verify, timeout=timeout,
        )
        r.raise_for_status()
        entry = r.json().get("entry", [{}])[0]
        if entry.get("content", {}).get("isDone"):
            break
    else:
        raise TimeoutError(f"Saved search '{name}' did not complete within 300s")

    # Fetch results
    max_count = max_results or config.get("max_results", 1000)
    results_url = f"{base_url}/servicesNS/nobody/{app}/search/jobs/{sid}/results"
    r = requests.get(
        results_url,
        params={"output_mode": "json", "count": max_count},
        headers=headers, verify=verify, timeout=timeout,
    )
    r.raise_for_status()
    return r.json().get("results", [])
