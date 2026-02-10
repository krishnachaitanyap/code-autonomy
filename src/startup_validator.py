"""
Pre-flight startup validation.

Catches configuration problems before the pipeline invests time cloning repos
or making API calls. Fatal errors abort immediately; warnings are logged but
do not block execution.
"""

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ValidationResult:
    """Collects errors (fatal) and warnings (non-fatal) from pre-flight checks."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0


def validate_startup(
    config: dict,
    dry_run: bool = False,
    using_local_repo: bool = False,
) -> ValidationResult:
    """
    Run pre-flight checks against the loaded configuration.

    Args:
        config: Full config dict from load_config().
        dry_run: Whether --dry-run was passed.
        using_local_repo: Whether --repo-path was passed.

    Returns:
        ValidationResult with errors and warnings.
    """
    result = ValidationResult()
    ai_cfg = config.get("ai", {})
    repo_cfg = config.get("repository", {})
    creds = config.get("github_config", {})
    workflow = config.get("workflow", {})

    # 1. API key present
    api_key = ai_cfg.get("api_key", "")
    if not api_key:
        env_var = ai_cfg.get("api_key_env", "OPENAI_API_KEY")
        result.errors.append(
            f"No API key found. Set {env_var} environment variable or api_key in config.ini [ai] section."
        )

    # 2. Model name non-empty
    model = ai_cfg.get("model", "")
    if not model:
        result.errors.append(
            "No model specified. Set model in config.ini [ai] section."
        )

    # 3. repo_url valid (unless --repo-path)
    if not using_local_repo:
        repo_url = repo_cfg.get("repo_url", "")
        placeholder = "https://github.com/owner/repo.git"
        if not repo_url or repo_url == placeholder:
            result.errors.append(
                "Set repo_url in config.ini to your actual repository URL."
            )

    # 4. auth_token present (unless dry-run or local)
    if not dry_run and not using_local_repo:
        auth_token = creds.get("auth_token", "")
        if not auth_token:
            result.errors.append(
                "Set auth_token in config.ini or GITHUB_TOKEN/BITBUCKET_APP_PASSWORD env var."
            )

    # 5. work_dir parent exists and writable
    work_dir = workflow.get("work_dir", "./workspace")
    work_path = Path(work_dir).resolve()
    parent = work_path.parent
    if not parent.exists():
        result.errors.append(
            f"work_dir parent does not exist: {parent}"
        )
    elif not os.access(str(parent), os.W_OK):
        result.errors.append(
            f"work_dir parent is not writable: {parent}"
        )

    # 6. git on PATH
    if shutil.which("git") is None:
        result.errors.append(
            "git is not found on PATH. Install git to proceed."
        )

    # 7. LLM API reachable (warning only)
    if api_key and model:
        try:
            import litellm
            from src.llm_client import _build_model_string, _resolve_api_key

            resolved_key = _resolve_api_key(ai_cfg)
            model_string = _build_model_string(ai_cfg)
            litellm.completion(
                model=model_string,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
                api_key=resolved_key,
            )
        except Exception as e:
            result.warnings.append(
                f"LLM API ping failed (non-fatal): {e}"
            )

    return result
