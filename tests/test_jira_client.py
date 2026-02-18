"""Tests for src/jira/client.py — JIRA integration (all HTTP calls mocked)."""

import os
from unittest.mock import patch, MagicMock

import pytest

from src.jira.client import (
    get_jira_token,
    search_jira_issues,
    fetch_agent_stories,
    add_jira_comment,
    transition_jira_issue,
    _jira_cfg,
    _resolve_credentials,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_config(**overrides) -> dict:
    """Return a minimal config dict with a populated [jira] section."""
    cfg = {
        "jira": {
            "base_url": "https://jira.example.com/rest/api/2",
            "ida_url": "https://idp.example.com/adfs/oauth2/token",
            "resource": "https://jira.example.com",
            "client_id": "test-client",
            "username": "testuser",
            "password": "testpass",
            "grant_type": "password",
            "project_key": "SPS",
            "agent_label": "code-autonomy",
            "acceptance_criteria_field": "customfield_11110",
            "verify_ssl": False,
            "timeout": 10,
            "max_stories": 50,
            "auto_transition_start": True,
            "auto_transition_done": False,
        },
    }
    for key, val in overrides.items():
        cfg["jira"][key] = val
    return cfg


def _mock_response(json_data=None, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.raise_for_status.return_value = None
    return resp


# ---------------------------------------------------------------------------
# _jira_cfg / _resolve_credentials
# ---------------------------------------------------------------------------

class TestJiraCfg:
    def test_missing_jira_section_raises(self):
        with pytest.raises(ValueError, match="Missing \\[jira\\] section"):
            _jira_cfg({})

    def test_returns_jira_dict(self):
        config = _base_config()
        assert _jira_cfg(config)["base_url"] == "https://jira.example.com/rest/api/2"


class TestResolveCredentials:
    def test_from_config(self):
        cfg = _base_config()["jira"]
        u, p = _resolve_credentials(cfg)
        assert u == "testuser"
        assert p == "testpass"

    def test_env_var_fallback(self):
        cfg = {"username": "", "password": ""}
        with patch.dict(os.environ, {"JIRA_USERNAME": "envuser", "JIRA_PASSWORD": "envpass"}):
            u, p = _resolve_credentials(cfg)
        assert u == "envuser"
        assert p == "envpass"

    def test_config_takes_precedence_over_env(self):
        cfg = {"username": "cfguser", "password": "cfgpass"}
        with patch.dict(os.environ, {"JIRA_USERNAME": "envuser", "JIRA_PASSWORD": "envpass"}):
            u, p = _resolve_credentials(cfg)
        assert u == "cfguser"
        assert p == "cfgpass"


# ---------------------------------------------------------------------------
# get_jira_token
# ---------------------------------------------------------------------------

class TestGetJiraToken:
    @patch("src.jira.client._session")
    def test_success(self, mock_session_fn):
        session = MagicMock()
        mock_session_fn.return_value = session
        session.post.return_value = _mock_response({"access_token": "tok123"})

        token = get_jira_token(_base_config())
        assert token == "tok123"
        session.post.assert_called_once()
        call_kwargs = session.post.call_args
        assert "idp.example.com" in call_kwargs[0][0]

    @patch("src.jira.client._session")
    def test_missing_access_token_raises(self, mock_session_fn):
        session = MagicMock()
        mock_session_fn.return_value = session
        session.post.return_value = _mock_response({})

        with pytest.raises(RuntimeError, match="access_token"):
            get_jira_token(_base_config())

    def test_missing_ida_url_raises(self):
        with pytest.raises(ValueError, match="ida_url"):
            get_jira_token(_base_config(ida_url=""))

    def test_missing_credentials_raises(self):
        config = _base_config(username="", password="")
        with patch.dict(os.environ, {}, clear=True):
            # Also clear any existing env vars
            env = {k: v for k, v in os.environ.items()
                   if k not in ("JIRA_USERNAME", "JIRA_PASSWORD")}
            with patch.dict(os.environ, env, clear=True):
                with pytest.raises(ValueError, match="credentials"):
                    get_jira_token(config)


# ---------------------------------------------------------------------------
# search_jira_issues
# ---------------------------------------------------------------------------

class TestSearchJiraIssues:
    @patch("src.jira.client._session")
    def test_returns_issues(self, mock_session_fn):
        session = MagicMock()
        mock_session_fn.return_value = session
        issues = [{"key": "SPS-1", "fields": {"summary": "Test"}}]
        session.post.return_value = _mock_response({"issues": issues})

        result = search_jira_issues(
            _base_config(), jql="project = SPS", token="pre-fetched",
        )
        assert len(result) == 1
        assert result[0]["key"] == "SPS-1"

    @patch("src.jira.client._session")
    def test_passes_fields(self, mock_session_fn):
        session = MagicMock()
        mock_session_fn.return_value = session
        session.post.return_value = _mock_response({"issues": []})

        search_jira_issues(
            _base_config(),
            jql="project = SPS",
            fields=["summary", "description"],
            token="tok",
        )
        payload = session.post.call_args[1]["json"]
        assert payload["fields"] == ["summary", "description"]

    def test_missing_base_url_raises(self):
        with pytest.raises(ValueError, match="base_url"):
            search_jira_issues(
                _base_config(base_url=""), jql="project = SPS", token="tok",
            )


# ---------------------------------------------------------------------------
# fetch_agent_stories
# ---------------------------------------------------------------------------

class TestFetchAgentStories:
    @patch("src.jira.client.search_jira_issues")
    def test_normalizes_fields(self, mock_search):
        mock_search.return_value = [
            {
                "key": "SPS-42",
                "fields": {
                    "summary": "Add login",
                    "description": "Build a login page",
                    "customfield_11110": "User can log in",
                },
            },
        ]
        stories = fetch_agent_stories(_base_config(), token="tok")
        assert len(stories) == 1
        s = stories[0]
        assert s["key"] == "SPS-42"
        assert s["summary"] == "Add login"
        assert s["description"] == "Build a login page"
        assert s["acceptance_criteria"] == "User can log in"

    @patch("src.jira.client.search_jira_issues")
    def test_missing_optional_fields(self, mock_search):
        mock_search.return_value = [
            {
                "key": "SPS-1",
                "fields": {"summary": "Bare story"},
            },
        ]
        stories = fetch_agent_stories(_base_config(), token="tok")
        assert stories[0]["description"] == ""
        assert stories[0]["acceptance_criteria"] == ""

    @patch("src.jira.client.search_jira_issues")
    def test_jql_includes_project_and_label(self, mock_search):
        mock_search.return_value = []
        fetch_agent_stories(_base_config(), token="tok")
        call_kwargs = mock_search.call_args
        jql = call_kwargs[1]["jql"]
        assert "project = SPS" in jql
        assert 'labels = "code-autonomy"' in jql
        assert "status != Done" in jql


# ---------------------------------------------------------------------------
# add_jira_comment
# ---------------------------------------------------------------------------

class TestAddJiraComment:
    @patch("src.jira.client._session")
    def test_posts_comment(self, mock_session_fn):
        session = MagicMock()
        mock_session_fn.return_value = session
        session.post.return_value = _mock_response()

        add_jira_comment(_base_config(), "SPS-1", "Hello", token="tok")
        call_args = session.post.call_args
        assert "/issue/SPS-1/comment" in call_args[0][0]
        assert call_args[1]["json"]["body"] == "Hello"


# ---------------------------------------------------------------------------
# transition_jira_issue
# ---------------------------------------------------------------------------

class TestTransitionJiraIssue:
    @patch("src.jira.client._session")
    def test_executes_matching_transition(self, mock_session_fn):
        session = MagicMock()
        mock_session_fn.return_value = session

        # First call: GET transitions, second call: POST transition
        session.get.return_value = _mock_response({
            "transitions": [
                {"id": "21", "name": "In Progress"},
                {"id": "31", "name": "Done"},
            ],
        })
        session.post.return_value = _mock_response()

        ok = transition_jira_issue(_base_config(), "SPS-1", "In Progress", token="tok")
        assert ok is True
        # Verify the POST used the correct transition id
        post_payload = session.post.call_args[1]["json"]
        assert post_payload["transition"]["id"] == "21"

    @patch("src.jira.client._session")
    def test_returns_false_when_not_found(self, mock_session_fn):
        session = MagicMock()
        mock_session_fn.return_value = session
        session.get.return_value = _mock_response({
            "transitions": [{"id": "21", "name": "In Progress"}],
        })

        ok = transition_jira_issue(_base_config(), "SPS-1", "Nonexistent", token="tok")
        assert ok is False
        session.post.assert_not_called()


# ---------------------------------------------------------------------------
# _build_requirements_from_story (from main.py)
# ---------------------------------------------------------------------------

class TestBuildRequirementsFromStory:
    def test_full_story(self):
        from main import _build_requirements_from_story

        story = {
            "key": "SPS-42",
            "summary": "Add login page",
            "description": "Build a login page with OAuth",
            "acceptance_criteria": "User can log in via Google",
        }
        req = _build_requirements_from_story(story)
        assert "SPS-42" in req
        assert "Add login page" in req
        assert "Build a login page with OAuth" in req
        assert "User can log in via Google" in req

    def test_minimal_story(self):
        from main import _build_requirements_from_story

        story = {
            "key": "SPS-1",
            "summary": "Do something",
            "description": "",
            "acceptance_criteria": "",
        }
        req = _build_requirements_from_story(story)
        assert "SPS-1" in req
        assert "Do something" in req
        assert "Description" not in req
        assert "Acceptance Criteria" not in req


# ---------------------------------------------------------------------------
# max_retries config default
# ---------------------------------------------------------------------------

class TestMaxRetriesConfig:
    def test_default_max_retries(self, tmp_path):
        """max_retries defaults to 2 when not set."""
        ini = tmp_path / "config.ini"
        ini.write_text(
            "[ai]\nprovider = openai\napi_key = test\nmodel = gpt-4o\n"
            "[repository]\nrepo_url = https://github.com/o/r.git\n"
            "[jira]\nbase_url = https://j.example.com/rest/api/2\n"
        )
        from src.config_loader import load_config

        cfg = load_config(str(ini))
        assert cfg["jira"]["max_retries"] == 2

    def test_custom_max_retries(self, tmp_path):
        ini = tmp_path / "config.ini"
        ini.write_text(
            "[ai]\nprovider = openai\napi_key = test\nmodel = gpt-4o\n"
            "[repository]\nrepo_url = https://github.com/o/r.git\n"
            "[jira]\nbase_url = https://j.example.com/rest/api/2\n"
            "max_retries = 5\n"
        )
        from src.config_loader import load_config

        cfg = load_config(str(ini))
        assert cfg["jira"]["max_retries"] == 5


# ---------------------------------------------------------------------------
# config_loader: [jira] section
# ---------------------------------------------------------------------------

class TestJiraConfigLoader:
    def test_jira_section_parsed(self, tmp_path):
        """config_loader.load_config parses the [jira] section."""
        ini = tmp_path / "config.ini"
        ini.write_text(
            "[ai]\nprovider = openai\napi_key = test\nmodel = gpt-4o\n"
            "[repository]\nrepo_url = https://github.com/o/r.git\n"
            "[jira]\nbase_url = https://j.example.com/rest/api/2\n"
            "ida_url = https://idp.example.com/token\n"
            "project_key = TST\nagent_label = my-agent\n"
            "verify_ssl = true\ntimeout = 15\nmax_stories = 10\n"
        )
        from src.config_loader import load_config

        cfg = load_config(str(ini))
        j = cfg["jira"]
        assert j["base_url"] == "https://j.example.com/rest/api/2"
        assert j["project_key"] == "TST"
        assert j["agent_label"] == "my-agent"
        assert j["verify_ssl"] is True
        assert j["timeout"] == 15
        assert j["max_stories"] == 10

    def test_jira_env_var_fallback(self, tmp_path):
        """Username/password fall back to env vars when not set in config."""
        ini = tmp_path / "config.ini"
        ini.write_text(
            "[ai]\nprovider = openai\napi_key = test\nmodel = gpt-4o\n"
            "[repository]\nrepo_url = https://github.com/o/r.git\n"
            "[jira]\nbase_url = https://j.example.com/rest/api/2\n"
        )
        from src.config_loader import load_config

        with patch.dict(os.environ, {"JIRA_USERNAME": "eu", "JIRA_PASSWORD": "ep"}):
            cfg = load_config(str(ini))
        assert cfg["jira"]["username"] == "eu"
        assert cfg["jira"]["password"] == "ep"
