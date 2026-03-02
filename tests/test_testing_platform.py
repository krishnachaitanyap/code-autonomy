"""
Tests for the enterprise testing platform — data models, service layer, and API routes.
"""

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Set a test database URL before importing anything that touches the DB
_TEST_DB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TEST_DB.close()
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB.name}"

from src.data.database import get_session, init_db, reset_engine
from src.data.models import (
    ChatMessage,
    CoverageReport,
    CustomStep,
    DataInjectionConfig,
    Repo,
    TestEvidence,
    TestProject,
    TestRun,
)
from src.services.testing_service import TestingService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _fresh_db():
    """Reset and reinitialize the database for each test."""
    reset_engine()
    os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB.name}"
    init_db()
    yield
    # Clean up all test data
    with get_session() as db:
        db.query(ChatMessage).delete()
        db.query(TestEvidence).delete()
        db.query(TestRun).delete()
        db.query(CoverageReport).delete()
        db.query(DataInjectionConfig).delete()
        db.query(CustomStep).delete()
        db.query(TestProject).delete()
        db.query(Repo).delete()


@pytest.fixture
def service():
    return TestingService()


@pytest.fixture
def sample_project(service):
    return service.create_project(
        name="Test Service",
        repo_url="https://github.com/org/test-service.git",
        language="java",
        framework="spring",
        testing_framework="junit",
        branch="main",
    )


# ---------------------------------------------------------------------------
# TestProject CRUD
# ---------------------------------------------------------------------------

class TestProjectCRUD:
    def test_create_project(self, service):
        project = service.create_project(
            name="My Service",
            repo_url="https://github.com/org/my-service.git",
            language="java",
        )
        assert project.id
        assert project.name == "My Service"
        assert project.repo_url == "https://github.com/org/my-service.git"
        assert project.language == "java"
        assert project.status == "pending"

    def test_create_project_local_path(self, service):
        project = service.create_project(
            name="Local Service",
            local_path="/tmp/my-service",
        )
        assert project.id
        assert project.local_path == "/tmp/my-service"
        assert project.repo_id  # should be generated

    def test_get_project(self, service, sample_project):
        fetched = service.get_project(sample_project.id)
        assert fetched is not None
        assert fetched.name == "Test Service"

    def test_get_project_not_found(self, service):
        assert service.get_project("nonexistent") is None

    def test_list_projects(self, service, sample_project):
        projects = service.list_projects()
        assert len(projects) >= 1
        assert any(p.id == sample_project.id for p in projects)

    def test_list_projects_filter_status(self, service, sample_project):
        projects = service.list_projects(status="pending")
        assert len(projects) >= 1

        projects_ready = service.list_projects(status="ready")
        assert not any(p.id == sample_project.id for p in projects_ready)

    def test_delete_project(self, service, sample_project):
        assert service.delete_project(sample_project.id) is True
        assert service.get_project(sample_project.id) is None

    def test_delete_project_not_found(self, service):
        assert service.delete_project("nonexistent") is False


# ---------------------------------------------------------------------------
# Auto-Discovery
# ---------------------------------------------------------------------------

class TestAutoDiscovery:
    def test_discover_from_path_java(self, service, tmp_path):
        # Create a minimal Java project structure
        (tmp_path / "pom.xml").write_text("<project></project>")
        src_dir = tmp_path / "src" / "main" / "java" / "com" / "example"
        src_dir.mkdir(parents=True)

        (src_dir / "UserController.java").write_text(
            '@RestController\n@RequestMapping("/api/users")\npublic class UserController {}'
        )
        (src_dir / "UserService.java").write_text(
            "@Service\npublic class UserService {}"
        )
        (src_dir / "UserRequest.java").write_text(
            "public class UserRequest { String name; }"
        )

        test_dir = tmp_path / "src" / "test" / "java" / "com" / "example"
        test_dir.mkdir(parents=True)
        (test_dir / "UserControllerTest.java").write_text("public class UserControllerTest {}")

        discovery = service._discover_from_path(tmp_path)

        assert "maven" in discovery["frameworks_detected"]
        assert "spring" in discovery["frameworks_detected"]
        assert len(discovery["endpoints"]) >= 1
        assert len(discovery["services"]) >= 1
        assert len(discovery["dto_classes"]) >= 1
        assert len(discovery["test_files"]) >= 1

    def test_discover_from_path_python(self, service, tmp_path):
        (tmp_path / "requirements.txt").write_text("flask\npytest\n")
        (tmp_path / "pytest.ini").write_text("[pytest]\n")
        (tmp_path / "test_app.py").write_text("def test_health(): pass")

        discovery = service._discover_from_path(tmp_path)

        assert "python" in discovery["frameworks_detected"]
        assert "pytest" in discovery["frameworks_detected"]
        assert len(discovery["test_files"]) >= 1

    def test_discover_from_path_servlet_xml(self, service, tmp_path):
        web_inf = tmp_path / "src" / "main" / "webapp" / "WEB-INF"
        web_inf.mkdir(parents=True)
        (web_inf / "rest-servlet.xml").write_text(
            '<beans><bean id="TestController" class="com.example.TestController"/></beans>'
        )
        (web_inf / "cxf-servlet.xml").write_text(
            '<beans><jaxws:endpoint id="TestSvc"/></beans>'
        )

        discovery = service._discover_from_path(tmp_path)

        assert any(ep["type"] == "REST-servlet" for ep in discovery["endpoints"])
        assert any(ep["type"] == "SOAP-servlet" for ep in discovery["endpoints"])

    def test_discover_openapi(self, service, tmp_path):
        (tmp_path / "openapi.yaml").write_text("openapi: 3.0.0\ninfo:\n  title: Test")

        discovery = service._discover_from_path(tmp_path)

        assert any(ep["type"] == "OpenAPI" for ep in discovery["endpoints"])

    def test_run_discovery_updates_project(self, service):
        project = service.create_project(
            name="Discovery Test",
            local_path="/nonexistent/path",
        )
        result = service.run_discovery(project.id)
        assert result is not None
        assert result.status == "ready"

    def test_run_discovery_not_found(self, service):
        assert service.run_discovery("nonexistent") is None

    def test_extract_annotations(self, service):
        code = '''
        @RestController
        @RequestMapping("/api/users")
        public class UserController {
            @GetMapping("/list")
            public List<User> list() {}

            @PostMapping("/create")
            public User create() {}
        }
        '''
        annotations = service._extract_annotations(code)
        assert "/api/users" in annotations
        assert "/list" in annotations
        assert "/create" in annotations


# ---------------------------------------------------------------------------
# Test Runs
# ---------------------------------------------------------------------------

class TestTestRuns:
    def test_create_run(self, service, sample_project):
        run = service.create_run(
            project_id=sample_project.id,
            run_type="functional",
            strategy="bdd",
        )
        assert run.id
        assert run.project_id == sample_project.id
        assert run.status == "queued"
        assert run.run_type == "functional"
        assert run.strategy == "bdd"

    def test_list_runs(self, service, sample_project):
        service.create_run(project_id=sample_project.id)
        service.create_run(project_id=sample_project.id, run_type="security")

        runs = service.list_runs()
        assert len(runs) >= 2

    def test_list_runs_filter_project(self, service, sample_project):
        service.create_run(project_id=sample_project.id)

        runs = service.list_runs(project_id=sample_project.id)
        assert len(runs) >= 1
        assert all(r.project_id == sample_project.id for r in runs)

    def test_list_runs_filter_status(self, service, sample_project):
        service.create_run(project_id=sample_project.id)

        runs = service.list_runs(status="queued")
        assert len(runs) >= 1

    def test_get_run(self, service, sample_project):
        run = service.create_run(project_id=sample_project.id)
        fetched = service.get_run(run.id)
        assert fetched is not None
        assert fetched.id == run.id

    def test_cancel_run(self, service, sample_project):
        run = service.create_run(project_id=sample_project.id)
        cancelled = service.cancel_run(run.id)
        assert cancelled is not None
        assert cancelled.status == "cancelled"
        assert cancelled.completed_at is not None

    def test_cancel_run_not_found(self, service):
        assert service.cancel_run("nonexistent") is None


# ---------------------------------------------------------------------------
# Coverage Analysis
# ---------------------------------------------------------------------------

class TestCoverageAnalysis:
    def test_analyze_coverage(self, service, sample_project):
        # Set up discovery results for the project
        with get_session() as db:
            project = db.get(TestProject, sample_project.id)
            project.discovery_result = {
                "endpoints": [
                    {"file": "UserController.java", "type": "REST"},
                    {"file": "OrderController.java", "type": "REST"},
                ],
                "services": [
                    {"file": "UserService.java", "type": "service"},
                ],
                "test_files": [
                    {"file": "UserControllerTest.java", "language": "java"},
                ],
                "frameworks_detected": ["spring", "maven"],
            }

        report = service.analyze_coverage(sample_project.id)
        assert report is not None
        assert report.project_id == sample_project.id
        assert report.report_type == "functional"
        assert report.overall_pct >= 0
        assert isinstance(report.uncovered_areas, list)
        assert isinstance(report.gaps, list)

    def test_analyze_coverage_not_found(self, service):
        assert service.analyze_coverage("nonexistent") is None

    def test_list_coverage_reports(self, service, sample_project):
        with get_session() as db:
            project = db.get(TestProject, sample_project.id)
            project.discovery_result = {
                "endpoints": [], "services": [], "test_files": [], "frameworks_detected": [],
            }

        service.analyze_coverage(sample_project.id)
        reports = service.list_coverage_reports(sample_project.id)
        assert len(reports) >= 1


# ---------------------------------------------------------------------------
# Data Injection
# ---------------------------------------------------------------------------

class TestDataInjection:
    def test_create_config(self, service, sample_project):
        config = service.create_data_injection_config(
            project_id=sample_project.id,
            name="User Factory",
            strategy="factory",
            target_entity="User",
            schema_definition={
                "firstName": {"type": "string"},
                "lastName": {"type": "string"},
                "email": {"type": "string"},
                "accountId": {"type": "integer"},
            },
        )
        assert config.id
        assert config.name == "User Factory"
        assert config.strategy == "factory"

    def test_list_configs(self, service, sample_project):
        service.create_data_injection_config(
            project_id=sample_project.id,
            name="Config 1",
        )
        service.create_data_injection_config(
            project_id=sample_project.id,
            name="Config 2",
        )
        configs = service.list_data_injection_configs(sample_project.id)
        assert len(configs) >= 2

    def test_delete_config(self, service, sample_project):
        config = service.create_data_injection_config(
            project_id=sample_project.id,
            name="To Delete",
        )
        assert service.delete_data_injection_config(config.id) is True
        configs = service.list_data_injection_configs(sample_project.id)
        assert not any(c.id == config.id for c in configs)

    def test_generate_sample_data(self, service, sample_project):
        config = service.create_data_injection_config(
            project_id=sample_project.id,
            name="User Data",
            schema_definition={
                "firstName": {"type": "string"},
                "email": {"type": "string"},
                "age": {"type": "integer"},
                "balance": {"type": "float"},
                "active": {"type": "boolean"},
            },
        )
        result = service.generate_sample_data(config.id, count=3)
        assert result is not None
        assert len(result.sample_data) == 3
        # Check generated values have the right types
        record = result.sample_data[0]
        assert "firstName" in record
        assert "email" in record
        assert "@" in record["email"]
        assert isinstance(record["age"], int)

    def test_generate_sample_data_not_found(self, service):
        assert service.generate_sample_data("nonexistent") is None

    def test_generate_field_value_types(self, service):
        assert "@" in service._generate_field_value("email", "string", 0)
        assert service._generate_field_value("phone", "string", 0).startswith("+")
        assert isinstance(service._generate_field_value("count", "integer", 0), int)
        assert isinstance(service._generate_field_value("amount", "float", 0), float)
        assert isinstance(service._generate_field_value("active", "boolean", 0), bool)


# ---------------------------------------------------------------------------
# Custom Steps
# ---------------------------------------------------------------------------

class TestCustomSteps:
    def test_create_step(self, service, sample_project):
        step = service.create_custom_step(
            project_id=sample_project.id,
            name="User is authenticated",
            step_type="given",
            pattern='the user {string} is authenticated',
            implementation='@Given("the user {string} is authenticated")\npublic void auth(String user) {}',
            language="java",
            tags=["auth"],
        )
        assert step.id
        assert step.name == "User is authenticated"
        assert step.source == "user"

    def test_list_steps(self, service, sample_project):
        service.create_custom_step(
            project_id=sample_project.id,
            name="Step 1",
        )
        service.create_custom_step(
            project_id=sample_project.id,
            name="Step 2",
        )
        steps = service.list_custom_steps(sample_project.id)
        assert len(steps) >= 2

    def test_update_step(self, service, sample_project):
        step = service.create_custom_step(
            project_id=sample_project.id,
            name="Original",
        )
        updated = service.update_custom_step(step.id, name="Updated")
        assert updated is not None
        assert updated.name == "Updated"

    def test_update_step_not_found(self, service):
        assert service.update_custom_step("nonexistent", name="Test") is None

    def test_delete_step(self, service, sample_project):
        step = service.create_custom_step(
            project_id=sample_project.id,
            name="To Delete",
        )
        assert service.delete_custom_step(step.id) is True
        steps = service.list_custom_steps(sample_project.id)
        assert not any(s.id == step.id for s in steps)

    def test_discover_steps_java(self, service, tmp_path):
        project = service.create_project(
            name="Step Discovery",
            local_path=str(tmp_path),
        )

        # Create a step definition file
        steps_dir = tmp_path / "src" / "test" / "java" / "steps"
        steps_dir.mkdir(parents=True)
        (steps_dir / "CommonSteps.java").write_text('''
            @Given("the user is logged in")
            public void userLoggedIn() {}

            @When("the user submits the form")
            public void submitForm() {}

            @Then("the response status is {int}")
            public void checkStatus(int status) {}
        ''')

        discovered = service.discover_custom_steps(project.id)
        assert len(discovered) == 3
        assert any(s.step_type == "given" for s in discovered)
        assert any(s.step_type == "when" for s in discovered)
        assert any(s.step_type == "then" for s in discovered)
        assert all(s.source == "discovered" for s in discovered)

    def test_discover_steps_no_path(self, service):
        project = service.create_project(name="No Path")
        steps = service.discover_custom_steps(project.id)
        assert steps == []


# ---------------------------------------------------------------------------
# Chat
# ---------------------------------------------------------------------------

class TestChat:
    def test_chat_basic(self, service, sample_project):
        reply, context = service.chat(
            project_id=sample_project.id,
            message="Hello, what can you help with?",
        )
        assert reply.role == "assistant"
        assert len(reply.content) > 0
        assert context.get("project_name") == "Test Service"

    def test_chat_coverage_intent(self, service, sample_project):
        reply, _ = service.chat(
            project_id=sample_project.id,
            message="What is the test coverage?",
        )
        assert "coverage" in reply.content.lower()

    def test_chat_security_intent(self, service, sample_project):
        reply, _ = service.chat(
            project_id=sample_project.id,
            message="Run a security penetration test",
        )
        assert "security" in reply.content.lower()

    def test_chat_test_intent(self, service, sample_project):
        reply, _ = service.chat(
            project_id=sample_project.id,
            message="Start running tests",
        )
        assert any(word in reply.content.lower() for word in ("test", "run", "functional"))

    def test_chat_history(self, service, sample_project):
        service.chat(project_id=sample_project.id, message="Hello")
        service.chat(project_id=sample_project.id, message="How are you?")

        history = service.get_chat_history(sample_project.id)
        # Each chat produces a user message + assistant reply
        assert len(history) >= 4

    def test_classify_intent(self, service):
        assert service._classify_intent("What is the coverage?") == "coverage"
        assert service._classify_intent("Run the tests") == "test_execution"
        assert service._classify_intent("Generate synthetic data") == "data_injection"
        assert service._classify_intent("Set up data factory") == "data_injection"
        assert service._classify_intent("Find custom steps") == "custom_steps"
        assert service._classify_intent("Discover endpoints") == "discovery"
        assert service._classify_intent("Check for SQL injection vulnerability") == "security"
        assert service._classify_intent("Show me the progress") == "status"
        assert service._classify_intent("Hello there") == "general"


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

class TestStats:
    def test_get_stats_empty(self, service):
        stats = service.get_stats()
        assert stats["total_projects"] == 0
        assert stats["total_runs"] == 0
        assert stats["success_rate"] == 0.0

    def test_get_stats_with_data(self, service, sample_project):
        service.create_run(project_id=sample_project.id)
        stats = service.get_stats()
        assert stats["total_projects"] >= 1
        assert stats["total_runs"] >= 1


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

class TestDataModels:
    def _ensure_repo(self, db, repo_id="test-repo-1"):
        """Create a Repo record if it doesn't exist."""
        repo = db.get(Repo, repo_id)
        if not repo:
            repo = Repo(id=repo_id, url="https://example.com/repo.git", local_path="", platform="github")
            db.add(repo)
            db.flush()
        return repo

    def test_test_project_model(self):
        with get_session() as db:
            self._ensure_repo(db, "test-repo-m1")
            project = TestProject(
                id="test-model-1",
                repo_id="test-repo-m1",
                name="Model Test",
                repo_url="https://example.com/repo.git",
                status="pending",
            )
            db.add(project)
            db.flush()

            fetched = db.get(TestProject, "test-model-1")
            assert fetched is not None
            assert fetched.name == "Model Test"
            assert fetched.created_at is not None

    def test_test_run_model(self):
        with get_session() as db:
            self._ensure_repo(db, "test-repo-m2")
            project = TestProject(id="test-model-2", repo_id="test-repo-m2", name="Run Model Test")
            db.add(project)
            db.flush()

            run = TestRun(
                id="run-model-1",
                project_id="test-model-2",
                run_type="security",
                strategy="penetration",
            )
            db.add(run)
            db.flush()

            fetched = db.get(TestRun, "run-model-1")
            assert fetched is not None
            assert fetched.run_type == "security"

    def test_test_evidence_model(self):
        with get_session() as db:
            self._ensure_repo(db, "test-repo-m3")
            project = TestProject(id="test-model-3", repo_id="test-repo-m3", name="Evidence Model Test")
            db.add(project)
            run = TestRun(id="run-model-2", project_id="test-model-3")
            db.add(run)
            db.flush()

            evidence = TestEvidence(
                id="ev-1",
                test_run_id="run-model-2",
                evidence_type="report",
                title="Test Report",
                content="All tests passed",
            )
            db.add(evidence)
            db.flush()

            fetched = db.get(TestEvidence, "ev-1")
            assert fetched is not None
            assert fetched.title == "Test Report"

    def test_cascade_delete(self):
        with get_session() as db:
            self._ensure_repo(db, "test-repo-cascade")
            project = TestProject(id="cascade-1", repo_id="test-repo-cascade", name="Cascade Test")
            db.add(project)
            db.flush()

            run = TestRun(id="cascade-run-1", project_id="cascade-1")
            db.add(run)
            db.flush()

            step = CustomStep(id="cascade-step-1", project_id="cascade-1", name="Test Step")
            db.add(step)
            db.flush()

            db.delete(project)
            db.flush()

            assert db.get(TestRun, "cascade-run-1") is None
            assert db.get(CustomStep, "cascade-step-1") is None


# ---------------------------------------------------------------------------
# Test Run Execution Pipeline
# ---------------------------------------------------------------------------

@dataclass
class MockAgentResult:
    """Mock for AgentResult returned by generate_changes_with_agent."""
    success: bool = True
    files_changed: list = field(default_factory=list)
    summary: str = "Generated 3 test files"
    turns_used: int = 5
    tests_passed: bool = True
    trace_id: str = ""


class TestRunExecution:
    """Tests for the background test run execution pipeline."""

    def test_execute_run_no_repo(self, service, sample_project):
        """Run with no accessible local_path → status='error'."""
        run = service.create_run(project_id=sample_project.id)
        config = {"ai": {"api_key": ""}}

        result = service.execute_run(run.id, config)
        assert result is None

        # Verify status is error
        fetched = service.get_run(run.id)
        assert fetched.status == "error"
        assert "Cannot resolve repository" in fetched.result_summary

        # Verify error evidence was created
        evidences = service.list_evidences(run.id)
        assert len(evidences) >= 1
        assert any(e.title == "Execution Error" for e in evidences)

    def test_execute_run_not_found(self, service):
        """Run with nonexistent run_id → returns None."""
        result = service.execute_run("nonexistent", {})
        assert result is None

    @patch("src.services.testing_service.TestingService._generate_tests")
    def test_execute_run_with_mock_repo(self, mock_gen, service, sample_project, tmp_path):
        """Full pipeline with mock repo and mock agent."""
        # Set up project with a real tmp path
        with get_session() as db:
            project = db.get(TestProject, sample_project.id)
            project.local_path = str(tmp_path)
            db.flush()

        # Create a simple Python test file in the temp dir
        (tmp_path / "test_hello.py").write_text(
            "def test_pass(): assert True\ndef test_fail(): assert False\n"
        )
        (tmp_path / "pytest.ini").write_text("[pytest]\n")

        # Mock agent to return success
        mock_gen.return_value = MockAgentResult(
            success=True,
            files_changed=[str(tmp_path / "test_hello.py")],
            summary="Generated test_hello.py with 2 tests",
        )

        run = service.create_run(project_id=sample_project.id)
        config = {"ai": {"api_key": "test-key"}, "agent": {}}

        result = service.execute_run(run.id, config)

        # The run should complete (status depends on actual test execution)
        assert result is not None
        assert result.status in ("passed", "failed")
        assert result.progress_pct == 100.0
        assert result.started_at is not None
        assert result.completed_at is not None
        assert result.agent_id is not None

    @patch("src.services.testing_service.TestingService._generate_tests")
    @patch("src.code.executor.run_tests")
    def test_execute_run_passed(self, mock_run_tests, mock_gen, service, sample_project, tmp_path):
        """Verify status='passed' when tests pass."""
        with get_session() as db:
            project = db.get(TestProject, sample_project.id)
            project.local_path = str(tmp_path)
            db.flush()

        (tmp_path / "pytest.ini").write_text("[pytest]\n")

        mock_gen.return_value = MockAgentResult(
            files_changed=["test_app.py"],
            summary="Generated 5 tests",
        )
        mock_run_tests.return_value = (0, "5 passed", "")

        run = service.create_run(project_id=sample_project.id)
        result = service.execute_run(run.id, {"ai": {"api_key": "k"}, "agent": {}})

        assert result is not None
        assert result.status == "passed"
        assert result.total_tests == 5
        assert result.passed_tests == 5
        assert result.failed_tests == 0

    @patch("src.services.testing_service.TestingService._generate_tests")
    @patch("src.code.executor.run_tests")
    def test_execute_run_failed(self, mock_run_tests, mock_gen, service, sample_project, tmp_path):
        """Verify status='failed' when tests fail."""
        with get_session() as db:
            project = db.get(TestProject, sample_project.id)
            project.local_path = str(tmp_path)
            db.flush()

        (tmp_path / "pytest.ini").write_text("[pytest]\n")

        mock_gen.return_value = MockAgentResult(
            files_changed=["test_app.py"],
            summary="Generated 3 tests",
        )
        mock_run_tests.return_value = (1, "2 passed, 1 failed", "FAILED test_app.py::test_bad")

        run = service.create_run(project_id=sample_project.id)
        result = service.execute_run(run.id, {"ai": {"api_key": "k"}, "agent": {}})

        assert result is not None
        assert result.status == "failed"
        assert result.total_tests == 3
        assert result.passed_tests == 2
        assert result.failed_tests == 1

    @patch("src.services.testing_service.TestingService._generate_tests")
    def test_execute_run_agent_exception(self, mock_gen, service, sample_project, tmp_path):
        """Verify status='error' when agent throws an exception."""
        with get_session() as db:
            project = db.get(TestProject, sample_project.id)
            project.local_path = str(tmp_path)
            db.flush()

        mock_gen.side_effect = RuntimeError("LLM API timeout")

        run = service.create_run(project_id=sample_project.id)
        result = service.execute_run(run.id, {"ai": {"api_key": "k"}, "agent": {}})

        assert result is None
        fetched = service.get_run(run.id)
        assert fetched.status == "error"
        assert "LLM API timeout" in fetched.result_summary

    @patch("src.services.testing_service.TestingService._generate_tests")
    @patch("src.code.executor.run_tests")
    def test_execute_run_evidence_created(self, mock_run_tests, mock_gen, service, sample_project, tmp_path):
        """Verify evidence records are created for logs, files, and reports."""
        with get_session() as db:
            project = db.get(TestProject, sample_project.id)
            project.local_path = str(tmp_path)
            db.flush()

        (tmp_path / "pytest.ini").write_text("[pytest]\n")

        mock_gen.return_value = MockAgentResult(
            files_changed=["test_one.py", "test_two.py"],
            summary="Generated 2 test files",
        )
        mock_run_tests.return_value = (0, "10 passed", "")

        run = service.create_run(project_id=sample_project.id)
        service.execute_run(run.id, {"ai": {"api_key": "k"}, "agent": {}})

        evidences = service.list_evidences(run.id)
        types = [e.evidence_type for e in evidences]
        assert "log" in types        # test output log
        assert "file" in types       # generated test files
        assert "report" in types     # agent summary

        file_evidences = [e for e in evidences if e.evidence_type == "file"]
        assert len(file_evidences) == 2

    @patch("src.services.testing_service.TestingService._generate_tests")
    @patch("src.code.executor.run_tests")
    def test_execute_run_progress_callback(self, mock_run_tests, mock_gen, service, sample_project, tmp_path):
        """Verify progress_callback is called with increasing percentages."""
        with get_session() as db:
            project = db.get(TestProject, sample_project.id)
            project.local_path = str(tmp_path)
            db.flush()

        (tmp_path / "pytest.ini").write_text("[pytest]\n")

        mock_gen.return_value = MockAgentResult(
            files_changed=[], summary="OK",
        )
        mock_run_tests.return_value = (0, "1 passed", "")

        progress_events = []
        def callback(event):
            progress_events.append(event)

        run = service.create_run(project_id=sample_project.id)
        service.execute_run(
            run.id, {"ai": {"api_key": "k"}, "agent": {}},
            progress_callback=callback,
        )

        assert len(progress_events) >= 5
        # Progress should be increasing
        pcts = [e.get("progress", 0) for e in progress_events if "progress" in e]
        assert pcts == sorted(pcts)
        assert pcts[-1] == 100

        # Should end with a complete event
        assert progress_events[-1]["type"] == "complete"

    def test_parse_pytest_output(self, service):
        """Test parsing pytest output format."""
        total, passed, failed, skipped = service._parse_test_output(
            "10 passed, 2 failed, 1 skipped in 5.2s", "", "python"
        )
        assert total == 13
        assert passed == 10
        assert failed == 2
        assert skipped == 1

    def test_parse_pytest_all_passed(self, service):
        total, passed, failed, skipped = service._parse_test_output(
            "25 passed in 3.1s", "", "python"
        )
        assert total == 25
        assert passed == 25
        assert failed == 0
        assert skipped == 0

    def test_parse_pytest_failed_first(self, service):
        total, passed, failed, skipped = service._parse_test_output(
            "3 failed, 7 passed", "", "python"
        )
        assert total == 10
        assert passed == 7
        assert failed == 3

    def test_parse_maven_output(self, service):
        """Test parsing Maven surefire output format."""
        total, passed, failed, skipped = service._parse_test_output(
            "", "Tests run: 15, Failures: 2, Errors: 1, Skipped: 3", "java_maven"
        )
        assert total == 15
        assert passed == 9
        assert failed == 3  # 2 failures + 1 error
        assert skipped == 3

    def test_parse_junit5_output(self, service):
        """Test parsing JUnit 5 output format."""
        total, passed, failed, skipped = service._parse_test_output(
            "8 tests successful\n2 tests failed", "", "java_maven"
        )
        assert total == 10
        assert passed == 8
        assert failed == 2

    def test_parse_empty_output(self, service):
        """No recognizable output → zeros."""
        total, passed, failed, skipped = service._parse_test_output("", "", "python")
        assert total == 0
        assert passed == 0

    def test_resolve_repo_path_local(self, service, tmp_path):
        """Local path exists → returns it."""
        result = service._resolve_repo_path(str(tmp_path), "")
        assert result == str(tmp_path)

    def test_resolve_repo_path_missing(self, service):
        """No local path, no URL → returns None."""
        result = service._resolve_repo_path("/nonexistent", "")
        assert result is None

    def test_build_requirements_prompt(self, service, tmp_path):
        """Requirements prompt includes run type, scope, and strategy context."""
        prompt = service._build_requirements_prompt(
            run_type="functional",
            target_scope="UserController",
            strategy="unit",
            language="java",
            framework="spring",
            discovery={
                "endpoints": [{"file": "UserController.java", "type": "REST"}],
                "services": [{"file": "UserService.java", "type": "service"}],
            },
            repo_path=str(tmp_path),
        )
        assert "functional" in prompt
        assert "UserController" in prompt
        assert "Unit Testing" in prompt or "unit" in prompt.lower()

    def test_build_requirements_security(self, service, tmp_path):
        """Security run type includes security-specific guidance."""
        prompt = service._build_requirements_prompt(
            run_type="security",
            target_scope="",
            strategy="auto",
            language="java",
            framework="spring",
            discovery={},
            repo_path=str(tmp_path),
        )
        assert "security" in prompt.lower()
        assert "SQL injection" in prompt or "OWASP" in prompt
