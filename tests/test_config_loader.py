"""Tests for src/config_loader.py — env var overrides and missing config.ini."""

import os
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from src.config_loader import load_config


class TestMissingConfigIni:
    """load_config() should work without a config.ini file."""

    def test_missing_config_returns_defaults(self, tmp_path):
        """When config.ini doesn't exist, load_config returns a dict with defaults."""
        missing = tmp_path / "nonexistent.ini"
        cfg = load_config(str(missing))
        # Should return a dict with expected top-level sections
        assert isinstance(cfg, dict)
        assert "ai" in cfg
        assert "repository" in cfg
        assert "workflow" in cfg
        # Default values should be populated
        assert cfg["ai"]["provider"] == "openai"
        assert cfg["repository"]["base_branch"] == "main"

    def test_missing_config_no_file_not_found_error(self, tmp_path):
        """Should NOT raise FileNotFoundError when config.ini is absent."""
        missing = tmp_path / "does_not_exist.ini"
        # This used to raise FileNotFoundError — now it should succeed
        cfg = load_config(str(missing))
        assert cfg is not None


class TestEnvVarOverrides:
    """CA_{SECTION}_{KEY} env vars should override config.ini values."""

    def test_env_var_overrides_ini_value(self, tmp_path):
        """An env var like CA_AI_PROVIDER should override the ini value."""
        ini = tmp_path / "config.ini"
        ini.write_text(textwrap.dedent("""\
            [ai]
            provider = openai
            model = gpt-4o
        """))
        with patch.dict(os.environ, {"CA_AI_PROVIDER": "anthropic"}, clear=False):
            cfg = load_config(str(ini))
        assert cfg["ai"]["provider"] == "anthropic"

    def test_env_var_overrides_without_ini(self, tmp_path):
        """Env vars should work even when no config.ini exists."""
        missing = tmp_path / "nonexistent.ini"
        with patch.dict(os.environ, {
            "CA_AI_PROVIDER": "gemini",
            "CA_AI_MODEL": "gemini-pro",
        }, clear=False):
            cfg = load_config(str(missing))
        assert cfg["ai"]["provider"] == "gemini"
        assert cfg["ai"]["model"] == "gemini-pro"

    def test_env_var_takes_precedence_over_ini(self, tmp_path):
        """Env var wins even when the ini file has a value for the same key."""
        ini = tmp_path / "config.ini"
        ini.write_text(textwrap.dedent("""\
            [workflow]
            work_dir = ./my_workspace
        """))
        with patch.dict(os.environ, {"CA_WORKFLOW_WORK_DIR": "/custom/dir"}, clear=False):
            cfg = load_config(str(ini))
        assert cfg["workflow"]["work_dir"] == "/custom/dir"

    def test_env_var_not_set_falls_through_to_ini(self, tmp_path):
        """When no env var is set, the ini value should be used."""
        ini = tmp_path / "config.ini"
        ini.write_text(textwrap.dedent("""\
            [ai]
            provider = anthropic
        """))
        # Ensure the env var is NOT set
        env = {k: v for k, v in os.environ.items() if k != "CA_AI_PROVIDER"}
        with patch.dict(os.environ, env, clear=True):
            cfg = load_config(str(ini))
        assert cfg["ai"]["provider"] == "anthropic"

    def test_env_var_empty_string_counts_as_set(self, tmp_path):
        """An env var set to empty string should override (not fall through)."""
        ini = tmp_path / "config.ini"
        ini.write_text(textwrap.dedent("""\
            [ai]
            base_url = https://example.com
        """))
        with patch.dict(os.environ, {"CA_AI_BASE_URL": ""}, clear=False):
            cfg = load_config(str(ini))
        assert cfg["ai"]["base_url"] == ""


class TestSessionDirOverride:
    """CA_JIRA_SESSION_DIR env var should override the default session dir."""

    def test_default_session_dir(self):
        from src.jira.session import _session_dir
        env = {k: v for k, v in os.environ.items() if k != "CA_JIRA_SESSION_DIR"}
        with patch.dict(os.environ, env, clear=True):
            result = _session_dir()
        assert result == Path.home() / ".code-autonomy" / "jira_sessions"

    def test_env_var_overrides_session_dir(self, tmp_path):
        from src.jira.session import _session_dir
        custom_dir = str(tmp_path / "custom_sessions")
        with patch.dict(os.environ, {"CA_JIRA_SESSION_DIR": custom_dir}, clear=False):
            result = _session_dir()
        assert result == Path(custom_dir)
