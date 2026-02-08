"""
Configuration loader for autonomous code generation.
Reads config.ini and provides typed access to settings.
"""

import configparser
import os
from pathlib import Path
from typing import Optional


def load_config(config_path: str = "config.ini") -> dict:
    """Load and parse config.ini, resolving environment variables."""
    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    parser = configparser.ConfigParser()
    parser.read(config_path)

    def get(section: str, key: str, fallback: str = "") -> str:
        try:
            return parser.get(section, key, fallback=fallback).strip()
        except (configparser.NoSectionError, configparser.NoOptionError):
            return fallback

    def get_bool(section: str, key: str, fallback: bool = False) -> bool:
        val = get(section, key, str(fallback)).lower()
        return val in ("true", "yes", "1", "on")

    # Resolve credentials from env if configured
    cred_section = "github_config" if parser.has_section("github_config") else "credentials"
    use_env = get_bool(cred_section, "use_env", True)
    auth_token = get(cred_section, "auth_token")
    if auth_token and auth_token.startswith("<") and auth_token.endswith(">"):
        auth_token = ""  # Treat placeholder as empty

    if use_env and not auth_token:
        platform = get("repository", "platform", "github").lower()
        if platform == "github":
            auth_token = os.environ.get("GITHUB_TOKEN", "")
        elif platform == "bitbucket":
            auth_token = os.environ.get("BITBUCKET_APP_PASSWORD", "")

    api_key = get("ai", "api_key")
    if api_key and api_key.startswith("<") and api_key.endswith(">"):
        api_key = ""  # Treat placeholder as empty
    api_key = api_key or os.environ.get("OPENAI_API_KEY", "")

    return {
        "repository": {
            "platform": get("repository", "platform", "github").lower(),
            "repo_url": get("repository", "repo_url"),
            "base_branch": get("repository", "base_branch", "main") or "main",
            "feature_branch": get("repository", "feature_branch"),
        },
        "github_config": {
            "auth_token": auth_token,
        },
        "ai": {
            "api_key": api_key,
            "model": get("ai", "model", "gpt-4o"),
            "verbose": get_bool("ai", "verbose", False),
        },
        "workflow": {
            "work_dir": get("workflow", "work_dir", "./workspace"),
            "cleanup_after_pr": get_bool("workflow", "cleanup_after_pr", False),
            "grep_patterns": get("workflow", "grep_patterns", ""),
            "reference_pr": get("workflow", "reference_pr", ""),
            "use_agent": get_bool("workflow", "use_agent", False),
        },
        "testing": {
            "run_tests": get_bool("testing", "run_tests", True) if parser.has_section("testing") else True,
            "max_regenerate_attempts": int(get("testing", "max_regenerate_attempts", "3") or "3") if parser.has_section("testing") else 3,
            "test_timeout": int(get("testing", "test_timeout", "120") or "120") if parser.has_section("testing") else 120,
            "testing_strategy": get("testing", "testing_strategy", "auto").lower().strip() or "auto" if parser.has_section("testing") else "auto",
        },
        "consciousness": {
            "backend": get("consciousness", "backend", "file").lower() if parser.has_section("consciousness") else "file",
            "cache_dir": get("consciousness", "cache_dir", ".consciousness") if parser.has_section("consciousness") else ".consciousness",
            "max_age_hours": float(get("consciousness", "max_age_hours", "24") or "24") if parser.has_section("consciousness") else 24.0,
            "opensearch_url": get("consciousness", "opensearch_url", "") if parser.has_section("consciousness") else "",
            "opensearch_index": get("consciousness", "opensearch_index", "code_consciousness") if parser.has_section("consciousness") else "code_consciousness",
        },
    }


def _parse_reference_pr_from_content(content: str) -> tuple[str, str]:
    """
    Extract reference PR URL from changes content if present.
    Returns (content_without_reference_line, reference_pr_url).
    Supports: # Reference PR: https://..., reference_pr: https://...
    """
    import re
    # Match: # Reference PR: url, reference_pr: url, Reference PR: url
    pattern = r"^(?:#\s*)?(?:reference_pr|Reference\s+PR)\s*:\s*(https?://[^\s#]+)"
    for line in content.splitlines():
        m = re.search(pattern, line, re.I)
        if m:
            url = m.group(1).rstrip(")")
            # Remove this line from content
            new_content = content.replace(line, "").strip()
            # Clean up double newlines
            new_content = re.sub(r"\n{3,}", "\n\n", new_content)
            return new_content, url
    return content, ""


def parse_testing_strategy_from_changes(content: str) -> Optional[str]:
    """
    Parse # Testing strategy: bdd|contract|integration|unit|e2e from changes content.
    Returns strategy string or None if not specified.
    """
    import re
    for line in content.splitlines():
        m = re.search(r"#\s*Testing\s+strategy\s*:\s*(\w+)", line, re.I)
        if m:
            return m.group(1).lower()
    return None


def load_changes(changes_path: str = "changes.txt") -> str:
    """Load requirement specification from changes.txt."""
    changes_path = Path(changes_path)
    if not changes_path.exists():
        raise FileNotFoundError(f"Changes file not found: {changes_path}")
    return changes_path.read_text(encoding="utf-8")


def load_changes_with_reference(changes_path: str = "changes.txt") -> tuple[str, str]:
    """
    Load changes.txt and parse optional reference PR from it.
    Returns (requirements, reference_pr_url). reference_pr_url is empty if not specified.
    """
    raw = load_changes(changes_path)
    return _parse_reference_pr_from_content(raw)
