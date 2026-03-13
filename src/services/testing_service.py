"""
Testing platform service — orchestrates project onboarding, test runs,
coverage analysis, data injection, custom steps, and chat.
"""

import hashlib
import logging
import os
import re
import shutil
import subprocess
import tempfile
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from src.data.database import get_session
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

logger = logging.getLogger(__name__)


def _uuid() -> str:
    return uuid.uuid4().hex[:16]


class TestingService:
    """High-level service for the enterprise testing platform."""

    # ------------------------------------------------------------------
    # Test Projects (Onboarding)
    # ------------------------------------------------------------------

    def list_projects(
        self, *, status: Optional[str] = None, repo_id: Optional[str] = None, limit: int = 50
    ) -> list[TestProject]:
        with get_session() as db:
            q = db.query(TestProject)
            if status:
                q = q.filter(TestProject.status == status)
            if repo_id:
                q = q.filter(TestProject.repo_id == repo_id)
            return q.order_by(TestProject.created_at.desc()).limit(limit).all()

    def get_project(self, project_id: str) -> Optional[TestProject]:
        with get_session() as db:
            return db.get(TestProject, project_id)

    def create_project(
        self,
        *,
        name: str,
        repo_id: str = "",
        repo_url: str = "",
        local_path: str = "",
        language: str = "auto",
        framework: str = "auto",
        testing_framework: str = "auto",
        branch: str = "main",
        config: dict | None = None,
    ) -> TestProject:
        from src.agent.knowledge import compute_repo_id

        if not repo_id:
            repo_id = compute_repo_id(local_path, repo_url)

        with get_session() as db:
            repo = db.get(Repo, repo_id)
            if repo is None:
                repo = Repo(
                    id=repo_id,
                    url=repo_url,
                    local_path=local_path,
                    platform=self._detect_platform(repo_url),
                )
                db.add(repo)
                db.flush()

            project = TestProject(
                id=_uuid(),
                repo_id=repo.id,
                name=name,
                repo_url=repo_url,
                local_path=local_path,
                language=language,
                framework=framework,
                testing_framework=testing_framework,
                branch=branch,
                status="pending",
                config=config or {},
            )
            db.add(project)
            db.flush()
            db.expunge(project)
        return project

    @staticmethod
    def _detect_platform(repo_url: str) -> str:
        """Detect platform from repository URL."""
        if not repo_url:
            return "local"
        if "github.com" in repo_url:
            return "github"
        if "bitbucket" in repo_url:
            return "bitbucket"
        return "local"

    def delete_project(self, project_id: str) -> bool:
        with get_session() as db:
            project = db.get(TestProject, project_id)
            if not project:
                return False
            db.delete(project)
            return True

    def run_discovery(self, project_id: str) -> Optional[TestProject]:
        """Run auto-discovery on a project to find endpoints, services, DTOs."""
        with get_session() as db:
            project = db.get(TestProject, project_id)
            if not project:
                return None

            discovery = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "endpoints": [],
                "services": [],
                "dto_classes": [],
                "test_files": [],
                "frameworks_detected": [],
            }

            # Resolve local path (auto-clone if needed)
            repo_path = project.local_path or ""
            if (not repo_path or not Path(repo_path).is_dir()) and project.repo_id:
                try:
                    from src.services.config_service import ConfigService
                    from src.services.repo_service import RepoService
                    config = ConfigService().load_config()
                    repo_path = RepoService().ensure_local_clone(
                        project.repo_id,
                        branch=project.branch or "main",
                        config=config,
                    )
                    project.local_path = repo_path
                    db.flush()
                except Exception as exc:
                    logger.warning("Could not resolve local path for discovery on project %s: %s", project_id, exc)

            if repo_path and Path(repo_path).exists():
                discovery = self._discover_from_path(Path(repo_path), project.language)

            project.discovery_result = discovery
            project.status = "ready" if discovery.get("endpoints") or discovery.get("services") else "ready"

            # Auto-detect language and framework if set to "auto"
            if project.language == "auto" and discovery.get("frameworks_detected"):
                for fw in discovery["frameworks_detected"]:
                    if fw in ("spring", "springboot", "maven", "gradle"):
                        project.language = "java"
                        break
                    elif fw in ("django", "flask", "fastapi", "pytest"):
                        project.language = "python"
                        break

            if project.framework == "auto" and discovery.get("frameworks_detected"):
                for fw in discovery["frameworks_detected"]:
                    if fw in ("spring", "springboot"):
                        project.framework = "spring"
                        break
                    elif fw in ("django",):
                        project.framework = "django"
                        break
                    elif fw in ("flask",):
                        project.framework = "flask"
                        break

            db.flush()
            db.expunge(project)
        return project

    # Strategy display names and guidance for gap suggestions
    STRATEGY_GUIDANCE = {
        "unit": {"name": "Unit Tests", "suggestion": "Add unit tests with mocks for isolated class testing"},
        "integration": {"name": "Integration Tests", "suggestion": "Add integration tests with real dependencies"},
        "bdd": {"name": "BDD / Cucumber", "suggestion": "Add Gherkin feature files with step definitions"},
        "contract": {"name": "Contract Tests", "suggestion": "Add Pact/contract tests for API consumers"},
        "e2e": {"name": "End-to-End Tests", "suggestion": "Add E2E tests with Selenium/Playwright"},
        "soap": {"name": "SOAP Tests", "suggestion": "Add MockWebServiceServer tests for SOAP endpoints"},
        "jisi_bdd": {"name": "JISI BDD", "suggestion": "Add JISI-framework BDD features with ServiceBase steps"},
        "security_bdd": {"name": "Security BDD", "suggestion": "Add security-focused BDD scenarios"},
        "messaging": {"name": "Messaging Tests", "suggestion": "Add integration tests for Kafka consumers/producers with EmbeddedKafka or Testcontainers"},
        "unknown": {"name": "Other Tests", "suggestion": "Classify and organise test files by strategy"},
    }

    @staticmethod
    def _normalize_test_stem(stem: str) -> str:
        """Strip common test suffixes/prefixes to get the source class name."""
        name = re.sub(r'^test_', '', stem)
        name = re.sub(r'(Tests?|IT|IntegrationTest|IntegrationTests|Spec|TestCase)$', '', name)
        return name

    def _classify_test_file(self, file_path: str, content: str, language: str) -> str:
        """Classify a test file into a testing strategy based on heuristics."""
        path_lower = file_path.lower()

        # .feature files
        if path_lower.endswith(".feature"):
            if "/security/" in path_lower or "@Security" in content:
                return "security_bdd"
            if any(kw in content for kw in ("ServiceBase", "CommonSteps", "GenericSteps")):
                return "jisi_bdd"
            return "bdd"

        # E2E
        if any(kw in content for kw in ("WebDriver", "Playwright", "selenium")) or "/e2e/" in path_lower:
            return "e2e"

        # Contract
        if any(seg in path_lower for seg in ("/contract/", "/pact/")) or any(
            kw in content for kw in ("@PactVerification", "ContractVerifier")
        ):
            return "contract"

        # Messaging / Kafka tests (any language)
        if any(kw in content for kw in (
            "EmbeddedKafka", "@EmbeddedKafka", "KafkaTemplate",
            "@KafkaListener", "kafka", "KafkaConsumer", "KafkaProducer",
            "TopicBuilder", "ConsumerRecord", "ProducerRecord",
        )) or any(seg in path_lower for seg in ("/kafka/", "/messaging/")):
            return "messaging"

        # Integration (Java)
        if language == "java":
            stem = Path(file_path).stem
            if stem.endswith("IT") or stem.endswith("IntegrationTest"):
                return "integration"
            if any(kw in content for kw in ("@SpringBootTest", "@DataJpaTest", "TestContainers")):
                return "integration"
            if "MockWebServiceServer" in content or "SOAPMessage" in content:
                return "soap"
            if "@Test" in content or "@Mock" in content:
                return "unit"

        # Integration (Python)
        if language == "python":
            if "TestClient" in content or "/integration/" in path_lower:
                return "integration"
            return "unit"

        return "unknown"

    def _discover_from_path(self, repo_path: Path, language: str = "auto") -> dict:
        """Perform auto-discovery on a repository path."""
        discovery = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "endpoints": [],
            "services": [],
            "messaging": [],
            "dto_classes": [],
            "test_files": [],
            "specifications": [],
            "frameworks_detected": [],
        }

        skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv", "target", "build", ".gradle"}

        # Detect build system / frameworks
        if (repo_path / "pom.xml").exists():
            discovery["frameworks_detected"].append("maven")
        if (repo_path / "build.gradle").exists() or (repo_path / "build.gradle.kts").exists():
            discovery["frameworks_detected"].append("gradle")
        if (repo_path / "requirements.txt").exists() or (repo_path / "setup.py").exists():
            discovery["frameworks_detected"].append("python")
        if (repo_path / "pytest.ini").exists() or (repo_path / "pyproject.toml").exists():
            discovery["frameworks_detected"].append("pytest")

        # Scan for Java controllers/services
        for java_file in repo_path.rglob("*.java"):
            if any(skip in java_file.parts for skip in skip_dirs):
                continue
            try:
                content = java_file.read_text(errors="ignore")
                rel = str(java_file.relative_to(repo_path))

                if "@RestController" in content or "@Controller" in content:
                    discovery["endpoints"].append({
                        "file": rel,
                        "type": "REST",
                        "annotations": self._extract_annotations(content),
                    })
                    if "spring" not in discovery["frameworks_detected"]:
                        discovery["frameworks_detected"].append("spring")

                if "@Service" in content:
                    discovery["services"].append({"file": rel, "type": "service"})
                elif "@Component" in content:
                    discovery["services"].append({"file": rel, "type": "component"})
                elif "@Repository" in content:
                    discovery["services"].append({"file": rel, "type": "repository"})
                elif "@Configuration" in content:
                    discovery["services"].append({"file": rel, "type": "configuration"})

                # Kafka / messaging producers and consumers
                if "@KafkaListener" in content:
                    discovery["messaging"].append({"file": rel, "type": "kafka", "direction": "consumer"})
                if "KafkaTemplate" in content or "@SendTo" in content:
                    discovery["messaging"].append({"file": rel, "type": "kafka", "direction": "producer"})
                if "@JmsListener" in content:
                    discovery["messaging"].append({"file": rel, "type": "jms", "direction": "consumer"})
                if "JmsTemplate" in content:
                    discovery["messaging"].append({"file": rel, "type": "jms", "direction": "producer"})
                if "@RabbitListener" in content:
                    discovery["messaging"].append({"file": rel, "type": "rabbitmq", "direction": "consumer"})
                if "RabbitTemplate" in content or "AmqpTemplate" in content:
                    discovery["messaging"].append({"file": rel, "type": "rabbitmq", "direction": "producer"})
                if "@StreamListener" in content:
                    discovery["messaging"].append({"file": rel, "type": "spring-cloud-stream", "direction": "consumer"})

                if "Request" in java_file.stem or "Response" in java_file.stem or "Dto" in java_file.stem.lower():
                    discovery["dto_classes"].append({"file": rel})

                if "Test" in java_file.stem or "test" in str(java_file.parent):
                    strategy = self._classify_test_file(rel, content, "java")
                    discovery["test_files"].append({"file": rel, "language": "java", "strategy": strategy})
            except Exception:
                continue

        # Scan for Python test files
        for py_file in repo_path.rglob("*.py"):
            if any(skip in py_file.parts for skip in skip_dirs):
                continue
            rel = str(py_file.relative_to(repo_path))
            if py_file.stem.startswith("test_") or py_file.stem.endswith("_test"):
                try:
                    py_content = py_file.read_text(errors="ignore")[:2000]
                except Exception:
                    py_content = ""
                strategy = self._classify_test_file(rel, py_content, "python")
                discovery["test_files"].append({"file": rel, "language": "python", "strategy": strategy})

        # Scan for Gherkin feature files
        for feature_file in repo_path.rglob("*.feature"):
            if any(skip in feature_file.parts for skip in skip_dirs):
                continue
            rel = str(feature_file.relative_to(repo_path))
            try:
                feat_content = feature_file.read_text(errors="ignore")[:2000]
            except Exception:
                feat_content = ""
            strategy = self._classify_test_file(rel, feat_content, "gherkin")
            discovery["test_files"].append({"file": rel, "language": "gherkin", "strategy": strategy})

        # Scan for Drools rule files (.drl) — classify as services (business logic)
        for drl_file in repo_path.rglob("*.drl"):
            if any(skip in drl_file.parts for skip in skip_dirs):
                continue
            rel = str(drl_file.relative_to(repo_path))
            discovery["services"].append({"file": rel, "type": "drools-rule"})

        # Fallback: if no endpoints/services/messaging found, detect all non-test
        # Java source files under src/main as coverable source classes
        if not discovery["endpoints"] and not discovery["services"] and not discovery["messaging"]:
            source_stems_seen: set[str] = set()
            for java_file in repo_path.rglob("*.java"):
                if any(skip in java_file.parts for skip in skip_dirs):
                    continue
                rel = str(java_file.relative_to(repo_path))
                # Skip test files
                if "Test" in java_file.stem or "/test/" in rel.replace("\\", "/"):
                    continue
                # Only source files under src/main (or any non-test path)
                rel_posix = rel.replace("\\", "/")
                if "src/main" in rel_posix or "/test/" not in rel_posix:
                    if java_file.stem not in source_stems_seen:
                        source_stems_seen.add(java_file.stem)
                        discovery["services"].append({"file": rel, "type": "source"})

        # Check for servlet XML files (JISI) — classify as specifications
        for xml_file in repo_path.rglob("*servlet*.xml"):
            if any(skip in xml_file.parts for skip in skip_dirs):
                continue
            rel = str(xml_file.relative_to(repo_path))
            if "rest" in xml_file.stem.lower():
                discovery["specifications"].append({"file": rel, "type": "REST-servlet"})
            elif "cxf" in xml_file.stem.lower():
                discovery["specifications"].append({"file": rel, "type": "SOAP-servlet"})

        # Check for OpenAPI/Swagger specs — classify as specifications
        for spec_name in ("openapi.yaml", "openapi.yml", "openapi.json", "swagger.yaml", "swagger.yml", "swagger.json"):
            for spec_file in repo_path.rglob(spec_name):
                if any(skip in spec_file.parts for skip in skip_dirs):
                    continue
                discovery["specifications"].append({
                    "file": str(spec_file.relative_to(repo_path)),
                    "type": "OpenAPI",
                })

        # Check for WSDL files — classify as specifications
        for wsdl_file in repo_path.rglob("*.wsdl"):
            if any(skip in wsdl_file.parts for skip in skip_dirs):
                continue
            discovery["specifications"].append({
                "file": str(wsdl_file.relative_to(repo_path)),
                "type": "WSDL",
            })

        return discovery

    def _extract_annotations(self, content: str) -> list[str]:
        """Extract Spring annotation values from Java source."""
        import re
        annotations = []
        for pattern in (
            r'@RequestMapping\s*\(\s*(?:value\s*=\s*)?["\']([^"\']+)',
            r'@GetMapping\s*\(\s*(?:value\s*=\s*)?["\']([^"\']+)',
            r'@PostMapping\s*\(\s*(?:value\s*=\s*)?["\']([^"\']+)',
            r'@PutMapping\s*\(\s*(?:value\s*=\s*)?["\']([^"\']+)',
            r'@DeleteMapping\s*\(\s*(?:value\s*=\s*)?["\']([^"\']+)',
        ):
            annotations.extend(re.findall(pattern, content))
        return annotations

    # ------------------------------------------------------------------
    # Test Runs (Agent Monitoring)
    # ------------------------------------------------------------------

    def list_runs(
        self,
        *,
        project_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> list[TestRun]:
        with get_session() as db:
            q = db.query(TestRun)
            if project_id:
                q = q.filter(TestRun.project_id == project_id)
            if status:
                q = q.filter(TestRun.status == status)
            return q.order_by(TestRun.created_at.desc()).limit(limit).all()

    def get_run(self, run_id: str) -> Optional[TestRun]:
        with get_session() as db:
            return db.get(TestRun, run_id)

    def create_run(
        self,
        *,
        project_id: str,
        run_type: str = "functional",
        target_scope: str = "",
        strategy: str = "auto",
        config: dict | None = None,
        branch: str = "",
    ) -> TestRun:
        run = TestRun(
            id=_uuid(),
            project_id=project_id,
            run_type=run_type,
            target_scope=target_scope,
            strategy=strategy,
            status="queued",
            config=config or {},
            branch=branch or "main",
        )
        with get_session() as db:
            db.add(run)
            db.flush()
            db.expunge(run)
        return run

    def cancel_run(self, run_id: str) -> Optional[TestRun]:
        with get_session() as db:
            run = db.get(TestRun, run_id)
            if not run:
                return None
            run.status = "cancelled"
            run.completed_at = datetime.now(timezone.utc)
            db.flush()
            db.expunge(run)
        return run

    def retry_run(self, run_id: str) -> Optional[TestRun]:
        """Reset a queued/failed/error run back to queued for re-execution."""
        with get_session() as db:
            run = db.get(TestRun, run_id)
            if not run or run.status not in ("queued", "failed", "error"):
                return None
            run.status = "queued"
            run.started_at = None
            run.completed_at = None
            run.progress_pct = 0.0
            run.total_tests = 0
            run.passed_tests = 0
            run.failed_tests = 0
            run.skipped_tests = 0
            run.result_summary = ""
            run.artifacts = {}
            run.log = []
            run.agent_id = None
            db.flush()
            db.expunge(run)
        return run

    def get_queued_runs(self) -> list[TestRun]:
        """Get all runs still in 'queued' status (for startup recovery)."""
        with get_session() as db:
            return (
                db.query(TestRun)
                .filter(TestRun.status == "queued")
                .order_by(TestRun.created_at.asc())
                .all()
            )

    def execute_run(
        self,
        run_id: str,
        config: dict,
        progress_callback: Optional[Callable[[dict], None]] = None,
    ) -> Optional[TestRun]:
        """Execute a queued test run: generate tests, run them, capture results.

        This is the main execution pipeline called from a background thread.
        """

        def _progress(pct: float, stage: str, detail: str = ""):
            """Update progress in DB and notify via callback."""
            with get_session() as db:
                run = db.get(TestRun, run_id)
                if run:
                    run.progress_pct = pct
                    log_entry = {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "stage": stage,
                        "detail": detail,
                        "progress": pct,
                    }
                    run.log = (run.log or []) + [log_entry]
                    db.flush()
            if progress_callback:
                progress_callback({
                    "type": "progress",
                    "run_id": run_id,
                    "progress": pct,
                    "stage": stage,
                    "detail": detail,
                })

        def _log_event(event_type: str, message: str):
            """Append a log entry without changing progress percentage."""
            with get_session() as db:
                run = db.get(TestRun, run_id)
                if run:
                    log_entry = {
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "stage": event_type,
                        "detail": message,
                        "progress": run.progress_pct,
                    }
                    run.log = (run.log or []) + [log_entry]
                    db.flush()
            if progress_callback:
                progress_callback({
                    "type": "log",
                    "run_id": run_id,
                    "stage": event_type,
                    "detail": message,
                })

        try:
            # --- A. Initialize ---
            _progress(5, "initializing", "Loading project and run")
            with get_session() as db:
                run = db.get(TestRun, run_id)
                if not run:
                    logger.error("Test run %s not found", run_id)
                    return None
                project = db.get(TestProject, run.project_id)
                if not project:
                    logger.error("Project for run %s not found", run_id)
                    return None

                run.status = "running"
                run.started_at = datetime.now(timezone.utc)
                run.agent_id = f"worker-{_uuid()}"
                db.flush()

                # Snapshot values we need outside the session
                # Resolve repo_url/local_path from parent Repo, falling back to project fields
                parent_repo = db.get(Repo, project.repo_id) if project.repo_id else None
                project_id = project.id
                repo_url = (parent_repo.url if parent_repo and parent_repo.url else project.repo_url)
                local_path = (parent_repo.local_path if parent_repo and parent_repo.local_path else project.local_path)
                language = project.language
                framework = project.framework
                run_type = run.run_type
                target_scope = run.target_scope
                strategy = run.strategy
                discovery = project.discovery_result or {}
                project_config = project.config or {}

            # --- B. Resolve repo path ---
            _progress(10, "resolving_repo", "Resolving repository path")
            repo_path = self._resolve_repo_path(local_path, repo_url)
            if not repo_path:
                raise RuntimeError(
                    f"Cannot resolve repository: local_path={local_path!r}, repo_url={repo_url!r}"
                )
            if local_path and Path(local_path).exists():
                _log_event("resolving_repo", f"Using local path: {local_path}")
            elif repo_url:
                _log_event("resolving_repo", f"Cloned from: {repo_url}")

            # --- C. Auto-discovery ---
            _progress(20, "discovery", "Running auto-discovery")
            if not discovery.get("endpoints") and not discovery.get("services"):
                updated = self.run_discovery(project_id)
                if updated:
                    discovery = updated.discovery_result or {}

            # Log discovery results
            ep_count = len(discovery.get("endpoints", []))
            svc_count = len(discovery.get("services", []))
            test_count = len(discovery.get("test_files", []))
            frameworks = discovery.get("frameworks_detected", [])
            if ep_count or svc_count:
                _log_event("discovery_result", f"Found {ep_count} endpoints, {svc_count} services")
            if test_count:
                _log_event("discovery_result", f"Found {test_count} existing test files")
            if frameworks:
                _log_event("discovery_result", f"Frameworks: {', '.join(frameworks)}")

            # --- D. Build requirements prompt ---
            _progress(30, "building_requirements", "Building test generation prompt")
            requirements = self._build_requirements_prompt(
                run_type=run_type,
                target_scope=target_scope,
                strategy=strategy,
                language=language,
                framework=framework,
                discovery=discovery,
                repo_path=repo_path,
                project_config=project_config,
            )
            _log_event("building_requirements", f"Strategy: {strategy} ({run_type})")
            if target_scope:
                _log_event("building_requirements", f"Scope: {target_scope}")

            # --- E. Generate tests ---
            _progress(40, "generating_tests", "Generating tests via agent")
            _log_event("generating_tests", "Invoking AI agent for test generation...")
            agent_result = self._generate_tests(
                repo_path=repo_path,
                requirements=requirements,
                config=config,
                repo_url=repo_url,
                strategy=strategy,
                log_fn=_log_event,
            )

            files_changed = agent_result.files_changed if agent_result else []
            agent_summary = agent_result.summary if agent_result else "No agent result"

            # Log agent results
            if files_changed:
                for f in files_changed[:10]:
                    _log_event("tool_call", f"write_file {Path(f).name}")
                if len(files_changed) > 10:
                    _log_event("tool_call", f"... and {len(files_changed) - 10} more files")
            else:
                _log_event("generating_tests", "Agent completed (no files changed)")

            # --- F. Execute tests ---
            _progress(70, "executing_tests", "Executing generated tests")
            from src.code.executor import run_tests, detect_project_type
            project_type = detect_project_type(repo_path)
            _log_event("executing_tests", f"Running {project_type} tests...")
            exit_code, stdout, stderr = run_tests(repo_path, project_type, timeout=300)

            # Log key output lines (last 5 stdout + error lines from stderr)
            if stdout:
                for line in stdout.strip().splitlines()[-5:]:
                    stripped = line.strip()
                    if stripped:
                        _log_event("test_output", stripped)
            if stderr and exit_code != 0:
                for line in stderr.strip().splitlines():
                    stripped = line.strip()
                    if stripped and ("[ERROR]" in stripped or "FAILURE" in stripped or "BUILD FAIL" in stripped):
                        _log_event("error", stripped)
                        break  # Just show the first meaningful error

            # --- G. Parse results ---
            _progress(80, "parsing_results", "Parsing test results")
            total, passed, failed, skipped = self._parse_test_output(
                stdout, stderr, project_type
            )
            _log_event("result", f"{passed} passed, {failed} failed, {skipped} skipped")

            # --- G2. Classify errors ---
            error_classifications = self._classify_test_errors(stdout, stderr, exit_code)
            if error_classifications:
                for ec in error_classifications:
                    _log_event(
                        "error_classification",
                        f"[{ec['type']}/{ec['subtype']}] {ec['message'][:100]}",
                    )
                _log_event(
                    "error_suggestion",
                    " | ".join(ec["suggestion"] for ec in error_classifications[:3]),
                )

            # --- H. Record evidence ---
            _progress(90, "recording_evidence", "Saving evidence and artifacts")
            _log_event("recording_evidence", f"Saving {len(files_changed)} generated files")
            self._record_evidence(
                run_id=run_id,
                stdout=stdout,
                stderr=stderr,
                files_changed=files_changed,
                agent_summary=agent_summary,
                error_classifications=error_classifications,
            )

            # --- I. Finalize ---
            # Use parsed results over exit code: if we found tests and none failed,
            # treat as passed even if exit_code is non-zero (e.g. pytest warnings,
            # collection errors in other files).
            if total > 0 and failed == 0:
                final_status = "passed"
            elif exit_code == 0:
                final_status = "passed"
            else:
                final_status = "failed"
            with get_session() as db:
                run = db.get(TestRun, run_id)
                if run:
                    run.status = final_status
                    run.total_tests = total
                    run.passed_tests = passed
                    run.failed_tests = failed
                    run.skipped_tests = skipped
                    run.progress_pct = 100.0
                    run.result_summary = agent_summary
                    run.completed_at = datetime.now(timezone.utc)
                    run.artifacts = {
                        "files_generated": files_changed,
                        "exit_code": exit_code,
                        "error_classifications": error_classifications or [],
                    }
                    db.flush()
                    db.expunge(run)

            _progress(100, "complete", f"Run {final_status}: {passed}/{total} passed")

            if progress_callback:
                progress_callback({
                    "type": "complete",
                    "run_id": run_id,
                    "status": final_status,
                    "total_tests": total,
                    "passed_tests": passed,
                    "failed_tests": failed,
                })

            return run

        except Exception as exc:
            # --- J. Error handling ---
            logger.error("Test run %s failed: %s", run_id, exc, exc_info=True)
            _log_event("error", str(exc))
            with get_session() as db:
                run = db.get(TestRun, run_id)
                if run:
                    run.status = "error"
                    run.result_summary = f"Execution error: {exc}"
                    run.completed_at = datetime.now(timezone.utc)
                    run.progress_pct = run.progress_pct or 0.0
                    db.flush()

                    # Record error evidence
                    evidence = TestEvidence(
                        id=_uuid(),
                        test_run_id=run_id,
                        evidence_type="log",
                        title="Execution Error",
                        content=str(exc),
                        extra_data={"error": True},
                    )
                    db.add(evidence)
                    db.flush()
                    db.expunge(run)

            if progress_callback:
                progress_callback({
                    "type": "error",
                    "run_id": run_id,
                    "error": str(exc),
                })
            return None

    def _resolve_repo_path(
        self, local_path: str, repo_url: str
    ) -> Optional[str]:
        """Resolve the repository path: use local_path or clone from repo_url."""
        if local_path and Path(local_path).exists():
            return local_path

        if repo_url:
            try:
                tmp_dir = tempfile.mkdtemp(prefix="ca-test-")
                result = subprocess.run(
                    ["git", "clone", "--depth", "1", repo_url, tmp_dir],
                    capture_output=True, text=True, timeout=120,
                )
                if result.returncode == 0:
                    return tmp_dir
                logger.error("git clone failed: %s", result.stderr)
            except Exception as exc:
                logger.error("Failed to clone %s: %s", repo_url, exc)

        return None

    def _build_requirements_prompt(
        self,
        *,
        run_type: str,
        target_scope: str,
        strategy: str,
        language: str,
        framework: str,
        discovery: dict,
        repo_path: str,
        project_config: dict | None = None,
    ) -> str:
        """Build the requirements prompt for the agent to generate tests."""
        from src.code.executor import detect_build_tool
        from src.code.testing_strategies import get_testing_strategy_context

        build_tool = detect_build_tool(repo_path)

        parts = []
        parts.append(f"Generate {run_type} tests for this {language} {framework} project.")

        if target_scope:
            parts.append(f"\nFocus on: {target_scope}")
        else:
            parts.append("\nGenerate tests for all discovered endpoints and services.")

        # Add discovery context
        endpoints = discovery.get("endpoints", [])
        services = discovery.get("services", [])
        if endpoints:
            ep_summary = ", ".join(
                ep.get("file", "unknown") for ep in endpoints[:10]
            )
            parts.append(f"\nDiscovered endpoints ({len(endpoints)}): {ep_summary}")
        if services:
            svc_summary = ", ".join(
                svc.get("file", "unknown") for svc in services[:10]
            )
            parts.append(f"\nDiscovered services ({len(services)}): {svc_summary}")

        # Add strategy context
        strategy_ctx = get_testing_strategy_context(
            strategy, build_tool, "\n".join(parts)
        )
        if strategy_ctx:
            parts.append(f"\n{strategy_ctx}")

        # Run-type specific guidance
        if run_type == "security":
            parts.append(
                "\nFocus on security testing: SQL injection, XSS, auth bypass, "
                "input validation, OWASP Top 10 vulnerabilities."
            )
        elif run_type == "regression":
            parts.append(
                "\nGenerate regression tests covering existing functionality. "
                "Ensure backward compatibility with existing behavior."
            )
        elif run_type == "smoke":
            parts.append(
                "\nGenerate minimal smoke tests: verify each endpoint responds "
                "with a valid status code and basic response structure."
            )

        # Inject reference repository patterns if available
        ref = (project_config or {}).get("reference_patterns", {})
        if ref:
            parts.append(f"\n## Reference Repository Patterns")
            parts.append(f"Learned from: {ref.get('reference_repo_url', 'N/A')}")

            step_defs = ref.get("step_definitions", [])
            if step_defs:
                parts.append("\n### Available Step Definitions (reuse these patterns):")
                for s in step_defs[:30]:
                    parts.append(f"- @{s['step_type']}(\"{s['pattern']}\")")
                    if s.get("implementation"):
                        parts.append(f"  Implementation: {s['implementation'][:200]}")

            features = ref.get("feature_summaries", [])
            if features:
                parts.append("\n### Example Feature Files (follow this structure):")
                for f in features[:5]:
                    parts.append(f"\n#### {f['file']}")
                    parts.append(f"```gherkin\n{f['content'][:1500]}\n```")

            maven_deps = ref.get("maven_dependencies", [])
            extra = ref.get("extra_maven_deps", [])
            if maven_deps or extra:
                parts.append("\n### Required Maven Dependencies (add to pom.xml):")
                for d in maven_deps:
                    if d.get("scope") in ("test", "") or "test" in d.get("artifactId", "").lower():
                        parts.append(d.get("xml", ""))
                for coord in extra:
                    parts.append(f"<!-- Additional: {coord} -->")

        return "\n".join(parts)

    def _generate_tests(
        self,
        *,
        repo_path: str,
        requirements: str,
        config: dict,
        repo_url: str,
        strategy: str,
        log_fn: Optional[Callable[[str, str], None]] = None,
    ):
        """Call the agent to generate tests. Returns AgentResult or None."""
        import io
        import sys
        import threading

        def _log(event_type: str, msg: str):
            if log_fn:
                log_fn(event_type, msg)

        try:
            from src.agent.analyzer import generate_changes_with_agent
            from src.agent.knowledge import load_repo_knowledge
            from src.code.executor import detect_build_tool
            from src.consciousness.core import build_or_load_consciousness

            ai_cfg = config.get("ai", {})
            # Resolve API key: check config first, then fall back to env var
            api_key = (ai_cfg.get("api_key") or "").strip()
            if not api_key:
                provider = (ai_cfg.get("provider") or "openai").lower()
                env_var = ai_cfg.get("api_key_env") or {
                    "openai": "OPENAI_API_KEY",
                    "anthropic": "ANTHROPIC_API_KEY",
                    "gemini": "GEMINI_API_KEY",
                }.get(provider, "OPENAI_API_KEY")
                api_key = os.environ.get(env_var, "")
            if not api_key:
                logger.warning("No LLM API key configured, skipping agent test generation")
                _log("generating_tests", "No LLM API key configured — skipping")
                return None

            agent_cfg = config.get("agent", {})
            agent_config = {
                "max_turns": int(agent_cfg.get("max_turns", 30)),
                "smart_summarization": agent_cfg.get("smart_summarization", True),
                "truncation_limit": int(agent_cfg.get("truncation_limit", 30000)),
                "skip_tests": False,
            }

            _log("generating_tests", "Building repository context...")
            consciousness = build_or_load_consciousness(
                repo_path, config, repo_url=repo_url
            )
            _log("generating_tests", "Repository context ready")

            code_index = None
            try:
                from src.code_index import build_or_load_code_index
                _log("generating_tests", "Building code index (scanning files, symbols)...")
                code_index = build_or_load_code_index(
                    repo_path, config, repo_url=repo_url, consciousness=consciousness
                )
                symbol_count = getattr(code_index, 'total_symbols', 0)
                file_count = getattr(code_index, 'total_files', 0)
                _log("discovery_result", f"Code index: {symbol_count} symbols in {file_count} files")
            except Exception:
                _log("generating_tests", "Code index skipped (optional)")

            repo_knowledge = load_repo_knowledge(repo_path)
            build_tool = detect_build_tool(repo_path)

            _log("generating_tests", "Starting agent LLM calls...")

            # Capture stdout to detect agent tool calls in real-time.
            # Use thread ID to only capture output from THIS run's thread,
            # preventing cross-contamination when multiple runs execute concurrently.
            original_stdout = sys.stdout
            my_thread_id = threading.current_thread().ident
            tool_call_pattern = re.compile(r'^\s*[\u25b8▸]\s+(\S+)\s+(.+)')

            class StdoutTee(io.TextIOBase):
                """Tee stdout to capture agent tool call lines from this thread only."""
                def write(self, text):
                    original_stdout.write(text)
                    if threading.current_thread().ident != my_thread_id:
                        return len(text)
                    for line in text.splitlines():
                        stripped = line.strip()
                        match = tool_call_pattern.match(stripped)
                        if match:
                            _log("tool_call", stripped.lstrip('\u25b8▸ '))
                        elif stripped.startswith('[code-index]') and 'Done' in stripped:
                            _log("generating_tests", stripped.replace('[code-index]', '').strip())
                        elif '[agent] LLM API error' in stripped or '[agent] Aborting' in stripped:
                            msg = stripped.replace('[agent]', '').strip()
                            _log("error", msg)
                    return len(text)

                def flush(self):
                    original_stdout.flush()

            sys.stdout = StdoutTee()
            try:
                result = generate_changes_with_agent(
                    requirements,
                    repo_path,
                    llm_config=ai_cfg,
                    verbose=ai_cfg.get("verbose", False),
                    consciousness=consciousness,
                    agent_config=agent_config,
                    config=config,
                    repo_url=repo_url,
                    repo_knowledge=repo_knowledge,
                    code_index=code_index,
                    build_tool=build_tool,
                )
            finally:
                sys.stdout = original_stdout

            return result
        except Exception as exc:
            logger.error("Agent test generation failed: %s", exc, exc_info=True)
            _log("error", f"Agent generation failed: {exc}")
            return None

    def _parse_test_output(
        self, stdout: str, stderr: str, project_type: str
    ) -> tuple[int, int, int, int]:
        """Parse test output to extract counts: (total, passed, failed, skipped)."""
        combined = stdout + "\n" + stderr

        # Python pytest: extract all counts individually
        passed_m = re.search(r'(\d+)\s+passed', combined)
        failed_m = re.search(r'(\d+)\s+failed', combined)
        skipped_m = re.search(r'(\d+)\s+skipped', combined)

        if passed_m or failed_m:
            passed = int(passed_m.group(1)) if passed_m else 0
            failed = int(failed_m.group(1)) if failed_m else 0
            skipped = int(skipped_m.group(1)) if skipped_m else 0
            total = passed + failed + skipped
            return total, passed, failed, skipped

        # Maven/Gradle surefire: "Tests run: X, Failures: Y, Errors: Z, Skipped: W"
        surefire_match = re.search(
            r'Tests run:\s*(\d+),\s*Failures:\s*(\d+),\s*Errors:\s*(\d+),\s*Skipped:\s*(\d+)',
            combined,
        )
        if surefire_match:
            total = int(surefire_match.group(1))
            failures = int(surefire_match.group(2))
            errors = int(surefire_match.group(3))
            skipped = int(surefire_match.group(4))
            failed = failures + errors
            passed = total - failed - skipped
            return total, max(passed, 0), failed, skipped

        # JUnit 5 format: "X tests successful", "Y tests failed"
        junit5_success = re.search(r'(\d+)\s+tests?\s+successful', combined)
        junit5_failed = re.search(r'(\d+)\s+tests?\s+failed', combined)
        if junit5_success or junit5_failed:
            passed = int(junit5_success.group(1)) if junit5_success else 0
            failed = int(junit5_failed.group(1)) if junit5_failed else 0
            total = passed + failed
            return total, passed, failed, 0

        # Fallback: couldn't parse
        return 0, 0, 0, 0

    def _classify_test_errors(
        self, stdout: str, stderr: str, exit_code: int
    ) -> list[dict]:
        """Classify test errors into actionable categories.

        Returns a list of dicts, each with:
          - type: compilation_error | assertion_failure | missing_dependency |
                  timeout | runtime_exception | build_failure | unknown
          - subtype: more specific classification
          - message: the matched error text (first 300 chars)
          - suggestion: actionable fix suggestion
        """
        combined = (stdout + "\n" + stderr).strip()
        if exit_code == 0 or not combined:
            return []

        classifications: list[dict] = []
        seen_types: set[str] = set()

        def _add(error_type: str, subtype: str, match_text: str, suggestion: str) -> None:
            key = f"{error_type}:{subtype}"
            if key not in seen_types:
                seen_types.add(key)
                classifications.append({
                    "type": error_type,
                    "subtype": subtype,
                    "message": match_text.strip()[:300],
                    "suggestion": suggestion,
                })

        # --- Compilation / Syntax errors ---
        for m in re.finditer(r'(SyntaxError|IndentationError|TabError):\s*(.+)', combined):
            _add("compilation_error", "python_syntax", m.group(0),
                 "Fix the Python syntax error — check indentation and brackets.")

        for m in re.finditer(r'error:\s*(cannot find symbol|illegal start|expected\b)', combined, re.I):
            _add("compilation_error", "java_compile", m.group(0),
                 "Fix the Java compilation error — check missing imports and type mismatches.")

        if re.search(r'COMPILATION ERROR|BUILD FAILURE.*Compilation failure', combined, re.I):
            line = next((l for l in combined.splitlines() if 'COMPILATION ERROR' in l or 'Compilation failure' in l), "")
            _add("compilation_error", "build_compile", line,
                 "Fix compilation errors before running tests. Check error output for missing imports or type errors.")

        # --- Missing dependencies / imports ---
        for m in re.finditer(r'(ModuleNotFoundError|ImportError):\s*(.+)', combined):
            _add("missing_dependency", "python_import", m.group(0),
                 f"Install the missing Python module or fix the import path.")

        for m in re.finditer(r'(NoClassDefFoundError|ClassNotFoundException):\s*(.+)', combined):
            _add("missing_dependency", "java_class", m.group(0),
                 "Add the missing dependency to pom.xml/build.gradle or fix the class reference.")

        if re.search(r'Could not resolve dependencies', combined, re.I):
            _add("missing_dependency", "build_dependency", "Could not resolve dependencies",
                 "Check pom.xml or build.gradle for correct dependency coordinates and versions.")

        # --- Assertion failures ---
        for m in re.finditer(r'(AssertionError|assert\s+.+==.+)', combined):
            _add("assertion_failure", "python_assert", m.group(0),
                 "Test assertion failed — check expected vs actual values and fix the logic.")

        for m in re.finditer(r'(org\.junit\..*AssertionError|expected:?\s*<.+>\s*but was:?\s*<.+>)', combined, re.I):
            _add("assertion_failure", "junit_assert", m.group(0),
                 "JUnit assertion failed — verify the expected value matches the actual output.")

        for m in re.finditer(r'(AssertionFailedError|org\.opentest4j\.AssertionFailedError)', combined):
            _add("assertion_failure", "junit5_assert", m.group(0),
                 "JUnit 5 assertion failed — check the test expectation against actual behavior.")

        # --- Timeout errors ---
        for m in re.finditer(r'(TimeoutError|timed?\s*out|timeout)', combined, re.I):
            _add("timeout", "execution_timeout", m.group(0),
                 "Test execution timed out — check for infinite loops, deadlocks, or increase timeout.")

        # --- Runtime exceptions ---
        for m in re.finditer(r'(NullPointerException)', combined):
            _add("runtime_exception", "null_pointer", m.group(0),
                 "NullPointerException — add null checks or ensure objects are properly initialized.")

        for m in re.finditer(r'(StackOverflowError)', combined):
            _add("runtime_exception", "stack_overflow", m.group(0),
                 "StackOverflowError — check for infinite recursion in the code.")

        for m in re.finditer(r'(OutOfMemoryError)', combined):
            _add("runtime_exception", "out_of_memory", m.group(0),
                 "OutOfMemoryError — reduce data size or increase memory allocation.")

        for m in re.finditer(r'(RuntimeError|RuntimeException):\s*(.+)', combined):
            _add("runtime_exception", "generic_runtime", m.group(0),
                 "Runtime exception — read the stack trace to identify the root cause.")

        # --- Build failures (non-compilation) ---
        if re.search(r'BUILD FAIL', combined, re.I) and "compilation_error" not in seen_types:
            line = next((l for l in combined.splitlines() if 'BUILD FAIL' in l), "")
            _add("build_failure", "maven_gradle", line,
                 "Build failed — check the full error output for dependency or plugin issues.")

        # --- Fallback: unknown error ---
        if not classifications and exit_code != 0:
            # Extract the most informative error line
            error_lines = [l for l in combined.splitlines()
                           if any(kw in l.lower() for kw in ("error", "fail", "exception"))]
            msg = error_lines[0] if error_lines else f"Exit code {exit_code}"
            _add("unknown", "unclassified", msg,
                 "Test run failed — review the full output to identify the root cause.")

        return classifications

    def _record_evidence(
        self,
        *,
        run_id: str,
        stdout: str,
        stderr: str,
        files_changed: list[str],
        agent_summary: str,
        error_classifications: list[dict] | None = None,
    ) -> None:
        """Record test evidence: logs, generated files, error analysis, and summary report."""
        with get_session() as db:
            # Test execution log
            if stdout or stderr:
                log_content = ""
                if stdout:
                    log_content += f"=== STDOUT ===\n{stdout}\n"
                if stderr:
                    log_content += f"=== STDERR ===\n{stderr}\n"
                evidence = TestEvidence(
                    id=_uuid(),
                    test_run_id=run_id,
                    evidence_type="log",
                    title="Test Execution Output",
                    content=log_content[:50000],  # Truncate very large output
                )
                db.add(evidence)

            # Error classification report
            if error_classifications:
                classification_lines = ["## Error Classification Report\n"]
                for ec in error_classifications:
                    classification_lines.append(
                        f"### [{ec['type']}/{ec['subtype']}]\n"
                        f"**Error:** {ec['message']}\n"
                        f"**Suggestion:** {ec['suggestion']}\n"
                    )
                evidence = TestEvidence(
                    id=_uuid(),
                    test_run_id=run_id,
                    evidence_type="report",
                    title="Error Classification",
                    content="\n".join(classification_lines),
                    extra_data={"classifications": error_classifications},
                )
                db.add(evidence)

            # Generated test files
            for file_path in files_changed:
                evidence = TestEvidence(
                    id=_uuid(),
                    test_run_id=run_id,
                    evidence_type="file",
                    title=f"Generated: {Path(file_path).name}",
                    content="",
                    file_path=file_path,
                    extra_data={"generated": True},
                )
                db.add(evidence)

            # Agent summary report
            if agent_summary:
                evidence = TestEvidence(
                    id=_uuid(),
                    test_run_id=run_id,
                    evidence_type="report",
                    title="Agent Summary",
                    content=agent_summary,
                )
                db.add(evidence)

            db.flush()

    def list_evidences(self, run_id: str) -> list[TestEvidence]:
        with get_session() as db:
            return (
                db.query(TestEvidence)
                .filter(TestEvidence.test_run_id == run_id)
                .order_by(TestEvidence.created_at.asc())
                .all()
            )

    # ------------------------------------------------------------------
    # Coverage helpers
    # ------------------------------------------------------------------

    def _compute_function_coverage(self, endpoints, test_files, repo_path, overall_pct):
        """Compute method-level function coverage by counting test methods vs API methods."""
        total_methods = sum(len(ep.get("annotations", [])) or 1 for ep in endpoints)
        if total_methods == 0:
            return overall_pct
        test_method_count = 0
        for tf in test_files:
            try:
                content = (Path(repo_path) / tf["file"]).read_text(errors="ignore")
            except Exception:
                continue
            if tf.get("language") == "java":
                test_method_count += len(re.findall(r'@Test\b', content))
            elif tf.get("language") == "python":
                test_method_count += len(re.findall(r'def test_\w+', content))
        return min(100.0, (test_method_count / total_methods) * 100) if test_method_count else overall_pct

    # ------------------------------------------------------------------
    # Coverage
    # ------------------------------------------------------------------

    def list_coverage_reports(
        self, project_id: str, *, limit: int = 10
    ) -> list[CoverageReport]:
        with get_session() as db:
            return (
                db.query(CoverageReport)
                .filter(CoverageReport.project_id == project_id)
                .order_by(CoverageReport.created_at.desc())
                .limit(limit)
                .all()
            )

    def analyze_coverage(
        self, project_id: str, branch: str = "", sonarqube_project_key: str = ""
    ) -> Optional[CoverageReport]:
        """Run coverage analysis on a project.

        Resolves the repo's local path (auto-cloning if needed), checks out the
        requested branch, re-runs discovery, and then calculates coverage.
        If SonarQube is configured, overlays line/branch coverage from real metrics.
        """
        from src.services.repo_service import RepoService

        with get_session() as db:
            project = db.get(TestProject, project_id)
            if not project:
                return None

            # --- Resolve local path (auto-clone if needed) ---
            repo_path = project.local_path or ""
            if not repo_path or not os.path.isdir(repo_path):
                # Try to resolve via the linked Repo record
                if project.repo_id:
                    try:
                        from src.services.config_service import ConfigService
                        config = ConfigService().load_config()
                        repo_path = RepoService().ensure_local_clone(
                            project.repo_id,
                            branch=branch or project.branch or "main",
                            config=config,
                        )
                        # Persist resolved path on the project
                        project.local_path = repo_path
                        db.flush()
                    except Exception as exc:
                        logger.warning("Could not resolve local path for project %s: %s", project_id, exc)

            # --- Checkout the selected branch ---
            effective_branch = branch or project.branch or ""
            if effective_branch and repo_path and os.path.isdir(repo_path):
                try:
                    # Unshallow if this is a shallow clone so all branches are reachable
                    subprocess.run(
                        ["git", "fetch", "--unshallow"],
                        cwd=repo_path, capture_output=True, text=True, timeout=300,
                    )
                    # Fetch the specific branch from origin
                    subprocess.run(
                        ["git", "fetch", "origin", effective_branch],
                        cwd=repo_path, capture_output=True, text=True, timeout=300,
                    )
                    # Try local checkout first
                    result = subprocess.run(
                        ["git", "checkout", effective_branch],
                        cwd=repo_path, capture_output=True, text=True, timeout=60,
                    )
                    if result.returncode != 0:
                        # Branch doesn't exist locally — create tracking branch from remote
                        result = subprocess.run(
                            ["git", "checkout", "-b", effective_branch, f"origin/{effective_branch}"],
                            cwd=repo_path, capture_output=True, text=True, timeout=60,
                        )
                    if result.returncode == 0:
                        logger.info("Checked out branch %s for coverage analysis", effective_branch)
                    else:
                        logger.warning(
                            "Git checkout result: %d, stdout: %s, stderr: %s",
                            result.returncode, result.stdout.strip(), result.stderr.strip(),
                        )
                except Exception as exc:
                    logger.warning("Could not checkout branch %s: %s", effective_branch, exc)

            # --- Re-run discovery on the current branch ---
            if repo_path and os.path.isdir(repo_path):
                discovery = self._discover_from_path(Path(repo_path), project.language or "auto")
                # Persist fresh discovery results
                project.discovery_result = discovery
                db.flush()
            else:
                discovery = project.discovery_result or {}

            endpoints = discovery.get("endpoints", [])
            test_files = discovery.get("test_files", [])
            services = discovery.get("services", [])
            messaging = discovery.get("messaging", [])

            # Normalise test file stems for matching
            tested_file_stems = {self._normalize_test_stem(Path(t["file"]).stem) for t in test_files}

            # Identify uncovered code items via stem matching
            uncovered = []
            for ep in endpoints:
                if Path(ep["file"]).stem not in tested_file_stems:
                    uncovered.append({
                        "type": "endpoint",
                        "file": ep["file"],
                        "endpoint_type": ep.get("type", "unknown"),
                        "priority": "high",
                    })

            for svc in services:
                if Path(svc["file"]).stem not in tested_file_stems:
                    uncovered.append({
                        "type": "service",
                        "file": svc["file"],
                        "priority": "medium",
                    })

            # Deduplicate messaging by file (a file may have both consumer + producer)
            messaging_files_seen: set[str] = set()
            for msg in messaging:
                if msg["file"] not in messaging_files_seen:
                    messaging_files_seen.add(msg["file"])
                    if Path(msg["file"]).stem not in tested_file_stems:
                        uncovered.append({
                            "type": "messaging",
                            "file": msg["file"],
                            "endpoint_type": msg.get("type", "kafka"),
                            "direction": msg.get("direction", ""),
                            "priority": "high",
                        })

            # Specs listed separately, not in main coverage calc
            for spec in discovery.get("specifications", []):
                uncovered.append({
                    "type": "specification",
                    "file": spec["file"],
                    "endpoint_type": spec.get("type", "spec"),
                    "priority": "low",
                })

            # Derive percentage from match results
            total_items = len(endpoints) + len(services) + len(messaging_files_seen)
            uncovered_code = [u for u in uncovered if u["type"] != "specification"]
            covered = total_items - len(uncovered_code)
            overall_pct = (covered / max(total_items, 1)) * 100

            # Compute real function coverage
            function_coverage = self._compute_function_coverage(
                endpoints, test_files, repo_path, overall_pct
            ) if repo_path and os.path.isdir(repo_path) else overall_pct

            # --- Suggest best strategy for each uncovered item ---
            def _suggest_strategy(item: dict) -> str:
                if item["type"] == "messaging":
                    return "messaging"
                ep_type = item.get("endpoint_type", "").lower()
                if ep_type in ("soap", "wsdl", "soap-servlet"):
                    return "soap"
                if ep_type == "rest":
                    return "integration"
                if item["type"] == "specification":
                    return "contract"
                return "unit"

            for item in uncovered:
                item["suggested_strategy"] = _suggest_strategy(item)

            # Generate gap suggestions
            gaps = []
            for item in uncovered[:10]:  # Top 10 gaps
                strat = item.get("suggested_strategy", "unit")
                guidance = self.STRATEGY_GUIDANCE.get(strat, self.STRATEGY_GUIDANCE["unit"])
                gaps.append({
                    "area": item["file"],
                    "gap_type": f"No tests for {item['type']}",
                    "suggestion": guidance["suggestion"] + f" for {item['file']}",
                    "priority": item.get("priority", "medium"),
                    "suggested_strategy": strat,
                })

            # --- Per-strategy breakdown from discovered files + TestRun data ---
            # Group test files by strategy
            files_by_strategy: dict[str, list[str]] = {}
            for tf in test_files:
                strat = tf.get("strategy", "unknown")
                files_by_strategy.setdefault(strat, []).append(tf["file"])

            # Query completed TestRun records for this project
            completed_runs = (
                db.query(TestRun)
                .filter(
                    TestRun.project_id == project_id,
                    TestRun.status.in_(["passed", "failed"]),
                )
                .order_by(TestRun.completed_at.desc())
                .all()
            )

            # Group runs by strategy
            runs_by_strategy: dict[str, list[TestRun]] = {}
            for run in completed_runs:
                s = run.strategy or "unknown"
                if s == "auto":
                    s = "unknown"
                runs_by_strategy.setdefault(s, []).append(run)

            # All strategies from both sources
            all_strategies = set(files_by_strategy.keys()) | set(runs_by_strategy.keys())
            all_strategies.discard("unknown")  # only include if explicitly present

            # Build the tested_stems per strategy for coverage calc
            all_source_stems = (
                {Path(ep["file"]).stem for ep in endpoints}
                | {Path(svc["file"]).stem for svc in services}
                | {Path(f).stem for f in messaging_files_seen}
            )

            strategy_breakdown = {}
            for strat in sorted(all_strategies | ({"unknown"} if "unknown" in files_by_strategy or "unknown" in runs_by_strategy else set())):
                strat_files = files_by_strategy.get(strat, [])
                strat_runs = runs_by_strategy.get(strat, [])

                total_tests = sum(r.total_tests for r in strat_runs)
                passed = sum(r.passed_tests for r in strat_runs)
                failed = sum(r.failed_tests for r in strat_runs)
                skipped = sum(r.skipped_tests for r in strat_runs)
                pass_rate = round((passed / max(total_tests, 1)) * 100, 1)

                latest = strat_runs[0] if strat_runs else None

                # Which source files does this strategy cover?
                strat_tested_stems = {
                    self._normalize_test_stem(Path(f).stem) for f in strat_files
                }
                covered_items = [
                    s for s in all_source_stems if s in strat_tested_stems
                ]
                strat_coverage = round(
                    (len(covered_items) / max(total_items, 1)) * 100, 1
                )

                # Derive covered endpoints/services lists
                covered_ep_files = [
                    ep["file"] for ep in endpoints if Path(ep["file"]).stem in strat_tested_stems
                ]
                covered_svc_files = [
                    svc["file"] for svc in services if Path(svc["file"]).stem in strat_tested_stems
                ]
                covered_msg_files = [
                    f for f in messaging_files_seen if Path(f).stem in strat_tested_stems
                ]

                strategy_breakdown[strat] = {
                    "strategy": strat,
                    "display_name": self.STRATEGY_GUIDANCE.get(strat, {}).get("name", strat.title()),
                    "test_file_count": len(strat_files),
                    "test_files": strat_files,
                    "run_count": len(strat_runs),
                    "total_tests": total_tests,
                    "passed": passed,
                    "failed": failed,
                    "skipped": skipped,
                    "pass_rate": pass_rate,
                    "latest_run_status": latest.status if latest else None,
                    "latest_run_at": latest.completed_at.isoformat() if latest and latest.completed_at else None,
                    "covered_endpoints": covered_ep_files,
                    "covered_services": covered_svc_files,
                    "covered_messaging": covered_msg_files,
                    "coverage_pct": strat_coverage,
                }

            # --- Test run summary ---
            total_runs = len(completed_runs)
            all_tests_executed = sum(r.total_tests for r in completed_runs)
            all_passed = sum(r.passed_tests for r in completed_runs)
            strategies_executed = sorted(s for s in runs_by_strategy if s != "unknown")
            expected_strategies = {"unit", "integration", "bdd", "contract", "e2e"}
            if messaging_files_seen:
                expected_strategies.add("messaging")
            strategies_missing = sorted(expected_strategies - set(strategies_executed))

            test_run_summary = {
                "total_runs": total_runs,
                "total_tests_executed": all_tests_executed,
                "overall_pass_rate": round((all_passed / max(all_tests_executed, 1)) * 100, 1),
                "strategies_executed": strategies_executed,
                "strategies_missing": strategies_missing,
            }

            line_coverage = 0.0
            branch_coverage = 0.0
            details = {
                "total_endpoints": len(endpoints),
                "total_services": len(services),
                "total_messaging": len(messaging_files_seen),
                "total_test_files": len(test_files),
                "total_specifications": len(discovery.get("specifications", [])),
                "frameworks": discovery.get("frameworks_detected", []),
                "strategy_breakdown": strategy_breakdown,
                "test_run_summary": test_run_summary,
            }

            # --- SonarQube overlay ---
            try:
                from src.services.config_service import ConfigService
                app_config = ConfigService().load_config()
            except Exception:
                app_config = {}

            sonar_config = app_config.get("sonarqube", {})
            if sonar_config.get("enabled") and sonar_config.get("base_url"):
                try:
                    from src.sonarqube.client import fetch_measures, fetch_quality_gate, derive_project_key

                    sq_key = sonarqube_project_key or derive_project_key(
                        sonar_config,
                        project.repo_url or "",
                        project.name,
                    )

                    measures = fetch_measures(sonar_config, sq_key)
                    quality_gate = fetch_quality_gate(sonar_config, sq_key)

                    if measures:
                        if "line_coverage" in measures:
                            line_coverage = float(measures["line_coverage"])
                        if "branch_coverage" in measures:
                            branch_coverage = float(measures["branch_coverage"])

                    details["sonarqube"] = {
                        "project_key": sq_key,
                        "measures": measures,
                        "quality_gate": quality_gate,
                    }
                except Exception as exc:
                    logger.warning("SonarQube overlay failed for project %s: %s", project_id, exc)

            report = CoverageReport(
                id=_uuid(),
                project_id=project_id,
                report_type="functional",
                overall_pct=round(overall_pct, 1),
                line_coverage=round(line_coverage, 1),
                branch_coverage=round(branch_coverage, 1),
                function_coverage=round(function_coverage, 1),
                uncovered_areas=uncovered,
                gaps=gaps,
                details=details,
            )
            db.add(report)
            db.flush()
            db.expunge(report)
        return report

    # ------------------------------------------------------------------
    # Data Injection
    # ------------------------------------------------------------------

    def list_data_injection_configs(self, project_id: str) -> list[DataInjectionConfig]:
        with get_session() as db:
            return (
                db.query(DataInjectionConfig)
                .filter(DataInjectionConfig.project_id == project_id)
                .order_by(DataInjectionConfig.created_at.desc())
                .all()
            )

    def create_data_injection_config(
        self,
        *,
        project_id: str,
        name: str,
        strategy: str = "synthetic",
        target_entity: str = "",
        schema_definition: dict | None = None,
        sample_data: list | None = None,
        environment_rules: dict | None = None,
    ) -> DataInjectionConfig:
        config = DataInjectionConfig(
            id=_uuid(),
            project_id=project_id,
            name=name,
            strategy=strategy,
            target_entity=target_entity,
            schema_definition=schema_definition or {},
            sample_data=sample_data or [],
            environment_rules=environment_rules or {},
        )
        with get_session() as db:
            db.add(config)
            db.flush()
            db.expunge(config)
        return config

    def delete_data_injection_config(self, config_id: str) -> bool:
        with get_session() as db:
            config = db.get(DataInjectionConfig, config_id)
            if not config:
                return False
            db.delete(config)
            return True

    def generate_sample_data(
        self, config_id: str, *, count: int = 5
    ) -> Optional[DataInjectionConfig]:
        """Generate synthetic sample data based on schema definition."""
        with get_session() as db:
            config = db.get(DataInjectionConfig, config_id)
            if not config:
                return None

            schema = config.schema_definition or {}
            samples = []
            for i in range(count):
                record = {}
                for field_name, field_def in schema.items():
                    field_type = field_def.get("type", "string") if isinstance(field_def, dict) else str(field_def)
                    record[field_name] = self._generate_field_value(field_name, field_type, i)
                samples.append(record)

            config.sample_data = samples
            db.flush()
            db.expunge(config)
        return config

    def _generate_field_value(self, name: str, field_type: str, index: int):
        """Generate a synthetic value based on field name and type."""
        name_lower = name.lower()
        if "email" in name_lower:
            return f"user{index + 1}@example.com"
        if "phone" in name_lower:
            return f"+1555000{1000 + index}"
        if "name" in name_lower and "first" in name_lower:
            names = ["John", "Jane", "Alice", "Bob", "Charlie"]
            return names[index % len(names)]
        if "name" in name_lower and "last" in name_lower:
            names = ["Smith", "Doe", "Johnson", "Williams", "Brown"]
            return names[index % len(names)]
        if "name" in name_lower:
            return f"TestEntity_{index + 1}"
        if "id" in name_lower:
            return f"ID-{10000 + index}"
        if "date" in name_lower or "time" in name_lower:
            return f"2026-01-{15 + index:02d}T10:00:00Z"
        if "amount" in name_lower or "price" in name_lower or "balance" in name_lower:
            return round(100.0 + index * 25.5, 2)
        if field_type in ("int", "integer", "long", "Integer", "Long"):
            return index + 1
        if field_type in ("float", "double", "decimal", "Float", "Double"):
            return round(1.0 + index * 0.5, 2)
        if field_type in ("boolean", "bool", "Boolean"):
            return index % 2 == 0
        return f"test_value_{index + 1}"

    # ------------------------------------------------------------------
    # Custom Steps
    # ------------------------------------------------------------------

    def list_custom_steps(self, project_id: str) -> list[CustomStep]:
        with get_session() as db:
            return (
                db.query(CustomStep)
                .filter(CustomStep.project_id == project_id)
                .order_by(CustomStep.created_at.desc())
                .all()
            )

    def create_custom_step(
        self,
        *,
        project_id: str,
        name: str,
        step_type: str = "given",
        pattern: str = "",
        implementation: str = "",
        language: str = "java",
        tags: list | None = None,
    ) -> CustomStep:
        step = CustomStep(
            id=_uuid(),
            project_id=project_id,
            name=name,
            step_type=step_type,
            pattern=pattern,
            implementation=implementation,
            language=language,
            tags=tags or [],
            source="user",
        )
        with get_session() as db:
            db.add(step)
            db.flush()
            db.expunge(step)
        return step

    def update_custom_step(
        self,
        step_id: str,
        *,
        name: str = "",
        step_type: str = "",
        pattern: str = "",
        implementation: str = "",
        language: str = "",
        tags: list | None = None,
    ) -> Optional[CustomStep]:
        with get_session() as db:
            step = db.get(CustomStep, step_id)
            if not step:
                return None
            if name:
                step.name = name
            if step_type:
                step.step_type = step_type
            if pattern:
                step.pattern = pattern
            if implementation:
                step.implementation = implementation
            if language:
                step.language = language
            if tags is not None:
                step.tags = tags
            db.flush()
            db.expunge(step)
        return step

    def delete_custom_step(self, step_id: str) -> bool:
        with get_session() as db:
            step = db.get(CustomStep, step_id)
            if not step:
                return False
            db.delete(step)
            return True

    def discover_custom_steps(self, project_id: str) -> list[CustomStep]:
        """Auto-discover custom step definitions from the project's test codebase."""
        with get_session() as db:
            project = db.get(TestProject, project_id)
            if not project:
                return []

            repo_path = Path(project.local_path) if project.local_path else None
            if not repo_path or not repo_path.exists():
                return []

            step_dicts = self._discover_steps_from_path(repo_path)
            discovered_steps = []
            for sd in step_dicts:
                step = CustomStep(
                    id=_uuid(),
                    project_id=project_id,
                    name=f"{sd['step_type']}: {sd['pattern'][:50]}",
                    step_type=sd["step_type"],
                    pattern=sd["pattern"],
                    implementation=sd.get("implementation", ""),
                    language=sd.get("language", "java"),
                    tags=["discovered"],
                    source="discovered",
                )
                db.add(step)
                discovered_steps.append(step)

            db.flush()
            for s in discovered_steps:
                db.expunge(s)
        return discovered_steps

    # ------------------------------------------------------------------
    # Reference Repo Learning
    # ------------------------------------------------------------------

    def _discover_steps_from_path(self, repo_path: Path) -> list[dict]:
        """Scan a directory for step definition files and extract patterns + implementations."""
        steps: list[dict] = []
        skip_dirs = {".git", "node_modules", "__pycache__", "target", "build", ".gradle"}

        # Java: scan *Steps*.java and *StepDefs*.java
        java_patterns = ["*Steps*.java", "*StepDef*.java", "*steps*.java"]
        seen_java: set[str] = set()
        for pat in java_patterns:
            for java_file in repo_path.rglob(pat):
                if any(skip in java_file.parts for skip in skip_dirs):
                    continue
                if str(java_file) in seen_java:
                    continue
                seen_java.add(str(java_file))
                try:
                    content = java_file.read_text(errors="ignore")
                    for match in re.finditer(
                        r'@(Given|When|Then|And)\s*\(\s*["\'](.+?)["\']\s*\)',
                        content,
                    ):
                        step_type = match.group(1).lower()
                        pattern_text = match.group(2)

                        # Try to extract method body after the annotation
                        impl = ""
                        after = content[match.end():]
                        method_match = re.search(
                            r'public\s+\w+\s+\w+\s*\([^)]*\)\s*\{', after[:500]
                        )
                        if method_match:
                            brace_start = after.index("{", method_match.start())
                            depth = 1
                            pos = brace_start + 1
                            while pos < len(after) and depth > 0:
                                if after[pos] == "{":
                                    depth += 1
                                elif after[pos] == "}":
                                    depth -= 1
                                pos += 1
                            if depth == 0:
                                impl = after[method_match.start():pos].strip()[:500]

                        steps.append({
                            "step_type": step_type,
                            "pattern": pattern_text,
                            "implementation": impl,
                            "language": "java",
                            "file": str(java_file.relative_to(repo_path)),
                        })
                except Exception:
                    continue

        # Python: scan *step*.py
        for py_file in repo_path.rglob("*step*.py"):
            if any(skip in py_file.parts for skip in skip_dirs):
                continue
            try:
                content = py_file.read_text(errors="ignore")
                for match in re.finditer(
                    r'@(given|when|then)\s*\(\s*["\'](.+?)["\']\s*\)',
                    content,
                ):
                    step_type = match.group(1)
                    pattern_text = match.group(2)

                    # Try to extract the function body
                    impl = ""
                    after = content[match.end():]
                    func_match = re.search(r'def\s+\w+\s*\([^)]*\)\s*:', after[:300])
                    if func_match:
                        # Grab lines until dedent
                        func_start = func_match.start()
                        lines = after[func_start:func_start + 500].split("\n")
                        impl_lines = [lines[0]]
                        for line in lines[1:]:
                            if line.strip() == "" or line[0:1] in (" ", "\t"):
                                impl_lines.append(line)
                            else:
                                break
                        impl = "\n".join(impl_lines)[:500]

                    steps.append({
                        "step_type": step_type,
                        "pattern": pattern_text,
                        "implementation": impl,
                        "language": "python",
                        "file": str(py_file.relative_to(repo_path)),
                    })
            except Exception:
                continue

        return steps

    def _scan_feature_files(self, repo_path: Path) -> list[dict]:
        """Scan for Gherkin .feature files and extract scenarios."""
        features: list[dict] = []
        skip_dirs = {".git", "node_modules", "target", "build"}

        for f in repo_path.rglob("*.feature"):
            if any(skip in f.parts for skip in skip_dirs):
                continue
            try:
                content = f.read_text(errors="ignore")
                features.append({
                    "file": str(f.relative_to(repo_path)),
                    "content": content[:4000],
                    "scenario_count": content.count("Scenario"),
                })
            except Exception:
                continue

        return features[:20]

    def _scan_maven_dependencies(self, repo_path: Path) -> list[dict]:
        """Parse pom.xml files for dependencies."""
        deps: list[dict] = []
        skip_dirs = {".git", "node_modules", "target", "build"}

        for pom in repo_path.rglob("pom.xml"):
            if any(skip in pom.parts for skip in skip_dirs):
                continue
            try:
                tree = ET.parse(str(pom))
                root = tree.getroot()
                # Handle Maven namespace
                ns_match = re.match(r'\{(.+?)\}', root.tag)
                ns = {"m": ns_match.group(1)} if ns_match else {}
                prefix = "m:" if ns else ""

                for dep in root.findall(f".//{prefix}dependency", ns):
                    group = dep.findtext(f"{prefix}groupId", "", ns)
                    artifact = dep.findtext(f"{prefix}artifactId", "", ns)
                    version = dep.findtext(f"{prefix}version", "", ns)
                    scope = dep.findtext(f"{prefix}scope", "", ns)
                    xml_str = ET.tostring(dep, encoding="unicode")
                    # Clean up namespace prefixes in output
                    xml_str = re.sub(r'\s*xmlns:\w+="[^"]*"', "", xml_str)
                    deps.append({
                        "groupId": group,
                        "artifactId": artifact,
                        "version": version,
                        "scope": scope or "compile",
                        "xml": xml_str.strip(),
                    })
            except Exception:
                continue

        return deps

    def learn_from_reference_repo(
        self,
        project_id: str,
        reference_repo_url: str,
        reference_branch: str = "main",
        maven_deps: list[str] | None = None,
    ) -> dict | None:
        """Clone a reference repo, extract BDD patterns, step defs, feature files, and Maven deps.

        Stores learned patterns as CustomStep records (source='reference') and
        in the project's config['reference_patterns'] for prompt injection.
        """
        with get_session() as db:
            project = db.get(TestProject, project_id)
            if not project:
                return None
            project_name = project.name

        # Clone reference repo into temp dir
        tmp_dir = tempfile.mkdtemp(prefix="ca-ref-")
        try:
            from src.platform.git_ops import clone_repo
            logger.info("Cloning reference repo %s (branch=%s)", reference_repo_url, reference_branch)
            clone_repo(reference_repo_url, tmp_dir, branch=reference_branch)
            ref_path = Path(tmp_dir)

            # Run scanners
            step_defs = self._discover_steps_from_path(ref_path)
            features = self._scan_feature_files(ref_path)
            maven_found = self._scan_maven_dependencies(ref_path)

            # Extract repo name for tagging
            repo_name = reference_repo_url.rstrip("/").split("/")[-1].replace(".git", "")

            # Store learned steps as CustomStep records
            with get_session() as db:
                for sd in step_defs:
                    step = CustomStep(
                        id=_uuid(),
                        project_id=project_id,
                        name=f"{sd['step_type']}: {sd['pattern'][:50]}",
                        step_type=sd["step_type"],
                        pattern=sd["pattern"],
                        implementation=sd.get("implementation", ""),
                        language=sd.get("language", "java"),
                        tags=["reference", repo_name],
                        source="reference",
                    )
                    db.add(step)

                # Store patterns in project config
                project = db.get(TestProject, project_id)
                if project:
                    config = dict(project.config or {})
                    config["reference_patterns"] = {
                        "reference_repo_url": reference_repo_url,
                        "reference_branch": reference_branch,
                        "step_definitions": [
                            {
                                "step_type": s["step_type"],
                                "pattern": s["pattern"],
                                "implementation": s.get("implementation", ""),
                            }
                            for s in step_defs
                        ],
                        "feature_summaries": features,
                        "maven_dependencies": maven_found,
                        "extra_maven_deps": maven_deps or [],
                        "learned_at": datetime.now(timezone.utc).isoformat(),
                    }
                    project.config = config

                db.flush()

            result = {
                "steps_learned": len(step_defs),
                "features_learned": len(features),
                "maven_deps_found": len(maven_found),
                "patterns": {
                    "step_definitions": [
                        {
                            "step_type": s["step_type"],
                            "pattern": s["pattern"],
                            "implementation": s.get("implementation", "")[:200],
                        }
                        for s in step_defs
                    ],
                    "feature_summaries": [
                        {
                            "file": f["file"],
                            "content": f["content"][:500],
                            "scenario_count": f["scenario_count"],
                        }
                        for f in features
                    ],
                    "maven_dependencies": maven_found,
                },
            }

            logger.info(
                "Reference repo learning complete for project %s: %d steps, %d features, %d deps",
                project_id, len(step_defs), len(features), len(maven_found),
            )
            return result

        except Exception as exc:
            logger.error("Failed to learn from reference repo %s: %s", reference_repo_url, exc, exc_info=True)
            raise
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------

    def chat(
        self, *, project_id: str, message: str
    ) -> tuple[ChatMessage, dict]:
        """Process a chat message and return an AI-generated reply."""
        context = {}

        with get_session() as db:
            # Save user message
            user_msg = ChatMessage(
                id=_uuid(),
                project_id=project_id,
                role="user",
                content=message,
            )
            db.add(user_msg)

            # Get project context
            project = db.get(TestProject, project_id)
            if project:
                context["project_name"] = project.name
                context["language"] = project.language
                context["framework"] = project.framework
                context["status"] = project.status
                context["discovery"] = project.discovery_result or {}

            # Get recent chat history for context
            history = (
                db.query(ChatMessage)
                .filter(ChatMessage.project_id == project_id)
                .order_by(ChatMessage.created_at.desc())
                .limit(10)
                .all()
            )
            context["history_count"] = len(history)

            # Generate response based on the message intent
            reply_content = self._generate_chat_reply(message, project, history)

            reply = ChatMessage(
                id=_uuid(),
                project_id=project_id,
                role="assistant",
                content=reply_content,
                extra_data={"intent": self._classify_intent(message)},
            )
            db.add(reply)
            db.flush()

            db.expunge(user_msg)
            db.expunge(reply)

        return reply, context

    def _classify_intent(self, message: str) -> str:
        """Classify the user's message intent."""
        import re
        msg = message.lower()
        words = set(re.findall(r'\b\w+\b', msg))

        if any(w in words for w in ("discover", "scan", "endpoint", "endpoints")):
            return "discovery"
        if any(w in words for w in ("coverage", "uncovered", "gap")):
            return "coverage"
        if any(w in words for w in ("data", "inject", "synthetic", "factory")):
            return "data_injection"
        if any(w in words for w in ("security", "penetration", "vulnerability", "owasp", "injection")):
            return "security"
        if any(w in words for w in ("step", "custom", "reusable")):
            return "custom_steps"
        if any(w in words for w in ("run", "execute", "start", "test")):
            return "test_execution"
        if any(w in words for w in ("status", "progress", "report")):
            return "status"
        return "general"

    def _generate_chat_reply(
        self, message: str, project, history: list
    ) -> str:
        """Generate a contextual reply for the chat message.

        In production, this would call the LLM. For now, returns a structured
        response based on intent classification and project state.
        """
        intent = self._classify_intent(message)
        project_name = project.name if project else "Unknown"

        if intent == "coverage":
            return (
                f"I can analyze the test coverage for **{project_name}**. "
                "Use the 'Analyze Coverage' button on the Coverage page, or I can "
                "identify uncovered endpoints and suggest tests to fill the gaps. "
                "Would you like me to run a coverage analysis now?"
            )
        elif intent == "test_execution":
            return (
                f"I can start a test run for **{project_name}**. Available strategies:\n"
                "- **Functional**: Generate and run functional tests\n"
                "- **Security**: Run security/penetration tests\n"
                "- **Regression**: Run regression test suite\n"
                "- **BDD**: Generate Cucumber/BDD scenarios\n\n"
                "Which type of tests would you like to run?"
            )
        elif intent == "data_injection":
            return (
                "I can help set up data injection for your tests. Available strategies:\n"
                "- **Synthetic**: Generate realistic test data from schema definitions\n"
                "- **Factory**: Create data factory patterns for reusable test data\n"
                "- **Pool**: Manage a pool of pre-generated test records\n"
                "- **Masked**: Use production-like data with PII masking\n\n"
                "Go to the Data Injection page to configure, or tell me about the "
                "entities you need test data for."
            )
        elif intent == "discovery":
            discovery = project.discovery_result if project else {}
            endpoints = discovery.get("endpoints", []) if discovery else []
            services = discovery.get("services", []) if discovery else []
            return (
                f"Discovery results for **{project_name}**:\n"
                f"- **{len(endpoints)}** endpoints found\n"
                f"- **{len(services)}** services found\n"
                f"- Frameworks: {', '.join(discovery.get('frameworks_detected', ['none']))}\n\n"
                "Would you like me to re-run discovery or generate tests for the discovered endpoints?"
            )
        elif intent == "security":
            return (
                f"I can run security testing on **{project_name}**. Available checks:\n"
                "- **SQL Injection**: Test input fields for SQL injection vulnerabilities\n"
                "- **XSS**: Cross-site scripting detection\n"
                "- **Auth Bypass**: Test authentication and authorization flows\n"
                "- **API Security**: Validate API key handling, rate limiting, CORS\n"
                "- **OWASP Top 10**: Comprehensive OWASP vulnerability scan\n\n"
                "Would you like to start a security scan?"
            )
        elif intent == "status":
            return (
                f"Current status for **{project_name}**: {project.status if project else 'unknown'}\n\n"
                "Check the Agents page for detailed run status and progress."
            )
        else:
            return (
                f"I'm your testing assistant for **{project_name}**. I can help with:\n"
                "- Running and monitoring tests\n"
                "- Analyzing test coverage and suggesting improvements\n"
                "- Setting up data injection strategies\n"
                "- Discovering endpoints and services\n"
                "- Running security/penetration tests\n"
                "- Managing custom step definitions\n\n"
                "What would you like to do?"
            )

    def get_chat_history(
        self, project_id: str, *, limit: int = 50
    ) -> list[ChatMessage]:
        with get_session() as db:
            return (
                db.query(ChatMessage)
                .filter(ChatMessage.project_id == project_id)
                .order_by(ChatMessage.created_at.asc())
                .limit(limit)
                .all()
            )

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_stats(self) -> dict:
        """Get aggregate testing statistics."""
        with get_session() as db:
            total_projects = db.query(TestProject).count()
            total_runs = db.query(TestRun).count()
            passed_runs = db.query(TestRun).filter(TestRun.status == "passed").count()
            failed_runs = db.query(TestRun).filter(TestRun.status == "failed").count()
            running_runs = db.query(TestRun).filter(TestRun.status == "running").count()

            # Get latest coverage
            latest_coverage = (
                db.query(CoverageReport)
                .order_by(CoverageReport.created_at.desc())
                .first()
            )

            return {
                "total_projects": total_projects,
                "total_runs": total_runs,
                "passed_runs": passed_runs,
                "failed_runs": failed_runs,
                "running_runs": running_runs,
                "success_rate": round(passed_runs / max(total_runs, 1) * 100, 1),
                "avg_coverage": latest_coverage.overall_pct if latest_coverage else 0.0,
            }
