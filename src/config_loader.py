"""
Configuration loader for autonomous code generation.
Reads config.ini and provides typed access to settings.
"""

import configparser
import json
import os
import re
from pathlib import Path
from typing import Optional, Union


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

    def get_int(section: str, key: str, fallback: int = 0) -> int:
        raw = get(section, key, str(fallback))
        try:
            return int(raw) if raw else fallback
        except ValueError:
            return fallback

    def get_float(section: str, key: str, fallback: float = 0.0) -> float:
        raw = get(section, key, str(fallback))
        try:
            return float(raw) if raw else fallback
        except ValueError:
            return fallback

    def get_list(section: str, key: str, fallback: str = "") -> list[str]:
        raw = get(section, key, fallback)
        return [p.strip() for p in raw.split(",") if p.strip()]

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
            auth_token = (
                os.environ.get("BITBUCKET_HTTP_ACCESS_TOKEN", "")
                or os.environ.get("BITBUCKET_APP_PASSWORD", "")
            )

    api_key = get("ai", "api_key")
    if api_key and api_key.startswith("<") and api_key.endswith(">"):
        api_key = ""  # Treat placeholder as empty
    provider = get("ai", "provider", "openai").lower() or "openai"
    api_key_env = get("ai", "api_key_env", "")
    if not api_key_env:
        api_key_env = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "gemini": "GEMINI_API_KEY",
            "google": "GEMINI_API_KEY",
        }.get(provider, "OPENAI_API_KEY")
    api_key = api_key or os.environ.get(api_key_env, "")

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
            "provider": provider,
            "api_key": api_key,
            "api_key_env": api_key_env,
            "model": get("ai", "model", "gpt-4o"),
            "temperature": get_float("ai", "temperature", 0.2),
            "base_url": get("ai", "base_url", ""),
            "verbose": get_bool("ai", "verbose", False),
            # Bedrock/cdao (when provider is bedrock or cdao)
            "aws_account_number": get("ai", "aws_account_number", ""),
            "aws_region": get("ai", "aws_region", "us-east-1"),
            "workspace_id": get("ai", "workspace_id", ""),
            "is_execution_role": get_bool("ai", "is_execution_role", False),
            # Azure OpenAI (when provider is azure)
            "endpoint": get("ai", "endpoint", ""),
            "deployment_name": get("ai", "deployment_name", ""),
            "api_version": get("ai", "api_version", "2024-02-15-preview"),
            "tenant_id": get("ai", "tenant_id", ""),
            "client_id": get("ai", "client_id", ""),
            "scope": get("ai", "scope", "https://cognitiveservices.azure.com/.default"),
            # S3 certificate auth (for Azure cert-based auth)
            "s3_bucket_name": get("ai", "s3_bucket_name", ""),
            "azure_cert_file_name": get("ai", "azure_cert_file_name", ""),
        },
        "workflow": {
            "work_dir": get("workflow", "work_dir", "./workspace"),
            "cleanup_after_pr": get_bool("workflow", "cleanup_after_pr", False),
            "grep_patterns": get("workflow", "grep_patterns", ""),
            "reference_pr": get("workflow", "reference_pr", ""),
            "use_agent": get_bool("workflow", "use_agent", False),
        },
        "testing": {
            "run_tests": get_bool("testing", "run_tests", True),
            "max_regenerate_attempts": get_int("testing", "max_regenerate_attempts", 3),
            "test_timeout": get_int("testing", "test_timeout", 120),
            "testing_strategy": get("testing", "testing_strategy", "auto").lower().strip() or "auto",
            "bdd_spec_path": get("testing", "bdd_spec_path", ""),
        },
        "consciousness": {
            "backend": get("consciousness", "backend", "file").lower(),
            "cache_dir": get("consciousness", "cache_dir", ".consciousness"),
            "max_age_hours": get_float("consciousness", "max_age_hours", 24.0),
            "opensearch_url": get("consciousness", "opensearch_url", ""),
            "opensearch_index": get("consciousness", "opensearch_index", "code_consciousness"),
        },
        "context": {
            "use_pipeline": get_bool("context", "use_pipeline", False),
            "grep_enricher": get_bool("context", "grep_enricher", True),
            "grep_from_requirements": get_bool("context", "grep_from_requirements", True),
            "similarity_enricher": get_bool("context", "similarity_enricher", False),
            "similarity_top_k": get_int("context", "similarity_top_k", 5),
            "call_graph_enricher": get_bool("context", "call_graph_enricher", False),
            "call_graph_depth": get_int("context", "call_graph_depth", 2),
            "max_files": get_int("context", "max_files", 30),
            "max_chars_per_file": get_int("context", "max_chars_per_file", 4000),
        },
        "agent": {
            "max_turns": get_int("agent", "max_turns", 50),
            "plan_max_turns": get_int("agent", "plan_max_turns", 30),
            "smart_summarization": get_bool("agent", "smart_summarization", True),
            "truncation_limit": get_int("agent", "truncation_limit", 100000),
            "show_activity": get_bool("agent", "show_activity", True),
            "command_allowlist_only": get_bool("agent", "command_allowlist_only", False),
            "allowed_command_prefixes": get_list("agent", "allowed_command_prefixes"),
            "blocked_commands": get_list("agent", "blocked_commands"),
            "skip_tests": get_bool("agent", "skip_tests", False),
            "circuit_breaker_threshold": get_int("agent", "circuit_breaker_threshold", 5),
            "circuit_breaker_timeout": get_float("agent", "circuit_breaker_timeout", 60.0),
            "rate_limit_max_tokens": get_float("agent", "rate_limit_max_tokens", 10.0),
            "rate_limit_refill_rate": get_float("agent", "rate_limit_refill_rate", 1.0),
            "summarization_budget": get_int("agent", "summarization_budget", 0),  # 0 = unlimited
            "testing_budget": get_int("agent", "testing_budget", 0),              # 0 = unlimited
            # Deadline nudges (advisory turn-budget hints)
            "nudge_enabled": get_bool("agent", "nudge_enabled", True),
            "explore_budget_pct": get_float("agent", "explore_budget_pct", 0.30),
            "soft_deadline_pct": get_float("agent", "soft_deadline_pct", 0.60),
            "hard_deadline_pct": get_float("agent", "hard_deadline_pct", 0.80),
        },
        "knowledge": {
            "backend": get("knowledge", "backend", "file").lower(),
            "storage_dir": get("knowledge", "storage_dir", ""),
            "opensearch_url": get("knowledge", "opensearch_url", ""),
            "opensearch_index": get("knowledge", "opensearch_index", "agent_knowledge"),
            "aws_region": get("knowledge", "aws_region", ""),
        },
        "bitbucket": {
            "enabled": get_bool("bitbucket", "enabled", False),
            "base_url": get("bitbucket", "base_url", ""),
            "user_token": get("bitbucket", "user_token", "") or os.environ.get("BITBUCKET_SERVER_TOKEN", ""),
            "clone_url": get("bitbucket", "clone_url", ""),
            "project_key": get("bitbucket", "project_key", ""),
            "repo_slug": get("bitbucket", "repo_slug", ""),
            "base_branch": get("bitbucket", "base_branch", "main") or "main",
            "verify_ssl": get_bool("bitbucket", "verify_ssl", False),
            "clone_protocol": get("bitbucket", "clone_protocol", "ssh").lower() or "ssh",
        },
        "jira": {
            "base_url": get("jira", "base_url", ""),
            "ida_url": get("jira", "ida_url", ""),
            "resource": get("jira", "resource", ""),
            "client_id": get("jira", "client_id", ""),
            "username": get("jira", "username", "") or os.environ.get("JIRA_USERNAME", ""),
            "password": get("jira", "password", "") or os.environ.get("JIRA_PASSWORD", ""),
            "grant_type": get("jira", "grant_type", "password"),
            "project_key": get("jira", "project_key", ""),
            "agent_label": get("jira", "agent_label", "code-autonomy"),
            "acceptance_criteria_field": get("jira", "acceptance_criteria_field", "customfield_11110"),
            "verify_ssl": get_bool("jira", "verify_ssl", False),
            "timeout": get_int("jira", "timeout", 30),
            "max_stories": get_int("jira", "max_stories", 50),
            "auto_transition_start": get_bool("jira", "auto_transition_start", True),
            "auto_transition_done": get_bool("jira", "auto_transition_done", False),
            "max_retries": get_int("jira", "max_retries", 2),
        },
        "tracing": {
            "enabled": get_bool("tracing", "enabled", True),
            "storage_dir": get("tracing", "storage_dir", ""),
        },
        "code_index": {
            "cache_dir": get("code_index", "cache_dir", ".code-index"),
            "max_age_hours": get_float("code_index", "max_age_hours", 24.0),
        },
        "opensearch": {
            "enabled": get_bool("opensearch", "enabled", False),
            "endpoint": get("opensearch", "endpoint", ""),
            "region": get("opensearch", "region", "us-east-1"),
            "aws_access_key_id": get("opensearch", "aws_access_key_id", "") or os.environ.get("AWS_ACCESS_KEY_ID", ""),
            "aws_secret_access_key": get("opensearch", "aws_secret_access_key", "") or os.environ.get("AWS_SECRET_ACCESS_KEY", ""),
            "index_name": get("opensearch", "index_name", "splunk-metadata"),
            "embedding_model": get("opensearch", "embedding_model", "text-embedding-3-small"),
            "verify_ssl": get_bool("opensearch", "verify_ssl", True),
            "timeout": get_int("opensearch", "timeout", 30),
        },
        "splunk": {
            "enabled": get_bool("splunk", "enabled", False),
            "base_url": get("splunk", "base_url", ""),
            "username": get("splunk", "username", "") or os.environ.get("SPLUNK_USERNAME", ""),
            "password": get("splunk", "password", "") or os.environ.get("SPLUNK_PASSWORD", ""),
            "app": get("splunk", "app", "search"),
            "default_earliest": get("splunk", "default_earliest", "-24h"),
            "default_latest": get("splunk", "default_latest", "now"),
            "verify_ssl": get_bool("splunk", "verify_ssl", False),
            "timeout": get_int("splunk", "timeout", 30),
            "max_results": get_int("splunk", "max_results", 1000),
        },
    }


def _parse_reference_pr_from_content(content: str) -> tuple[str, str]:
    """
    Extract reference PR URL from changes content if present.
    Returns (content_without_reference_line, reference_pr_url).
    Supports: # Reference PR: https://..., reference_pr: https://...
    """
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


def parse_framework_repo_from_changes(content: str) -> tuple[Optional[str], Optional[str]]:
    """
    Parse framework repo URL and branch from changes content.
    Supports:
      # Framework repo: https://github.com/org/framework.git
      # Framework: https://github.com/org/framework.git
      # Framework branch: main
    Returns (framework_repo_url, framework_branch). Either can be None.
    """
    url = None
    branch = None
    for line in content.splitlines():
        m = re.search(r"^(?:#\s*)?(?:Framework\s+repo|Framework)\s*:\s*(https?://[^\s#]+\.git)", line, re.I)
        if m:
            url = m.group(1).rstrip(")").strip()
            continue
        m = re.search(r"^(?:#\s*)?Framework\s+branch\s*:\s*(\w[\w\-/]*)", line, re.I)
        if m:
            branch = m.group(1).strip()
    return url, (branch or "main") if url else None


def _strip_framework_lines(content: str) -> str:
    """Remove framework meta lines from content."""
    lines = []
    for line in content.splitlines():
        if re.search(r"^(?:#\s*)?(?:Framework\s+repo|Framework)\s*:\s*https?://", line, re.I):
            continue
        if re.search(r"^(?:#\s*)?Framework\s+branch\s*:\s*\w", line, re.I):
            continue
        lines.append(line)
    result = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", result)


def parse_testing_strategy_from_changes(content: str) -> Optional[str]:
    """
    Parse # Testing strategy: bdd|contract|integration|unit|e2e from changes content.
    Returns strategy string or None if not specified.
    """
    for line in content.splitlines():
        m = re.search(r"#\s*Testing\s+strategy\s*:\s*(\w+)", line, re.I)
        if m:
            return m.group(1).lower()
    return None


def _extract_json_object(text: str, start: int) -> Optional[str]:
    """
    Extract a balanced JSON object from *text* beginning at *start*.

    Walks forward from ``text[start]`` (which must be ``{``), tracking brace
    depth while skipping braces that appear inside JSON string literals
    (including escaped quotes ``\"``).

    Returns the substring ``text[start:end+1]`` when the opening brace is
    balanced, or ``None`` if the braces are never balanced.
    """
    if start >= len(text) or text[start] != "{":
        return None

    depth = 0
    in_string = False
    i = start
    while i < len(text):
        ch = text[i]
        if in_string:
            if ch == "\\" and i + 1 < len(text):
                i += 2  # skip escaped character
                continue
            if ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        i += 1
    return None


def parse_bdd_spec_from_changes(content: str) -> Optional[Union[str, dict]]:
    """
    Parse BDD spec reference from changes content.

    Returns:
      - ``dict`` — inline JSON spec (parsed)
      - ``str``  — file path to a spec JSON file
      - ``None`` — not found

    Supports three styles:

    1. ``# BDD spec: path/to/spec.json``  (file path — existing behavior)
    2. ``# BDD spec: { "service_name": ... }``  (inline JSON after directive)
    3. Freestanding JSON block containing ``"service_name"`` anywhere in content
    """
    # --- Style 1 & 2: explicit directive ---
    for line_no, line in enumerate(content.splitlines()):
        m = re.search(r"#\s*BDD\s+spec\s*:\s*(\S.*)", line, re.I)
        if m:
            value = m.group(1).strip()
            if value.startswith("{"):
                # Inline JSON may span multiple lines — find opening brace in
                # the original content and extract the balanced object.
                brace_pos = content.index(value, content.index(line))
                json_str = _extract_json_object(content, brace_pos)
                if json_str:
                    # Strip leading '#' comment markers from each line (common
                    # when the JSON is inside a commented block).
                    cleaned = "\n".join(
                        re.sub(r"^\s*#\s?", "", l) for l in json_str.splitlines()
                    )
                    try:
                        return json.loads(cleaned)
                    except json.JSONDecodeError:
                        # Fall back to raw (no comment stripping)
                        try:
                            return json.loads(json_str)
                        except json.JSONDecodeError:
                            pass
                return None  # malformed inline JSON after directive
            # Plain file path
            return value

    # --- Style 3: freestanding JSON containing "service_name" ---
    sn_idx = content.find('"service_name"')
    if sn_idx != -1:
        brace_start = content.rfind("{", 0, sn_idx)
        if brace_start != -1:
            json_str = _extract_json_object(content, brace_start)
            if json_str:
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    pass

    return None


def load_changes(changes_path: str = "changes.txt") -> str:
    """Load requirement specification from changes.txt."""
    changes_path = Path(changes_path)
    if not changes_path.exists():
        raise FileNotFoundError(f"Changes file not found: {changes_path}")
    return changes_path.read_text(encoding="utf-8")


def load_changes_with_reference(changes_path: str = "changes.txt") -> tuple[str, str, Optional[str], Optional[str]]:
    """
    Load changes.txt and parse optional reference PR and framework repo.
    Returns (requirements, reference_pr_url, framework_repo_url, framework_branch).
    """
    raw = load_changes(changes_path)
    content, reference_pr = _parse_reference_pr_from_content(raw)
    framework_url, framework_branch = parse_framework_repo_from_changes(content)
    content = _strip_framework_lines(content)
    return content, reference_pr, framework_url, framework_branch
