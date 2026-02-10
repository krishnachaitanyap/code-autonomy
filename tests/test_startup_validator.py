"""Tests for src/startup_validator.py — pre-flight startup validation."""

import os
from unittest.mock import patch, MagicMock

import pytest

from src.startup_validator import validate_startup, ValidationResult


def _base_config(**overrides):
    """Build a minimal valid config dict, with optional overrides."""
    cfg = {
        "ai": {
            "api_key": "sk-test-key",
            "api_key_env": "OPENAI_API_KEY",
            "model": "gpt-4o",
            "provider": "openai",
            "base_url": "",
        },
        "repository": {
            "repo_url": "https://github.com/org/repo.git",
        },
        "github_config": {
            "auth_token": "ghp_testtoken",
        },
        "workflow": {
            "work_dir": "./workspace",
        },
    }
    for key, val in overrides.items():
        section, field = key.split(".", 1)
        cfg[section][field] = val
    return cfg


# ---------------------------------------------------------------------------
# ValidationResult
# ---------------------------------------------------------------------------

class TestValidationResult:
    def test_empty_result_is_valid(self):
        r = ValidationResult()
        assert r.is_valid is True

    def test_errors_make_invalid(self):
        r = ValidationResult(errors=["boom"])
        assert r.is_valid is False

    def test_warnings_only_is_valid(self):
        r = ValidationResult(warnings=["heads up"])
        assert r.is_valid is True


# ---------------------------------------------------------------------------
# API key check
# ---------------------------------------------------------------------------

class TestApiKeyValidation:
    @patch("src.startup_validator.shutil.which", return_value="/usr/bin/git")
    def test_missing_api_key_is_error(self, _mock_which):
        cfg = _base_config(**{"ai.api_key": ""})
        result = validate_startup(cfg)
        assert not result.is_valid
        assert any("API key" in e or "api_key" in e.lower() for e in result.errors)

    @patch("src.startup_validator.shutil.which", return_value="/usr/bin/git")
    def test_present_api_key_ok(self, _mock_which):
        cfg = _base_config()
        result = validate_startup(cfg)
        assert not any("API key" in e for e in result.errors)


# ---------------------------------------------------------------------------
# Model check
# ---------------------------------------------------------------------------

class TestModelValidation:
    @patch("src.startup_validator.shutil.which", return_value="/usr/bin/git")
    def test_missing_model_is_error(self, _mock_which):
        cfg = _base_config(**{"ai.model": ""})
        result = validate_startup(cfg)
        assert any("model" in e.lower() for e in result.errors)

    @patch("src.startup_validator.shutil.which", return_value="/usr/bin/git")
    def test_present_model_ok(self, _mock_which):
        cfg = _base_config()
        result = validate_startup(cfg)
        assert not any("model" in e.lower() for e in result.errors)


# ---------------------------------------------------------------------------
# repo_url check
# ---------------------------------------------------------------------------

class TestRepoUrlValidation:
    @patch("src.startup_validator.shutil.which", return_value="/usr/bin/git")
    def test_placeholder_repo_url_is_error(self, _mock_which):
        cfg = _base_config(**{"repository.repo_url": "https://github.com/owner/repo.git"})
        result = validate_startup(cfg, using_local_repo=False)
        assert any("repo_url" in e for e in result.errors)

    @patch("src.startup_validator.shutil.which", return_value="/usr/bin/git")
    def test_empty_repo_url_is_error(self, _mock_which):
        cfg = _base_config(**{"repository.repo_url": ""})
        result = validate_startup(cfg, using_local_repo=False)
        assert any("repo_url" in e for e in result.errors)

    @patch("src.startup_validator.shutil.which", return_value="/usr/bin/git")
    def test_repo_url_skipped_for_local_repo(self, _mock_which):
        cfg = _base_config(**{"repository.repo_url": ""})
        result = validate_startup(cfg, using_local_repo=True)
        assert not any("repo_url" in e for e in result.errors)


# ---------------------------------------------------------------------------
# auth_token check
# ---------------------------------------------------------------------------

class TestAuthTokenValidation:
    @patch("src.startup_validator.shutil.which", return_value="/usr/bin/git")
    def test_missing_auth_token_is_error_in_remote_mode(self, _mock_which):
        cfg = _base_config(**{"github_config.auth_token": ""})
        result = validate_startup(cfg, dry_run=False, using_local_repo=False)
        assert any("auth_token" in e for e in result.errors)

    @patch("src.startup_validator.shutil.which", return_value="/usr/bin/git")
    def test_auth_token_skipped_for_dry_run(self, _mock_which):
        cfg = _base_config(**{"github_config.auth_token": ""})
        result = validate_startup(cfg, dry_run=True)
        assert not any("auth_token" in e for e in result.errors)

    @patch("src.startup_validator.shutil.which", return_value="/usr/bin/git")
    def test_auth_token_skipped_for_local_repo(self, _mock_which):
        cfg = _base_config(**{"github_config.auth_token": ""})
        result = validate_startup(cfg, using_local_repo=True)
        assert not any("auth_token" in e for e in result.errors)


# ---------------------------------------------------------------------------
# git on PATH
# ---------------------------------------------------------------------------

class TestGitValidation:
    @patch("src.startup_validator.shutil.which", return_value=None)
    def test_git_not_on_path_is_error(self, _mock_which):
        cfg = _base_config()
        result = validate_startup(cfg)
        assert any("git" in e.lower() for e in result.errors)

    @patch("src.startup_validator.shutil.which", return_value="/usr/bin/git")
    def test_git_on_path_ok(self, _mock_which):
        cfg = _base_config()
        result = validate_startup(cfg)
        assert not any("git" in e.lower() and "not found" in e.lower() for e in result.errors)


# ---------------------------------------------------------------------------
# LLM ping (warning only)
# ---------------------------------------------------------------------------

class TestLlmPingValidation:
    @patch("src.startup_validator.shutil.which", return_value="/usr/bin/git")
    def test_llm_ping_failure_is_warning(self, _mock_which):
        cfg = _base_config()
        with patch("litellm.completion", side_effect=Exception("connection refused")):
            result = validate_startup(cfg)
        assert result.is_valid  # Still valid — it's a warning
        assert any("LLM API ping" in w for w in result.warnings)

    @patch("src.startup_validator.shutil.which", return_value="/usr/bin/git")
    def test_llm_ping_success_no_warning(self, _mock_which):
        cfg = _base_config()
        mock_resp = MagicMock()
        with patch("litellm.completion", return_value=mock_resp):
            result = validate_startup(cfg)
        assert not any("LLM API ping" in w for w in result.warnings)
