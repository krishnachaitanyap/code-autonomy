"""
Fetch reference PR content for repetitive changes.
Use a previous PR as a template/pattern when making similar changes.
"""

import re
from typing import Optional


def parse_pr_url(url: str) -> Optional[tuple[str, int]]:
    """
    Parse GitHub PR URL into (owner/repo, pr_number).
    Supports: https://github.com/owner/repo/pull/123, github.com/owner/repo/pull/123
    """
    url = url.strip()
    # Match github.com/owner/repo/pull/123 or /pulls/123
    m = re.search(r"github\.com/([^/]+)/([^/]+)/pull[s]?/(\d+)", url, re.I)
    if m:
        return f"{m.group(1)}/{m.group(2)}", int(m.group(3))
    return None


def fetch_reference_pr(pr_url: str, token: str, max_diff_chars: int = 25000) -> Optional[str]:
    """
    Fetch PR title, body, and diff from GitHub. Returns formatted string for AI context.
    """
    import requests

    parsed = parse_pr_url(pr_url)
    if not parsed:
        return None

    owner_repo, pr_num = parsed
    headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}

    # Get PR details
    resp = requests.get(
        f"https://api.github.com/repos/{owner_repo}/pulls/{pr_num}",
        headers=headers,
    )
    if not resp.ok:
        return None

    pr = resp.json()
    title = pr.get("title", "")
    body = pr.get("body", "")

    # Get diff
    diff_headers = {**headers, "Accept": "application/vnd.github.v3.diff"}
    diff_resp = requests.get(
        f"https://api.github.com/repos/{owner_repo}/pulls/{pr_num}",
        headers=diff_headers,
    )
    diff = diff_resp.text if diff_resp.ok else ""

    if len(diff) > max_diff_chars:
        diff = diff[:max_diff_chars] + "\n... (diff truncated)"

    parts = [f"## Reference PR: {pr_url}", f"**Title:** {title}"]
    if body:
        body_trunc = body[:3000] + "..." if len(body) > 3000 else body
        parts.append(f"**Description:**\n{body_trunc}")
    if diff:
        parts.append(f"**Diff:**\n```diff\n{diff}\n```")

    return "\n\n".join(parts)


def get_reference_pr_context(pr_url: Optional[str], token: Optional[str]) -> str:
    """
    Fetch reference PR context if URL and token provided. Returns empty string on failure.
    """
    if not pr_url or not token or not token.strip():
        return ""

    result = fetch_reference_pr(pr_url, token)
    return result or ""
