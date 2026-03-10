"""
Migration Service — orchestrates repository migration from legacy to golden template.

Handles project CRUD, stack analysis, gap computation, capacity modeling,
recipe selection, roadmap generation, and migration execution.
"""

import logging
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from src.data.database import get_session
from src.data.models import MigrationProject, MigrationRun, Repo

logger = logging.getLogger(__name__)


def _uuid() -> str:
    return uuid.uuid4().hex[:16]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MigrationService:
    """High-level service for the migration platform."""

    # ------------------------------------------------------------------
    # CRUD — Projects
    # ------------------------------------------------------------------

    def list_projects(
        self,
        *,
        status: Optional[str] = None,
        repo_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[MigrationProject]:
        with get_session() as db:
            q = db.query(MigrationProject)
            if status:
                q = q.filter(MigrationProject.status == status)
            if repo_id:
                q = q.filter(MigrationProject.repo_id == repo_id)
            return q.order_by(MigrationProject.created_at.desc()).limit(limit).all()

    def get_project(self, project_id: str) -> Optional[MigrationProject]:
        with get_session() as db:
            return db.get(MigrationProject, project_id)

    def create_project(
        self,
        *,
        name: str,
        migration_mode: str = "migration",
        source_repo_url: str = "",
        source_local_path: str = "",
        source_branch: str = "main",
        reference_repo_url: str = "",
        reference_local_path: str = "",
        reference_branch: str = "main",
        reference_folders: list[str] | None = None,
        config: dict | None = None,
    ) -> MigrationProject:
        """Create a new migration project, registering the source repo.

        migration_mode:
            "migration"   — source repo migrated toward a reference golden template
            "improvement" — existing dest repo assessed for quality, completeness,
                            testing gaps, performance, structure, etc.
        """
        from src.agent.knowledge import compute_repo_id

        repo_id = compute_repo_id(source_local_path, source_repo_url)

        with get_session() as db:
            # Ensure source repo is registered
            repo = db.get(Repo, repo_id)
            if repo is None:
                repo = Repo(
                    id=repo_id,
                    url=source_repo_url,
                    local_path=source_local_path,
                    platform=self._detect_platform(source_repo_url),
                )
                db.add(repo)
                db.flush()

            project = MigrationProject(
                id=_uuid(),
                repo_id=repo.id,
                name=name,
                migration_mode=migration_mode,
                source_repo_url=source_repo_url,
                source_local_path=source_local_path,
                source_branch=source_branch,
                reference_repo_url=reference_repo_url,
                reference_local_path=reference_local_path,
                reference_branch=reference_branch,
                reference_folders=reference_folders or [],
                status="pending",
                config=config or {},
            )
            db.add(project)
            db.flush()
            db.expunge(project)
        return project

    def delete_project(self, project_id: str) -> bool:
        with get_session() as db:
            project = db.get(MigrationProject, project_id)
            if not project:
                return False
            db.delete(project)
            return True

    @staticmethod
    def _detect_platform(repo_url: str) -> str:
        if not repo_url:
            return "local"
        if "github.com" in repo_url:
            return "github"
        if "bitbucket" in repo_url:
            return "bitbucket"
        return "local"

    # ------------------------------------------------------------------
    # Analysis — Stack profiling + Gap computation
    # ------------------------------------------------------------------

    def analyze_project(
        self,
        project_id: str,
        config: dict | None = None,
        progress_callback: Optional[Callable] = None,
    ) -> Optional[MigrationProject]:
        """Run stack analysis on source (and optionally reference) repo, compute gaps.

        For migration mode:
            1. Analyze both source and reference repos
            2. Compute gap analysis between them
            3. Run improvement analysis on source

        For improvement mode:
            1. Analyze source repo only
            2. Run deep improvement analysis (tests, quality, performance, structure)
            3. Optionally compare with reference if provided
        """
        from src.consciousness.stack_analyzer import analyze_stack

        def _log(stage: str, detail: str):
            if progress_callback:
                progress_callback({"type": "progress", "data": {"stage": stage, "detail": detail}})
            logger.info("[migration:%s] %s: %s", project_id, stage, detail)

        with get_session() as db:
            project = db.get(MigrationProject, project_id)
            if not project:
                return None

            project.status = "analyzing"
            migration_mode = project.migration_mode or "migration"
            db.flush()

        try:
            _log("analyze", f"Starting analysis (mode: {migration_mode})")

            # 1. Resolve source path
            source_path = self._resolve_repo_path(
                project.source_local_path,
                project.source_repo_url,
                project.source_branch,
                project.repo_id,
                config,
            )
            _log("analyze", f"Source path: {source_path}")

            # 2. Run stack analysis on source
            _log("analyze", "Analyzing source stack...")
            source_profile = analyze_stack(source_path)
            source_dict = asdict(source_profile)

            # 3. Reference analysis (optional in improvement mode)
            reference_dict: dict = {}
            gap: dict = {}
            has_reference = bool(project.reference_repo_url or project.reference_local_path)

            if has_reference:
                reference_path = self._clone_reference_repo(
                    project.reference_repo_url,
                    project.reference_local_path,
                    project.reference_branch,
                )
                _log("analyze", f"Reference path: {reference_path}")
                _log("analyze", "Analyzing reference stack...")
                reference_profile = analyze_stack(reference_path)
                reference_dict = asdict(reference_profile)

                _log("analyze", "Computing gap analysis...")
                gap = self._compute_gap_analysis(source_dict, reference_dict)

            # 4. Run improvement analysis on source repo
            _log("analyze", "Running improvement analysis...")
            improvement = self._compute_improvement_analysis(source_path, source_dict)

            # Merge improvement findings into gap categories for unified recipe recommendations
            if improvement.get("areas_needing_improvement"):
                gap.setdefault("categories_with_gaps", [])
                for area in improvement["areas_needing_improvement"]:
                    if area not in gap["categories_with_gaps"]:
                        gap["categories_with_gaps"].append(area)

            # 5. Auto-detect capacity
            _log("analyze", "Detecting capacity...")
            capacity = self._detect_capacity(source_dict)

            # 6. Persist
            with get_session() as db:
                project = db.get(MigrationProject, project_id)
                if project:
                    project.source_profile = source_dict
                    project.reference_profile = reference_dict
                    project.gap_analysis = gap
                    project.improvement_analysis = improvement
                    project.capacity_current = capacity
                    project.status = "analyzed"
                    db.flush()
                    db.expunge(project)

            _log("complete", "Analysis complete")
            return project

        except Exception as exc:
            logger.error("Migration analysis failed for %s: %s", project_id, exc)
            with get_session() as db:
                project = db.get(MigrationProject, project_id)
                if project:
                    project.status = "failed"
                    db.flush()
            if progress_callback:
                progress_callback({"type": "error", "data": {"message": str(exc)}})
            raise

    def _resolve_repo_path(
        self,
        local_path: str,
        repo_url: str,
        branch: str,
        repo_id: str,
        config: dict | None,
    ) -> str:
        """Resolve local path for a repo — use existing path or clone."""
        if local_path and Path(local_path).is_dir():
            return local_path

        if repo_url:
            from src.services.repo_service import RepoService
            return RepoService().ensure_local_clone(repo_id, branch=branch, config=config or {})

        raise ValueError("No local path or URL provided for repository")

    def _clone_reference_repo(
        self,
        repo_url: str,
        local_path: str,
        branch: str,
    ) -> str:
        """Clone the reference repo to a temp directory or use existing path."""
        if local_path and Path(local_path).is_dir():
            return local_path

        if not repo_url:
            raise ValueError("Reference repo has no URL or local path")

        # Clone to temp directory
        tmp_dir = tempfile.mkdtemp(prefix="migration_ref_")
        try:
            cmd = ["git", "clone", "--depth", "1", "--branch", branch, repo_url, tmp_dir]
            subprocess.run(cmd, check=True, capture_output=True, timeout=120)
        except subprocess.CalledProcessError:
            # Try without --branch (branch might not exist)
            shutil.rmtree(tmp_dir, ignore_errors=True)
            tmp_dir = tempfile.mkdtemp(prefix="migration_ref_")
            cmd = ["git", "clone", "--depth", "1", repo_url, tmp_dir]
            subprocess.run(cmd, check=True, capture_output=True, timeout=120)

        return tmp_dir

    def _compute_gap_analysis(self, source: dict, reference: dict) -> dict:
        """Compare two StackProfile dicts and produce a structured gap analysis."""
        gaps: dict = {
            "categories_with_gaps": [],
            "technology_gaps": [],
            "dependency_gaps": [],
            "k8s_gaps": [],
            "docker_gaps": [],
            "config_gaps": [],
            "summary": {},
        }

        # Technology gaps: techs in reference not in source
        src_techs = set()
        for cat_techs in (source.get("technologies") or {}).values():
            if isinstance(cat_techs, list):
                src_techs.update(cat_techs)

        ref_techs = set()
        for cat_techs in (reference.get("technologies") or {}).values():
            if isinstance(cat_techs, list):
                ref_techs.update(cat_techs)

        missing_techs = ref_techs - src_techs
        if missing_techs:
            gaps["categories_with_gaps"].append("technology")
            gaps["technology_gaps"] = [
                {"tech": t, "status": "missing", "source": "reference"}
                for t in sorted(missing_techs)
            ]

        # Dependency gaps
        src_deps = {
            f"{d.get('group', '')}:{d.get('artifact', '')}": d
            for d in (source.get("dependencies") or [])
        }
        ref_deps = {
            f"{d.get('group', '')}:{d.get('artifact', '')}": d
            for d in (reference.get("dependencies") or [])
        }

        dep_gaps = []
        for key, ref_dep in ref_deps.items():
            if key not in src_deps:
                dep_gaps.append({
                    "artifact": key,
                    "status": "missing",
                    "reference_version": ref_dep.get("version", ""),
                })
            elif src_deps[key].get("version") != ref_dep.get("version"):
                dep_gaps.append({
                    "artifact": key,
                    "status": "version_mismatch",
                    "source_version": src_deps[key].get("version", ""),
                    "reference_version": ref_dep.get("version", ""),
                })
        if dep_gaps:
            gaps["categories_with_gaps"].append("dependencies")
            gaps["dependency_gaps"] = dep_gaps

        # K8s gaps
        src_k8s = {r.get("kind", ""): r for r in (source.get("k8s_resources") or [])}
        ref_k8s = {r.get("kind", ""): r for r in (reference.get("k8s_resources") or [])}

        k8s_gaps = []
        for kind, ref_res in ref_k8s.items():
            if kind not in src_k8s:
                k8s_gaps.append({"kind": kind, "status": "missing", "reference": ref_res})
            else:
                src_res = src_k8s[kind]
                diffs = {}
                if ref_res.get("image") and src_res.get("image") != ref_res.get("image"):
                    diffs["image"] = {"source": src_res.get("image"), "reference": ref_res.get("image")}
                if ref_res.get("replicas") and src_res.get("replicas") != ref_res.get("replicas"):
                    diffs["replicas"] = {"source": src_res.get("replicas"), "reference": ref_res.get("replicas")}
                if diffs:
                    k8s_gaps.append({"kind": kind, "status": "differs", "diffs": diffs})

        if k8s_gaps:
            gaps["categories_with_gaps"].append("k8s")
            gaps["k8s_gaps"] = k8s_gaps

        # Config property gaps
        src_props = source.get("config_properties") or {}
        ref_props = reference.get("config_properties") or {}
        config_gaps = []
        for key, val in ref_props.items():
            if key not in src_props:
                config_gaps.append({"key": key, "status": "missing", "reference_value": val})
            elif src_props[key] != val:
                config_gaps.append({
                    "key": key,
                    "status": "differs",
                    "source_value": src_props[key],
                    "reference_value": val,
                })
        if config_gaps:
            gaps["categories_with_gaps"].append("config")
            gaps["config_gaps"] = config_gaps

        # Summary
        gaps["summary"] = {
            "total_gaps": (
                len(gaps["technology_gaps"])
                + len(gaps["dependency_gaps"])
                + len(gaps["k8s_gaps"])
                + len(gaps["config_gaps"])
            ),
            "technology_gap_count": len(gaps["technology_gaps"]),
            "dependency_gap_count": len(gaps["dependency_gaps"]),
            "k8s_gap_count": len(gaps["k8s_gaps"]),
            "config_gap_count": len(gaps["config_gaps"]),
            "categories_affected": len(gaps["categories_with_gaps"]),
        }

        return gaps

    # ------------------------------------------------------------------
    # Improvement Analysis
    # ------------------------------------------------------------------

    def _compute_improvement_analysis(self, repo_path: str, source_profile: dict) -> dict:
        """Scan a repository for quality, testing, performance, and structural improvements.

        Returns a structured dict with findings per area and an overall
        ``areas_needing_improvement`` list for recipe recommendation.
        """
        findings: dict = {
            "areas_needing_improvement": [],
            "test_coverage": {},
            "code_quality": {},
            "performance": {},
            "structure": {},
            "error_handling": {},
            "api_documentation": {},
            "summary": {},
        }

        root = Path(repo_path)

        # --- Test Coverage ---------------------------------------------------
        findings["test_coverage"] = self._analyze_test_coverage(root, source_profile)
        if findings["test_coverage"].get("needs_improvement"):
            findings["areas_needing_improvement"].append("test_coverage")

        # --- Code Quality ----------------------------------------------------
        findings["code_quality"] = self._analyze_code_quality(root, source_profile)
        if findings["code_quality"].get("needs_improvement"):
            findings["areas_needing_improvement"].append("code_quality")

        # --- Performance -----------------------------------------------------
        findings["performance"] = self._analyze_performance(root, source_profile)
        if findings["performance"].get("needs_improvement"):
            findings["areas_needing_improvement"].append("performance")

        # --- Project Structure -----------------------------------------------
        findings["structure"] = self._analyze_structure(root, source_profile)
        if findings["structure"].get("needs_improvement"):
            findings["areas_needing_improvement"].append("structure")

        # --- Error Handling --------------------------------------------------
        findings["error_handling"] = self._analyze_error_handling(root, source_profile)
        if findings["error_handling"].get("needs_improvement"):
            findings["areas_needing_improvement"].append("error_handling")

        # --- API Documentation -----------------------------------------------
        findings["api_documentation"] = self._analyze_api_documentation(root, source_profile)
        if findings["api_documentation"].get("needs_improvement"):
            findings["areas_needing_improvement"].append("api_documentation")

        # Summary
        findings["summary"] = {
            "total_areas_scanned": 6,
            "areas_needing_improvement": len(findings["areas_needing_improvement"]),
            "improvement_areas": findings["areas_needing_improvement"],
        }
        return findings

    # --- Sub-analyses -------------------------------------------------------

    def _analyze_test_coverage(self, root: Path, profile: dict) -> dict:
        """Detect test coverage gaps by comparing source files to test files."""
        result: dict = {
            "needs_improvement": False,
            "issues": [],
            "source_file_count": 0,
            "test_file_count": 0,
            "test_ratio": 0.0,
            "has_test_directory": False,
            "has_test_config": False,
            "missing_test_types": [],
        }

        # Collect source and test files
        src_files: list[str] = []
        test_files: list[str] = []
        test_dirs_found: set[str] = set()

        test_dir_names = {"test", "tests", "__tests__", "spec", "specs"}
        test_file_patterns = re.compile(
            r"(test_|_test\.|\.test\.|\.spec\.|Test\.|Tests\.|IT\.)", re.IGNORECASE
        )
        source_exts = {".java", ".py", ".ts", ".js", ".kt", ".go", ".cs", ".rb", ".scala"}

        for f in root.rglob("*"):
            if not f.is_file():
                continue
            if f.suffix not in source_exts:
                continue
            rel = str(f.relative_to(root))
            # Skip vendor / node_modules / build dirs
            if any(p in rel for p in ("node_modules/", "vendor/", "build/", "target/", ".gradle/", "dist/")):
                continue

            parts_lower = {p.lower() for p in f.parts}
            is_test_dir = bool(parts_lower & test_dir_names)
            is_test_file = bool(test_file_patterns.search(f.name))

            if is_test_dir or is_test_file:
                test_files.append(rel)
                for p in f.parts:
                    if p.lower() in test_dir_names:
                        test_dirs_found.add(p)
            else:
                src_files.append(rel)

        result["source_file_count"] = len(src_files)
        result["test_file_count"] = len(test_files)
        result["has_test_directory"] = len(test_dirs_found) > 0
        result["test_ratio"] = (
            round(len(test_files) / len(src_files), 2) if src_files else 0.0
        )

        # Check for test configuration files
        test_config_patterns = [
            "pytest.ini", "setup.cfg", "tox.ini", "jest.config.*",
            "vitest.config.*", "karma.conf.*", "phpunit.xml",
            "**/application-test.yml", "**/application-test.properties",
        ]
        has_test_config = any(
            list(root.glob(pat)) for pat in test_config_patterns
        )
        result["has_test_config"] = has_test_config

        # Determine missing test types
        deps = {
            f"{d.get('group', '')}:{d.get('artifact', '')}".lower()
            for d in (profile.get("dependencies") or [])
        }
        dep_str = " ".join(deps)

        test_type_markers = {
            "integration": ["testcontainers", "spring-boot-test", "@springboottest", "wiremock"],
            "performance": ["jmeter", "gatling", "k6", "jmh", "benchmark"],
            "security": ["owasp", "spotbugs", "findsecbugs", "dependency-check", "snyk"],
            "contract": ["pact", "spring-cloud-contract"],
        }
        for ttype, markers in test_type_markers.items():
            if not any(m in dep_str for m in markers):
                # Also scan file names for test type indicators
                type_files = [
                    t for t in test_files
                    if ttype in t.lower() or (ttype == "security" and "security" in t.lower())
                ]
                if not type_files:
                    result["missing_test_types"].append(ttype)

        # Issues
        if not result["has_test_directory"]:
            result["issues"].append("No dedicated test directory found")
        if result["test_ratio"] < 0.5 and len(src_files) > 3:
            result["issues"].append(
                f"Low test-to-source ratio: {result['test_ratio']} (recommend >= 0.5)"
            )
        if not has_test_config:
            result["issues"].append("No test configuration file found")
        if result["missing_test_types"]:
            result["issues"].append(
                f"Missing test types: {', '.join(result['missing_test_types'])}"
            )

        result["needs_improvement"] = len(result["issues"]) >= 2 or result["test_ratio"] < 0.3
        return result

    def _analyze_code_quality(self, root: Path, profile: dict) -> dict:
        """Heuristic code quality analysis: complexity, large files, dead code indicators."""
        result: dict = {
            "needs_improvement": False,
            "issues": [],
            "large_files": [],
            "high_complexity_files": [],
            "has_linter_config": False,
            "has_formatter_config": False,
        }

        source_exts = {".java", ".py", ".ts", ".js", ".kt", ".go", ".cs"}
        skip_dirs = {"node_modules", "vendor", "build", "target", ".gradle", "dist", "__pycache__"}

        large_threshold = 500  # lines
        complexity_threshold = 15  # deep nesting heuristic

        for f in root.rglob("*"):
            if not f.is_file() or f.suffix not in source_exts:
                continue
            if any(p in skip_dirs for p in f.parts):
                continue

            try:
                content = f.read_text(errors="ignore")
            except Exception:
                continue

            lines = content.splitlines()
            line_count = len(lines)
            rel = str(f.relative_to(root))

            if line_count > large_threshold:
                result["large_files"].append({"file": rel, "lines": line_count})

            # Rough complexity: count max nesting depth via indentation
            max_depth = 0
            for line in lines:
                stripped = line.lstrip()
                if not stripped:
                    continue
                indent = len(line) - len(stripped)
                # Normalize to tab-stops (4 spaces or 1 tab)
                depth = indent // 4 if "    " in line[:indent] else indent
                if depth > max_depth:
                    max_depth = depth

            if max_depth >= complexity_threshold:
                result["high_complexity_files"].append({"file": rel, "max_depth": max_depth})

        # Check for linter / formatter configs
        linter_globs = [
            ".eslintrc*", ".pylintrc", "pyproject.toml", "checkstyle*.xml",
            ".flake8", "tslint.json", "biome.json", ".golangci.yml",
            "pmd*.xml", "spotbugs*.xml",
        ]
        formatter_globs = [
            ".prettierrc*", ".editorconfig", "spotless*", "google-java-format*",
            "black.toml", "rustfmt.toml", ".clang-format",
        ]
        result["has_linter_config"] = any(list(root.glob(p)) for p in linter_globs)
        result["has_formatter_config"] = any(list(root.glob(p)) for p in formatter_globs)

        if result["large_files"]:
            result["issues"].append(
                f"{len(result['large_files'])} file(s) exceed {large_threshold} lines"
            )
        if result["high_complexity_files"]:
            result["issues"].append(
                f"{len(result['high_complexity_files'])} file(s) have high nesting depth (>={complexity_threshold})"
            )
        if not result["has_linter_config"]:
            result["issues"].append("No linter configuration found")
        if not result["has_formatter_config"]:
            result["issues"].append("No code formatter configuration found")

        result["needs_improvement"] = len(result["issues"]) >= 2
        return result

    def _analyze_performance(self, root: Path, profile: dict) -> dict:
        """Detect performance anti-patterns from dependencies and source code."""
        result: dict = {
            "needs_improvement": False,
            "issues": [],
            "missing_patterns": [],
        }

        deps = {
            f"{d.get('group', '')}:{d.get('artifact', '')}".lower()
            for d in (profile.get("dependencies") or [])
        }
        dep_str = " ".join(deps)
        techs = set()
        for cat_techs in (profile.get("technologies") or {}).values():
            if isinstance(cat_techs, list):
                techs.update(t.lower() for t in cat_techs)

        # Check for caching
        has_caching = any(
            k in dep_str for k in ["caffeine", "ehcache", "redis", "cache-api", "spring-cache"]
        ) or any("cache" in t for t in techs)

        if not has_caching:
            result["missing_patterns"].append("caching")
            result["issues"].append("No caching library detected (Caffeine, Ehcache, Redis)")

        # Check for connection pooling (Java)
        has_pool = any(
            k in dep_str for k in ["hikari", "c3p0", "dbcp", "tomcat-jdbc"]
        )
        is_java = any(e in dep_str for e in ["spring", "javax", "jakarta", "maven", "gradle"])
        if is_java and not has_pool:
            result["missing_patterns"].append("connection_pooling")
            result["issues"].append("No explicit connection pool configuration detected")

        # Check for async / reactive patterns
        has_async = any(
            k in dep_str for k in ["webflux", "reactor", "rxjava", "completable", "coroutines"]
        )
        if is_java and not has_async:
            result["missing_patterns"].append("async_patterns")

        # Check for monitoring / profiling deps
        has_profiling = any(
            k in dep_str for k in ["micrometer", "prometheus", "actuator", "metrics"]
        )
        if not has_profiling:
            result["missing_patterns"].append("metrics")
            result["issues"].append("No metrics/profiling library detected (Micrometer, Prometheus)")

        result["needs_improvement"] = len(result["issues"]) >= 2
        return result

    def _analyze_structure(self, root: Path, profile: dict) -> dict:
        """Analyze project structure for standard directory conventions."""
        result: dict = {
            "needs_improvement": False,
            "issues": [],
            "detected_layout": "unknown",
            "missing_directories": [],
        }

        # Detect project type
        is_maven = (root / "pom.xml").exists()
        is_gradle = (root / "build.gradle").exists() or (root / "build.gradle.kts").exists()
        is_python = (root / "setup.py").exists() or (root / "pyproject.toml").exists()
        is_node = (root / "package.json").exists()

        if is_maven or is_gradle:
            result["detected_layout"] = "java_maven" if is_maven else "java_gradle"
            expected = [
                "src/main/java",
                "src/main/resources",
                "src/test/java",
                "src/test/resources",
            ]
            for d in expected:
                if not (root / d).is_dir():
                    result["missing_directories"].append(d)

            # Check for clean architecture indicators
            java_root = root / "src" / "main" / "java"
            if java_root.is_dir():
                packages = {p.name for p in java_root.rglob("*") if p.is_dir()}
                arch_dirs = {"controller", "service", "repository", "model",
                             "dto", "config", "exception", "util"}
                found = packages & arch_dirs
                if len(found) < 3 and len(list(java_root.rglob("*.java"))) > 10:
                    result["issues"].append(
                        "Project has >10 Java files but lacks standard package layering "
                        "(controller, service, repository, model)"
                    )

        elif is_python:
            result["detected_layout"] = "python"
            expected = ["tests"]
            for d in expected:
                if not (root / d).is_dir():
                    result["missing_directories"].append(d)

        elif is_node:
            result["detected_layout"] = "node"
            expected = ["src"]
            for d in expected:
                if not (root / d).is_dir():
                    result["missing_directories"].append(d)

        if result["missing_directories"]:
            result["issues"].append(
                f"Missing standard directories: {', '.join(result['missing_directories'])}"
            )

        # Check for README
        has_readme = any(
            (root / name).exists() for name in ["README.md", "README.rst", "README.txt", "README"]
        )
        if not has_readme:
            result["issues"].append("No README file found")

        # Check for .gitignore
        if not (root / ".gitignore").exists():
            result["issues"].append("No .gitignore file found")

        result["needs_improvement"] = len(result["issues"]) >= 2
        return result

    def _analyze_error_handling(self, root: Path, profile: dict) -> dict:
        """Check for error handling patterns (global handlers, structured responses)."""
        result: dict = {
            "needs_improvement": False,
            "issues": [],
            "has_global_handler": False,
            "has_error_dto": False,
            "has_resilience": False,
        }

        deps = {
            f"{d.get('group', '')}:{d.get('artifact', '')}".lower()
            for d in (profile.get("dependencies") or [])
        }
        dep_str = " ".join(deps)

        # Scan for global exception handler patterns
        handler_patterns = re.compile(
            r"(@ControllerAdvice|@RestControllerAdvice|app\.exception_handler|"
            r"@ExceptionHandler|error_handler|GlobalExceptionHandler)",
            re.IGNORECASE,
        )
        error_dto_patterns = re.compile(
            r"(ErrorResponse|ErrorDto|ApiError|ProblemDetail|error_response)",
            re.IGNORECASE,
        )

        source_exts = {".java", ".py", ".ts", ".js", ".kt", ".go"}
        skip_dirs = {"node_modules", "vendor", "build", "target", "dist", "__pycache__"}

        for f in root.rglob("*"):
            if not f.is_file() or f.suffix not in source_exts:
                continue
            if any(p in skip_dirs for p in f.parts):
                continue
            try:
                content = f.read_text(errors="ignore")
            except Exception:
                continue

            if handler_patterns.search(content):
                result["has_global_handler"] = True
            if error_dto_patterns.search(content):
                result["has_error_dto"] = True

            if result["has_global_handler"] and result["has_error_dto"]:
                break

        # Check for resilience patterns
        result["has_resilience"] = any(
            k in dep_str for k in ["resilience4j", "hystrix", "sentinel", "retry", "circuit"]
        )

        if not result["has_global_handler"]:
            result["issues"].append("No global exception handler found (@ControllerAdvice or equivalent)")
        if not result["has_error_dto"]:
            result["issues"].append("No structured error response DTO found")
        if not result["has_resilience"]:
            result["issues"].append("No resilience library detected (Resilience4j, Hystrix)")

        result["needs_improvement"] = len(result["issues"]) >= 2
        return result

    def _analyze_api_documentation(self, root: Path, profile: dict) -> dict:
        """Check for API documentation setup (OpenAPI, Swagger, etc.)."""
        result: dict = {
            "needs_improvement": False,
            "issues": [],
            "has_openapi": False,
            "has_swagger_annotations": False,
            "has_api_docs_config": False,
        }

        deps = {
            f"{d.get('group', '')}:{d.get('artifact', '')}".lower()
            for d in (profile.get("dependencies") or [])
        }
        dep_str = " ".join(deps)

        # Check for OpenAPI / Swagger dependencies
        result["has_openapi"] = any(
            k in dep_str for k in ["springdoc", "swagger", "openapi", "springfox"]
        )

        # Check for OpenAPI spec files
        spec_patterns = ["openapi.yml", "openapi.yaml", "openapi.json", "swagger.yml", "swagger.yaml", "swagger.json"]
        has_spec_file = any((root / s).exists() for s in spec_patterns) or any(
            list(root.rglob(p)) for p in spec_patterns
        )

        # Scan for annotation usage
        api_annotation_pattern = re.compile(
            r"(@Operation|@ApiResponse|@Schema|@Api\b|@SwaggerDefinition|@OpenAPIDefinition)",
            re.IGNORECASE,
        )
        source_exts = {".java", ".kt", ".py", ".ts", ".js"}
        skip_dirs = {"node_modules", "vendor", "build", "target", "dist"}

        annotation_count = 0
        controller_count = 0
        controller_pattern = re.compile(r"(@RestController|@Controller|@app\.route|@router\.|@api_view)", re.IGNORECASE)

        for f in root.rglob("*"):
            if not f.is_file() or f.suffix not in source_exts:
                continue
            if any(p in skip_dirs for p in f.parts):
                continue
            try:
                content = f.read_text(errors="ignore")
            except Exception:
                continue

            if controller_pattern.search(content):
                controller_count += 1
            if api_annotation_pattern.search(content):
                annotation_count += 1

        result["has_swagger_annotations"] = annotation_count > 0
        result["has_api_docs_config"] = has_spec_file or result["has_openapi"]

        if not result["has_openapi"] and not has_spec_file:
            result["issues"].append("No OpenAPI/Swagger dependency or spec file found")
        if controller_count > 0 and annotation_count == 0:
            result["issues"].append(
                f"Found {controller_count} controller(s) but no API documentation annotations"
            )
        if controller_count > 0 and not has_spec_file and not result["has_openapi"]:
            result["issues"].append("API endpoints exist but no documentation infrastructure is configured")

        result["needs_improvement"] = len(result["issues"]) >= 2
        return result

    def _detect_capacity(self, source_profile: dict) -> dict:
        """Auto-detect current capacity from K8s/Docker configs."""
        capacity: dict = {
            "services": [],
            "total_replicas": 0,
            "ports": [],
        }

        for res in (source_profile.get("k8s_resources") or []):
            svc: dict = {
                "kind": res.get("kind", ""),
                "name": res.get("name", ""),
                "replicas": res.get("replicas", 1),
                "image": res.get("image", ""),
            }
            capacity["services"].append(svc)
            capacity["total_replicas"] += svc["replicas"] if isinstance(svc["replicas"], int) else 0

        return capacity

    # ------------------------------------------------------------------
    # Capacity — target modeling
    # ------------------------------------------------------------------

    def update_capacity_target(
        self, project_id: str, capacity_target: dict
    ) -> Optional[MigrationProject]:
        """Save user-defined target capacity model."""
        with get_session() as db:
            project = db.get(MigrationProject, project_id)
            if not project:
                return None
            project.capacity_target = capacity_target
            db.flush()
            db.expunge(project)
        return project

    # ------------------------------------------------------------------
    # Recipes
    # ------------------------------------------------------------------

    def select_recipes(
        self, project_id: str, recipe_ids: list[str]
    ) -> Optional[MigrationProject]:
        """Save selected recipe IDs for a project."""
        with get_session() as db:
            project = db.get(MigrationProject, project_id)
            if not project:
                return None
            project.selected_recipes = recipe_ids
            db.flush()
            db.expunge(project)
        return project

    def get_recommended_recipes(self, project_id: str) -> list[dict]:
        """Return applicable recipes based on the project's gap analysis."""
        from src.services.migration_recipes import get_applicable_recipes

        with get_session() as db:
            project = db.get(MigrationProject, project_id)
            if not project:
                return []

        applicable = get_applicable_recipes(
            project.source_profile or {},
            project.reference_profile or {},
            project.gap_analysis or {},
            improvement_analysis=project.improvement_analysis or {},
        )
        return [r.to_dict() for r in applicable]

    # ------------------------------------------------------------------
    # Roadmap
    # ------------------------------------------------------------------

    def generate_roadmap(self, project_id: str) -> Optional[MigrationRun]:
        """Build ordered migration steps from selected recipes + gaps, create a MigrationRun."""
        with get_session() as db:
            project = db.get(MigrationProject, project_id)
            if not project:
                return None

            steps = self._build_roadmap_steps(
                project.selected_recipes or [],
                project.gap_analysis or {},
            )

            run = MigrationRun(
                id=_uuid(),
                project_id=project.id,
                status="queued",
                roadmap_steps=steps,
                current_step=0,
                progress_pct=0.0,
            )
            db.add(run)
            db.flush()
            db.expunge(run)
        return run

    def _build_roadmap_steps(self, recipe_ids: list[str], gap_analysis: dict) -> list[dict]:
        """Convert selected recipes into ordered roadmap steps, respecting prerequisites."""
        from src.services.migration_recipes import get_recipe

        recipes = []
        for rid in recipe_ids:
            r = get_recipe(rid)
            if r:
                recipes.append(r)

        # Sort by priority (descending) but respect prerequisites
        recipes.sort(key=lambda r: r.priority, reverse=True)

        # Topological sort respecting prerequisites
        ordered: list = []
        placed = set()

        def _place(recipe):
            if recipe.id in placed:
                return
            for prereq_id in recipe.prerequisites:
                prereq = get_recipe(prereq_id)
                if prereq and prereq.id in {r.id for r in recipes}:
                    _place(prereq)
            placed.add(recipe.id)
            ordered.append(recipe)

        for r in recipes:
            _place(r)

        # Convert to step dicts
        steps = []
        for idx, recipe in enumerate(ordered):
            steps.append(self._recipe_to_step(idx, recipe, gap_analysis))
        return steps

    def _recipe_to_step(self, index: int, recipe, gap_analysis: dict) -> dict:
        """Convert a recipe into a concrete roadmap step dict."""
        return {
            "index": index,
            "title": recipe.name,
            "description": recipe.description,
            "category": recipe.category,
            "recipe_id": recipe.id,
            "status": "pending",
            "priority": recipe.priority,
            "files_affected": [],
            "result_summary": "",
            "error": None,
            "started_at": None,
            "completed_at": None,
            "agent_instructions": recipe.agent_instructions,
        }

    # ------------------------------------------------------------------
    # Runs — CRUD
    # ------------------------------------------------------------------

    def list_runs(
        self,
        *,
        project_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> list[MigrationRun]:
        with get_session() as db:
            q = db.query(MigrationRun)
            if project_id:
                q = q.filter(MigrationRun.project_id == project_id)
            if status:
                q = q.filter(MigrationRun.status == status)
            return q.order_by(MigrationRun.created_at.desc()).limit(limit).all()

    def get_run(self, run_id: str) -> Optional[MigrationRun]:
        with get_session() as db:
            return db.get(MigrationRun, run_id)

    def cancel_run(self, run_id: str) -> Optional[MigrationRun]:
        with get_session() as db:
            run = db.get(MigrationRun, run_id)
            if not run or run.status not in ("queued", "running", "paused"):
                return None
            run.status = "cancelled"
            run.completed_at = _utcnow()
            db.flush()
            db.expunge(run)
        return run

    # ------------------------------------------------------------------
    # Execution — Phase 3 stubs
    # ------------------------------------------------------------------

    def execute_run(
        self,
        run_id: str,
        config: dict | None = None,
        progress_callback: Optional[Callable] = None,
    ) -> Optional[MigrationRun]:
        """Execute all migration steps sequentially. (Phase 3 implementation)"""
        with get_session() as db:
            run = db.get(MigrationRun, run_id)
            if not run:
                return None

            run.status = "running"
            run.started_at = _utcnow()
            db.flush()

            steps = run.roadmap_steps or []
            total = len(steps)

            for i, step in enumerate(steps):
                if run.status == "cancelled":
                    break

                self._execute_migration_step(run, i, step, config, progress_callback)

                # Update progress
                run.current_step = i + 1
                run.progress_pct = ((i + 1) / total * 100) if total else 100
                db.flush()

            # Finalize
            failed_steps = [s for s in steps if s.get("status") == "failed"]
            run.status = "failed" if failed_steps else "completed"
            run.completed_at = _utcnow()
            run.result_summary = (
                f"Completed {total - len(failed_steps)}/{total} steps"
                + (f" ({len(failed_steps)} failed)" if failed_steps else "")
            )
            db.flush()
            db.expunge(run)

        return run

    def execute_single_step(
        self,
        run_id: str,
        step_index: int,
        config: dict | None = None,
        progress_callback: Optional[Callable] = None,
    ) -> Optional[MigrationRun]:
        """Execute a single migration step. (Phase 3 implementation)"""
        with get_session() as db:
            run = db.get(MigrationRun, run_id)
            if not run:
                return None

            steps = run.roadmap_steps or []
            if step_index < 0 or step_index >= len(steps):
                return None

            step = steps[step_index]
            self._execute_migration_step(run, step_index, step, config, progress_callback)
            db.flush()
            db.expunge(run)

        return run

    def _execute_migration_step(
        self,
        run: MigrationRun,
        step_index: int,
        step: dict,
        config: dict | None,
        progress_callback: Optional[Callable] = None,
    ) -> None:
        """Execute a single migration step using the AI agent. (Phase 3)

        Uses generate_changes_with_agent() from src/agent/analyzer.py to
        apply the recipe instructions against the source repo.
        """
        step["status"] = "running"
        step["started_at"] = _utcnow().isoformat()

        log_entry = {
            "timestamp": _utcnow().isoformat(),
            "stage": "step_start",
            "detail": f"Starting step {step_index}: {step.get('title', '')}",
            "progress": 0,
        }
        run.log = (run.log or []) + [log_entry]

        if progress_callback:
            progress_callback({
                "type": "progress",
                "data": {
                    "step_index": step_index,
                    "stage": "step_start",
                    "detail": f"Starting: {step.get('title', '')}",
                },
            })

        try:
            # Phase 3: Here we would call generate_changes_with_agent()
            # For now, mark as pending (not executed)
            step["status"] = "pending"
            step["result_summary"] = "Execution not yet implemented (Phase 3)"
            step["completed_at"] = _utcnow().isoformat()

        except Exception as exc:
            step["status"] = "failed"
            step["error"] = str(exc)
            step["completed_at"] = _utcnow().isoformat()
            logger.error("Migration step %d failed: %s", step_index, exc)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_stats(self) -> dict:
        """Get aggregate migration statistics."""
        with get_session() as db:
            projects = db.query(MigrationProject).all()
            runs = db.query(MigrationRun).all()

            total_projects = len(projects)
            analyzed = sum(1 for p in projects if p.status == "analyzed")
            completed_runs = sum(1 for r in runs if r.status == "completed")
            running_runs = sum(1 for r in runs if r.status == "running")
            failed_runs = sum(1 for r in runs if r.status == "failed")

            return {
                "total_projects": total_projects,
                "analyzed_projects": analyzed,
                "total_runs": len(runs),
                "completed_runs": completed_runs,
                "running_runs": running_runs,
                "failed_runs": failed_runs,
            }
