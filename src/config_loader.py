"""
Configuration loader for autonomous code generation.
Reads config.ini and provides typed access to settings.
"""

import configparser
import os
import re
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
            auth_token = os.environ.get("BITBUCKET_APP_PASSWORD", "")

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
            "truncation_limit": get_int("agent", "truncation_limit", 30000),
            "show_activity": get_bool("agent", "show_activity", True),
            "command_allowlist_only": get_bool("agent", "command_allowlist_only", False),
            "allowed_command_prefixes": get_list("agent", "allowed_command_prefixes"),
            "blocked_commands": get_list("agent", "blocked_commands"),
            "circuit_breaker_threshold": get_int("agent", "circuit_breaker_threshold", 5),
            "circuit_breaker_timeout": get_float("agent", "circuit_breaker_timeout", 60.0),
            "rate_limit_max_tokens": get_float("agent", "rate_limit_max_tokens", 10.0),
            "rate_limit_refill_rate": get_float("agent", "rate_limit_refill_rate", 1.0),
            "summarization_budget": get_int("agent", "summarization_budget", 0),  # 0 = unlimited
            "testing_budget": get_int("agent", "testing_budget", 0),              # 0 = unlimited
        },
        "knowledge": {
            "backend": get("knowledge", "backend", "file").lower(),
            "storage_dir": get("knowledge", "storage_dir", ""),
            "opensearch_url": get("knowledge", "opensearch_url", ""),
            "opensearch_index": get("knowledge", "opensearch_index", "agent_knowledge"),
            "aws_region": get("knowledge", "aws_region", ""),
        },
        "tracing": {
            "enabled": get_bool("tracing", "enabled", True),
            "storage_dir": get("tracing", "storage_dir", ""),
        },
        "code_index": {
            "cache_dir": get("code_index", "cache_dir", ".code-index"),
            "max_age_hours": get_float("code_index", "max_age_hours", 24.0),
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
