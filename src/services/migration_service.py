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
        source_db: dict | None = None,
        destination_db: dict | None = None,
    ) -> MigrationProject:
        """Create a new migration project, registering the source repo.

        migration_mode:
            "migration"   — source repo migrated toward a reference golden template
            "improvement" — existing dest repo assessed for quality, completeness,
                            testing gaps, performance, structure, etc.
            "database"    — compare source and destination database schemas,
                            generate DDL/DML migration scripts
        """
        import hashlib

        merged_config = config or {}
        if source_db:
            merged_config["source_db"] = source_db
        if destination_db:
            merged_config["destination_db"] = destination_db

        if migration_mode == "database":
            # Compute repo_id from DB connection info instead of repo URL
            db_identifier = ""
            if source_db:
                db_identifier = f"{source_db.get('engine', '')}://{source_db.get('host', '')}:{source_db.get('port', '')}/{source_db.get('database', '')}"
                if source_db.get("jdbc_url"):
                    db_identifier = source_db["jdbc_url"]
            repo_id = hashlib.sha256(db_identifier.encode()).hexdigest()[:16]
        else:
            from src.agent.knowledge import compute_repo_id
            repo_id = compute_repo_id(source_local_path, source_repo_url)

        with get_session() as db:
            # Ensure source repo is registered
            repo = db.get(Repo, repo_id)
            if repo is None:
                repo = Repo(
                    id=repo_id,
                    url=source_repo_url or (source_db.get("jdbc_url", "") if source_db else ""),
                    local_path=source_local_path,
                    platform="database" if migration_mode == "database" else self._detect_platform(source_repo_url),
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
                config=merged_config,
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

            # --- Database mode branch ---
            if migration_mode == "database":
                return self._analyze_database_project(project, _log)

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
            "cicd_gaps": [],
            "framework_migration": {},
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

        # CI/CD gaps: pipelines in reference not in source
        src_cicd = {p.get("type", ""): p for p in (source.get("cicd_pipelines") or [])}
        ref_cicd = {p.get("type", ""): p for p in (reference.get("cicd_pipelines") or [])}

        cicd_gaps = []
        for cicd_type, ref_pipeline in ref_cicd.items():
            if cicd_type not in src_cicd:
                cicd_gaps.append({
                    "type": cicd_type,
                    "status": "missing",
                    "reference_file": ref_pipeline.get("file", ""),
                    "reference_stages": ref_pipeline.get("stages", []),
                })
            else:
                src_pipeline = src_cicd[cicd_type]
                ref_stages = set(ref_pipeline.get("stages", []))
                src_stages = set(src_pipeline.get("stages", []))
                missing_stages = ref_stages - src_stages
                if missing_stages:
                    cicd_gaps.append({
                        "type": cicd_type,
                        "status": "missing_stages",
                        "missing_stages": sorted(missing_stages),
                        "source_file": src_pipeline.get("file", ""),
                        "reference_file": ref_pipeline.get("file", ""),
                    })
        if cicd_gaps:
            gaps["categories_with_gaps"].append("cicd")
            gaps["cicd_gaps"] = cicd_gaps

        # Framework migration detection: detect source/reference frameworks
        src_frameworks = (source.get("technologies") or {}).get("framework", [])
        ref_frameworks = (reference.get("technologies") or {}).get("framework", [])
        src_parent = (source.get("technologies") or {}).get("parent_pom")
        ref_parent = (reference.get("technologies") or {}).get("parent_pom")

        if src_frameworks or ref_frameworks:
            gaps["framework_migration"] = {
                "source_framework": src_frameworks[0] if src_frameworks else "Unknown",
                "target_framework": ref_frameworks[0] if ref_frameworks else "Unknown",
                "source_parent_pom": src_parent,
                "target_parent_pom": ref_parent,
            }
            # If different frameworks detected, add to gap categories
            src_fw = src_frameworks[0] if src_frameworks else ""
            ref_fw = ref_frameworks[0] if ref_frameworks else ""
            if src_fw and ref_fw and src_fw != ref_fw:
                if "technology" not in gaps["categories_with_gaps"]:
                    gaps["categories_with_gaps"].append("technology")

        # Summary
        gaps["summary"] = {
            "total_gaps": (
                len(gaps["technology_gaps"])
                + len(gaps["dependency_gaps"])
                + len(gaps["k8s_gaps"])
                + len(gaps["config_gaps"])
                + len(gaps["cicd_gaps"])
            ),
            "technology_gap_count": len(gaps["technology_gaps"]),
            "dependency_gap_count": len(gaps["dependency_gaps"]),
            "k8s_gap_count": len(gaps["k8s_gaps"]),
            "config_gap_count": len(gaps["config_gaps"]),
            "cicd_gap_count": len(gaps["cicd_gaps"]),
            "categories_affected": len(gaps["categories_with_gaps"]),
            "framework_migration": gaps.get("framework_migration", {}),
        }

        return gaps

    # ------------------------------------------------------------------
    # Database Analysis
    # ------------------------------------------------------------------

    def _analyze_database_project(self, project, _log) -> MigrationProject:
        """Analyze a database migration project by introspecting schemas."""
        project_id = project.id
        project_config = project.config or {}
        source_db_config = project_config.get("source_db", {})
        dest_db_config = project_config.get("destination_db", {})

        # 1. Introspect source database schema
        _log("analyze", "Introspecting source database schema...")
        source_schema = self._introspect_database_schema(source_db_config)

        # 2. Optionally introspect destination and compute gaps
        dest_schema: dict = {}
        gap: dict = {"categories_with_gaps": []}

        if dest_db_config and dest_db_config.get("engine"):
            _log("analyze", "Introspecting destination database schema...")
            dest_schema = self._introspect_database_schema(dest_db_config)

            _log("analyze", "Computing database gap analysis...")
            gap = self._compute_database_gap_analysis(source_schema, dest_schema)

        # 3. Run database improvement analysis
        _log("analyze", "Running database improvement analysis...")
        improvement = self._compute_database_improvement_analysis(source_schema)

        # Merge improvement findings into gap categories
        if improvement.get("areas_needing_improvement"):
            gap.setdefault("categories_with_gaps", [])
            for area in improvement["areas_needing_improvement"]:
                if area not in gap["categories_with_gaps"]:
                    gap["categories_with_gaps"].append(area)

        # 4. Persist
        with get_session() as db:
            proj = db.get(MigrationProject, project_id)
            if proj:
                proj.source_profile = source_schema
                proj.reference_profile = dest_schema
                proj.gap_analysis = gap
                proj.improvement_analysis = improvement
                is_nosql = source_schema.get("db_type") == "nosql"
                proj.capacity_current = {
                    "tables": len(source_schema.get("tables", [])),
                    "collections": len(source_schema.get("collections", [])),
                    "views": len(source_schema.get("views", [])),
                    "indexes": len(source_schema.get("indexes", [])),
                    "db_type": "nosql" if is_nosql else "sql",
                }
                proj.status = "analyzed"
                db.flush()
                db.expunge(proj)

        _log("complete", "Database analysis complete")
        return proj

    # NoSQL engine identifiers
    _NOSQL_ENGINES = frozenset({
        "mongodb", "mongo",
        "cassandra",
        "dynamodb",
        "redis",
        "elasticsearch", "elastic",
        "couchbase",
        "neo4j",
    })

    @staticmethod
    def _is_nosql(engine: str) -> bool:
        """Check if an engine string refers to a NoSQL database."""
        return engine.lower() in MigrationService._NOSQL_ENGINES

    def _build_connection_url(self, db_config: dict) -> str:
        """Convert db_config dict to a SQLAlchemy connection URL.

        Accepts {engine, host, port, database, username, password} or {jdbc_url}.
        Supports postgresql, mysql, oracle, sqlserver.
        For NoSQL engines, returns a native connection string (not SQLAlchemy).
        """
        engine_name = db_config.get("engine", "postgresql").lower()

        # NoSQL engines — return native connection string
        if self._is_nosql(engine_name):
            return self._build_nosql_connection_url(db_config)

        jdbc_url = db_config.get("jdbc_url", "")
        if jdbc_url:
            # Convert JDBC URL to SQLAlchemy format
            jdbc_url = jdbc_url.replace("jdbc:", "")
            if "sqlserver" in jdbc_url:
                jdbc_url = jdbc_url.replace("sqlserver", "mssql+pyodbc")
            return jdbc_url

        host = db_config.get("host", "localhost")
        port = db_config.get("port", "")
        database = db_config.get("database", "")
        username = db_config.get("username", "")
        password = db_config.get("password", "")

        engine_map = {
            "postgresql": "postgresql",
            "postgres": "postgresql",
            "mysql": "mysql+pymysql",
            "oracle": "oracle+oracledb",
            "sqlserver": "mssql+pyodbc",
            "mssql": "mssql+pyodbc",
        }
        dialect = engine_map.get(engine_name, engine_name)

        auth = ""
        if username:
            auth = f"{username}:{password}@" if password else f"{username}@"

        port_str = f":{port}" if port else ""
        return f"{dialect}://{auth}{host}{port_str}/{database}"

    def _build_nosql_connection_url(self, db_config: dict) -> str:
        """Build a native connection URL for NoSQL engines."""
        engine = db_config.get("engine", "").lower()
        host = db_config.get("host", "localhost")
        port = db_config.get("port", "")
        database = db_config.get("database", "")
        username = db_config.get("username", "")
        password = db_config.get("password", "")

        auth = ""
        if username:
            auth = f"{username}:{password}@" if password else f"{username}@"
        port_str = f":{port}" if port else ""

        if engine in ("mongodb", "mongo"):
            return f"mongodb://{auth}{host}{port_str}/{database}"
        if engine == "redis":
            return f"redis://{auth}{host}{port_str}/{database or '0'}"
        if engine in ("elasticsearch", "elastic"):
            scheme = "https" if port == "9243" else "http"
            return f"{scheme}://{auth}{host}{port_str}"
        if engine == "cassandra":
            return f"{host}{port_str}"
        if engine == "couchbase":
            return f"couchbase://{host}{port_str}"
        if engine == "neo4j":
            return f"bolt://{auth}{host}{port_str}"
        if engine == "dynamodb":
            return f"dynamodb://{host}{port_str}"
        return f"{engine}://{auth}{host}{port_str}/{database}"

    def _introspect_database_schema(self, db_config: dict) -> dict:
        """Introspect a database schema.

        For SQL engines uses SQLAlchemy inspect().
        For NoSQL engines delegates to _introspect_nosql_schema().

        Returns a dict with engine, database, tables/collections, views,
        indexes, constraints, and introspection_mode.
        Falls back to static mode if the database is unreachable.
        """
        engine_name = db_config.get("engine", "unknown").lower()

        # Route NoSQL engines to dedicated introspection
        if self._is_nosql(engine_name):
            return self._introspect_nosql_schema(db_config)

        schema_result: dict = {
            "engine": db_config.get("engine", "unknown"),
            "database": db_config.get("database", ""),
            "schema": db_config.get("schema", ""),
            "db_type": "sql",
            "tables": [],
            "views": [],
            "indexes": [],
            "constraints": [],
            "introspection_mode": "static",
        }

        try:
            from sqlalchemy import create_engine, inspect as sa_inspect

            url = self._build_connection_url(db_config)
            engine = create_engine(url, pool_pre_ping=True, connect_args={"connect_timeout": 10})
            inspector = sa_inspect(engine)
            schema_name = db_config.get("schema") or None

            schema_result["introspection_mode"] = "live"

            # Tables
            for table_name in inspector.get_table_names(schema=schema_name):
                columns = []
                for col in inspector.get_columns(table_name, schema=schema_name):
                    columns.append({
                        "name": col["name"],
                        "type": str(col["type"]),
                        "nullable": col.get("nullable", True),
                        "primary_key": False,  # updated below
                    })

                pk = inspector.get_pk_constraint(table_name, schema=schema_name)
                pk_cols = set(pk.get("constrained_columns", []))
                for col in columns:
                    if col["name"] in pk_cols:
                        col["primary_key"] = True

                schema_result["tables"].append({
                    "name": table_name,
                    "columns": columns,
                    "column_count": len(columns),
                })

            # Views
            for view_name in inspector.get_view_names(schema=schema_name):
                schema_result["views"].append({"name": view_name})

            # Indexes
            for table_name in inspector.get_table_names(schema=schema_name):
                for idx in inspector.get_indexes(table_name, schema=schema_name):
                    schema_result["indexes"].append({
                        "table": table_name,
                        "name": idx.get("name", ""),
                        "columns": idx.get("column_names", []),
                        "unique": idx.get("unique", False),
                    })

            # Constraints (foreign keys)
            for table_name in inspector.get_table_names(schema=schema_name):
                for fk in inspector.get_foreign_keys(table_name, schema=schema_name):
                    schema_result["constraints"].append({
                        "table": table_name,
                        "name": fk.get("name", ""),
                        "type": "foreign_key",
                        "columns": fk.get("constrained_columns", []),
                        "referred_table": fk.get("referred_table", ""),
                        "referred_columns": fk.get("referred_columns", []),
                    })

            engine.dispose()

        except Exception as exc:
            logger.warning("Database introspection failed (falling back to static): %s", exc)
            schema_result["introspection_mode"] = "static"
            schema_result["introspection_error"] = str(exc)

        return schema_result

    def _introspect_nosql_schema(self, db_config: dict) -> dict:
        """Introspect a NoSQL database schema.

        Supports MongoDB, Redis, Elasticsearch, Cassandra, DynamoDB,
        Couchbase, and Neo4j.  Returns a dict with collections (instead
        of tables), indexes, and introspection_mode.
        """
        engine_name = db_config.get("engine", "").lower()
        schema_result: dict = {
            "engine": db_config.get("engine", "unknown"),
            "database": db_config.get("database", ""),
            "schema": db_config.get("schema", ""),
            "db_type": "nosql",
            "collections": [],
            "tables": [],      # empty — kept for uniform structure
            "views": [],
            "indexes": [],
            "constraints": [],
            "introspection_mode": "static",
        }

        try:
            if engine_name in ("mongodb", "mongo"):
                schema_result = self._introspect_mongodb(db_config, schema_result)
            elif engine_name == "redis":
                schema_result = self._introspect_redis(db_config, schema_result)
            elif engine_name in ("elasticsearch", "elastic"):
                schema_result = self._introspect_elasticsearch(db_config, schema_result)
            elif engine_name == "cassandra":
                schema_result = self._introspect_cassandra(db_config, schema_result)
            elif engine_name == "dynamodb":
                schema_result = self._introspect_dynamodb(db_config, schema_result)
            elif engine_name == "couchbase":
                schema_result = self._introspect_couchbase(db_config, schema_result)
            elif engine_name == "neo4j":
                schema_result = self._introspect_neo4j(db_config, schema_result)
            else:
                schema_result["introspection_error"] = f"Unsupported NoSQL engine: {engine_name}"
        except Exception as exc:
            logger.warning("NoSQL introspection failed (falling back to static): %s", exc)
            schema_result["introspection_mode"] = "static"
            schema_result["introspection_error"] = str(exc)

        return schema_result

    # --- NoSQL engine-specific introspection helpers ---

    def _introspect_mongodb(self, db_config: dict, result: dict) -> dict:
        """Introspect MongoDB collections and sample document fields."""
        from pymongo import MongoClient

        url = self._build_nosql_connection_url(db_config)
        client = MongoClient(url, serverSelectionTimeoutMS=10000)
        db_name = db_config.get("database", "test")
        db = client[db_name]

        result["introspection_mode"] = "live"

        for coll_name in db.list_collection_names():
            # Sample one document to infer field schema
            sample = db[coll_name].find_one()
            fields = []
            if sample:
                for key, value in sample.items():
                    fields.append({
                        "name": key,
                        "type": type(value).__name__,
                        "nullable": True,
                        "primary_key": key == "_id",
                    })

            result["collections"].append({
                "name": coll_name,
                "fields": fields,
                "field_count": len(fields),
                "estimated_count": db[coll_name].estimated_document_count(),
            })

            # Indexes
            for idx_name, idx_info in db[coll_name].index_information().items():
                result["indexes"].append({
                    "collection": coll_name,
                    "table": coll_name,
                    "name": idx_name,
                    "columns": [k for k, _ in idx_info.get("key", [])],
                    "unique": idx_info.get("unique", False),
                })

        client.close()
        return result

    def _introspect_redis(self, db_config: dict, result: dict) -> dict:
        """Introspect Redis key patterns and types."""
        import redis as redis_lib

        url = self._build_nosql_connection_url(db_config)
        client = redis_lib.from_url(url, socket_connect_timeout=10)
        client.ping()

        result["introspection_mode"] = "live"

        # Scan a sample of keys to infer patterns
        key_types: dict = {}
        cursor = 0
        sample_limit = 500
        count = 0
        while count < sample_limit:
            cursor, keys = client.scan(cursor=cursor, count=100)
            for key in keys:
                key_str = key.decode("utf-8", errors="replace") if isinstance(key, bytes) else key
                key_type = client.type(key)
                type_str = key_type.decode("utf-8") if isinstance(key_type, bytes) else str(key_type)
                # Extract key pattern (replace numeric/uuid segments)
                import re as _re
                pattern = _re.sub(r"[0-9a-f]{8,}", "*", key_str)
                pattern = _re.sub(r"\d+", "*", pattern)
                key_types.setdefault(pattern, {"type": type_str, "count": 0})
                key_types[pattern]["count"] += 1
                count += 1
            if cursor == 0:
                break

        for pattern, info in key_types.items():
            result["collections"].append({
                "name": pattern,
                "fields": [{"name": "value", "type": info["type"], "nullable": True, "primary_key": False}],
                "field_count": 1,
                "estimated_count": info["count"],
            })

        db_size = client.dbsize()
        result["collections"].insert(0, {
            "name": f"__db_info (total keys: {db_size})",
            "fields": [],
            "field_count": 0,
            "estimated_count": db_size,
        }) if not result["collections"] else None

        client.close()
        return result

    def _introspect_elasticsearch(self, db_config: dict, result: dict) -> dict:
        """Introspect Elasticsearch index mappings."""
        from elasticsearch import Elasticsearch

        url = self._build_nosql_connection_url(db_config)
        username = db_config.get("username", "")
        password = db_config.get("password", "")
        auth = (username, password) if username else None
        es = Elasticsearch([url], basic_auth=auth, request_timeout=10)

        result["introspection_mode"] = "live"

        indices = es.indices.get(index="*")
        for index_name, index_info in indices.items():
            if index_name.startswith("."):
                continue  # skip system indices
            mappings = index_info.get("mappings", {}).get("properties", {})
            fields = []
            for field_name, field_info in mappings.items():
                fields.append({
                    "name": field_name,
                    "type": field_info.get("type", "object"),
                    "nullable": True,
                    "primary_key": False,
                })
            result["collections"].append({
                "name": index_name,
                "fields": fields,
                "field_count": len(fields),
                "estimated_count": 0,
            })

        es.close()
        return result

    def _introspect_cassandra(self, db_config: dict, result: dict) -> dict:
        """Introspect Cassandra keyspace tables and columns."""
        from cassandra.cluster import Cluster

        host = db_config.get("host", "localhost")
        port = int(db_config.get("port", 9042))
        keyspace = db_config.get("database", "") or db_config.get("schema", "")

        cluster = Cluster([host], port=port, connect_timeout=10)
        session = cluster.connect()

        result["introspection_mode"] = "live"

        if keyspace:
            meta = cluster.metadata.keyspaces.get(keyspace)
            if meta:
                for table_name, table_meta in meta.tables.items():
                    fields = []
                    pk_cols = {col.name for col in table_meta.primary_key}
                    for col_name, col_meta in table_meta.columns.items():
                        fields.append({
                            "name": col_name,
                            "type": str(col_meta.cql_type),
                            "nullable": True,
                            "primary_key": col_name in pk_cols,
                        })
                    result["collections"].append({
                        "name": table_name,
                        "fields": fields,
                        "field_count": len(fields),
                        "estimated_count": 0,
                    })

        cluster.shutdown()
        return result

    def _introspect_dynamodb(self, db_config: dict, result: dict) -> dict:
        """Introspect DynamoDB tables and key schemas."""
        import boto3

        region = db_config.get("schema", "") or "us-east-1"
        endpoint_url = None
        host = db_config.get("host", "")
        if host and host != "aws":
            port = db_config.get("port", "8000")
            endpoint_url = f"http://{host}:{port}"

        client = boto3.client("dynamodb", region_name=region, endpoint_url=endpoint_url)

        result["introspection_mode"] = "live"

        table_names = client.list_tables().get("TableNames", [])
        for table_name in table_names:
            desc = client.describe_table(TableName=table_name)["Table"]
            key_schema = desc.get("KeySchema", [])
            attr_defs = {a["AttributeName"]: a["AttributeType"] for a in desc.get("AttributeDefinitions", [])}
            pk_names = {k["AttributeName"] for k in key_schema}

            fields = []
            for attr_name, attr_type in attr_defs.items():
                type_map = {"S": "String", "N": "Number", "B": "Binary"}
                fields.append({
                    "name": attr_name,
                    "type": type_map.get(attr_type, attr_type),
                    "nullable": attr_name not in pk_names,
                    "primary_key": attr_name in pk_names,
                })

            result["collections"].append({
                "name": table_name,
                "fields": fields,
                "field_count": len(fields),
                "estimated_count": desc.get("ItemCount", 0),
            })

            # GSIs as indexes
            for gsi in desc.get("GlobalSecondaryIndexes", []):
                result["indexes"].append({
                    "collection": table_name,
                    "table": table_name,
                    "name": gsi["IndexName"],
                    "columns": [k["AttributeName"] for k in gsi.get("KeySchema", [])],
                    "unique": False,
                })

        return result

    def _introspect_couchbase(self, db_config: dict, result: dict) -> dict:
        """Introspect Couchbase bucket info (basic metadata)."""
        result["introspection_mode"] = "static"
        result["introspection_error"] = "Couchbase live introspection requires Couchbase SDK — showing static config"
        bucket = db_config.get("database", "default")
        result["collections"].append({
            "name": bucket,
            "fields": [],
            "field_count": 0,
            "estimated_count": 0,
        })
        return result

    def _introspect_neo4j(self, db_config: dict, result: dict) -> dict:
        """Introspect Neo4j node labels and relationship types."""
        from neo4j import GraphDatabase

        url = self._build_nosql_connection_url(db_config)
        username = db_config.get("username", "neo4j")
        password = db_config.get("password", "")
        driver = GraphDatabase.driver(url, auth=(username, password))

        result["introspection_mode"] = "live"

        with driver.session() as session:
            # Node labels
            labels_result = session.run("CALL db.labels()")
            for record in labels_result:
                label = record[0]
                # Get sample properties
                props_result = session.run(
                    f"MATCH (n:`{label}`) RETURN properties(n) LIMIT 1"
                )
                fields = []
                for prop_record in props_result:
                    props = prop_record[0]
                    if props:
                        for key, value in props.items():
                            fields.append({
                                "name": key,
                                "type": type(value).__name__,
                                "nullable": True,
                                "primary_key": False,
                            })
                count_result = session.run(f"MATCH (n:`{label}`) RETURN count(n)")
                count = count_result.single()[0]
                result["collections"].append({
                    "name": f":{label}",
                    "fields": fields,
                    "field_count": len(fields),
                    "estimated_count": count,
                })

            # Relationship types
            rels_result = session.run("CALL db.relationshipTypes()")
            for record in rels_result:
                rel_type = record[0]
                result["constraints"].append({
                    "table": "",
                    "name": rel_type,
                    "type": "relationship",
                    "columns": [],
                    "referred_table": "",
                    "referred_columns": [],
                })

        driver.close()
        return result

    def _compute_database_gap_analysis(self, source: dict, dest: dict) -> dict:
        """Compare source and destination database schemas.

        Handles both SQL (tables/columns) and NoSQL (collections/fields)
        schemas, as well as cross-engine (SQL-to-NoSQL) migrations.
        """
        gap: dict = {
            "categories_with_gaps": [],
            "table_gaps": [],
            "collection_gaps": [],
            "column_gaps": [],
            "index_gaps": [],
            "type_mapping_gaps": [],
            "view_gaps": [],
            "summary": {},
        }

        src_is_nosql = source.get("db_type") == "nosql"
        dst_is_nosql = dest.get("db_type") == "nosql"
        is_cross_engine = src_is_nosql != dst_is_nosql

        # Normalize: use collections for NoSQL, tables for SQL
        def _get_entities(schema: dict) -> dict:
            """Return entity dict {name: entity} from either tables or collections."""
            if schema.get("db_type") == "nosql":
                return {c["name"]: c for c in schema.get("collections", [])}
            return {t["name"]: t for t in schema.get("tables", [])}

        def _get_fields(entity: dict) -> dict:
            """Return field dict {name: field} from either columns or fields."""
            return {f["name"]: f for f in entity.get("fields", entity.get("columns", []))}

        src_entities = _get_entities(source)
        dst_entities = _get_entities(dest)

        entity_label = "collection" if (src_is_nosql or dst_is_nosql) else "table"
        gap_key = "collection_gaps" if (src_is_nosql or dst_is_nosql) else "table_gaps"
        gap_category = "database_collections" if (src_is_nosql or dst_is_nosql) else "database_tables"

        # Entity-level gaps
        for name in src_entities:
            if name not in dst_entities:
                gap[gap_key].append({entity_label: name, "status": "missing_in_destination"})
        for name in dst_entities:
            if name not in src_entities:
                gap[gap_key].append({entity_label: name, "status": "extra_in_destination"})
        if gap[gap_key]:
            gap["categories_with_gaps"].append(gap_category)

        # Field/Column-level gaps (only for entities in both)
        for name in src_entities:
            if name not in dst_entities:
                continue
            src_fields = _get_fields(src_entities[name])
            dst_fields = _get_fields(dst_entities[name])

            for field_name, src_field in src_fields.items():
                if field_name not in dst_fields:
                    gap["column_gaps"].append({
                        entity_label: name, "column": field_name, "status": "missing_in_destination",
                    })
                else:
                    dst_field = dst_fields[field_name]
                    if str(src_field.get("type", "")).lower() != str(dst_field.get("type", "")).lower():
                        gap["type_mapping_gaps"].append({
                            entity_label: name, "column": field_name,
                            "source_type": str(src_field.get("type", "")),
                            "destination_type": str(dst_field.get("type", "")),
                            "status": "type_mismatch",
                        })
        if gap["column_gaps"]:
            gap["categories_with_gaps"].append("database_columns")
        if gap["type_mapping_gaps"]:
            gap["categories_with_gaps"].append("database_types")

        # Cross-engine gap flag
        if is_cross_engine:
            gap["categories_with_gaps"].append("database_nosql")

        # Index gaps
        src_indexes = {f"{i.get('table', i.get('collection', ''))}.{i['name']}": i for i in source.get("indexes", [])}
        dst_indexes = {f"{i.get('table', i.get('collection', ''))}.{i['name']}": i for i in dest.get("indexes", [])}
        for key in src_indexes:
            if key not in dst_indexes:
                gap["index_gaps"].append({**src_indexes[key], "status": "missing_in_destination"})
        if gap["index_gaps"]:
            gap["categories_with_gaps"].append("database_indexes")

        # View gaps (SQL only)
        src_views = {v["name"] for v in source.get("views", [])}
        dst_views = {v["name"] for v in dest.get("views", [])}
        for name in src_views - dst_views:
            gap["view_gaps"].append({"view": name, "status": "missing_in_destination"})
        if gap["view_gaps"]:
            gap["categories_with_gaps"].append("database_views")

        # Summary
        total = (
            len(gap["table_gaps"])
            + len(gap["collection_gaps"])
            + len(gap["column_gaps"])
            + len(gap["index_gaps"])
            + len(gap["type_mapping_gaps"])
            + len(gap["view_gaps"])
        )
        gap["summary"] = {
            "total_gaps": total,
            "table_gap_count": len(gap["table_gaps"]),
            "collection_gap_count": len(gap["collection_gaps"]),
            "column_gap_count": len(gap["column_gaps"]),
            "index_gap_count": len(gap["index_gaps"]),
            "type_mapping_gap_count": len(gap["type_mapping_gaps"]),
            "view_gap_count": len(gap["view_gaps"]),
            "categories_affected": len(gap["categories_with_gaps"]),
            "cross_engine": is_cross_engine,
        }

        return gap

    def _compute_database_improvement_analysis(self, schema: dict) -> dict:
        """Analyze a database schema for quality improvements.

        Works for both SQL (tables/columns) and NoSQL (collections/fields).
        """
        improvement: dict = {
            "areas_needing_improvement": [],
            "indexing": {"needs_improvement": False, "issues": []},
            "constraints": {"needs_improvement": False, "issues": []},
            "schema_design": {"needs_improvement": False, "issues": []},
            "summary": {},
        }

        is_nosql = schema.get("db_type") == "nosql"
        entities = schema.get("collections", []) if is_nosql else schema.get("tables", [])
        indexes = schema.get("indexes", [])
        constraints = schema.get("constraints", [])
        entity_label = "collection" if is_nosql else "table"

        # Entities without indexes
        indexed_entities = {i.get("table", i.get("collection", "")) for i in indexes}
        entities_without_indexes = [e["name"] for e in entities if e["name"] not in indexed_entities]
        if entities_without_indexes:
            improvement["indexing"]["issues"].append(
                f"{len(entities_without_indexes)} {entity_label}(s) without any indexes: {', '.join(entities_without_indexes[:5])}"
            )
            improvement["indexing"]["needs_improvement"] = True

        if is_nosql:
            # NoSQL-specific checks
            # Collections with very wide schemas (too many fields)
            wide_collections = [
                e["name"] for e in entities
                if e.get("field_count", len(e.get("fields", []))) > 50
            ]
            if wide_collections:
                improvement["schema_design"]["issues"].append(
                    f"{len(wide_collections)} collection(s) with >50 fields (consider subdocuments): {', '.join(wide_collections[:5])}"
                )
                improvement["schema_design"]["needs_improvement"] = True

            # Collections without _id or primary key field
            no_pk = [
                e["name"] for e in entities
                if not any(f.get("primary_key") for f in e.get("fields", []))
            ]
            if no_pk and schema.get("engine", "").lower() not in ("redis",):
                improvement["constraints"]["issues"].append(
                    f"{len(no_pk)} {entity_label}(s) without identifiable primary key"
                )
                improvement["constraints"]["needs_improvement"] = True
        else:
            # SQL-specific checks
            # Tables without primary keys
            tables_without_pk = []
            for t in entities:
                has_pk = any(c.get("primary_key") for c in t.get("columns", []))
                if not has_pk:
                    tables_without_pk.append(t["name"])
            if tables_without_pk:
                improvement["constraints"]["issues"].append(
                    f"{len(tables_without_pk)} table(s) without primary keys: {', '.join(tables_without_pk[:5])}"
                )
                improvement["constraints"]["needs_improvement"] = True

            # Few foreign keys relative to table count
            fk_count = len([c for c in constraints if c.get("type") == "foreign_key"])
            if len(entities) > 3 and fk_count < len(entities) // 2:
                improvement["constraints"]["issues"].append(
                    f"Few foreign key constraints ({fk_count}) relative to table count ({len(entities)})"
                )
                improvement["constraints"]["needs_improvement"] = True

        if improvement["indexing"]["needs_improvement"]:
            improvement["areas_needing_improvement"].append("database_indexes")
        if improvement["constraints"]["needs_improvement"]:
            improvement["areas_needing_improvement"].append("database_constraints")
        if improvement["schema_design"]["needs_improvement"]:
            improvement["areas_needing_improvement"].append("database_collections")

        improvement["summary"] = {
            "total_areas_scanned": 3,
            "areas_needing_improvement": len(improvement["areas_needing_improvement"]),
            "improvement_areas": improvement["areas_needing_improvement"],
        }
        return improvement

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
            # 1. Load project from DB (run.project relationship)
            project = run.project

            # 2. Get target repo/branch from run.artifacts (set by API before execution)
            target_repo_url = (run.artifacts or {}).get("target_repo_url", project.source_repo_url)
            target_branch = (run.artifacts or {}).get("target_branch", "migration/" + _uuid())

            # 3. Resolve repo path (clone if needed)
            repo_path = self._resolve_repo_path(
                project.source_local_path, target_repo_url,
                project.source_branch, project.repo_id, config
            )

            # 4. Checkout target branch (create if needed)
            from src.platform.git_ops import checkout_branch
            checkout_branch(repo_path, target_branch, create=True)

            # 5. Build consciousness + code index for understanding the repo
            from src.consciousness.core import build_or_load_consciousness, build_consciousness as _build_ref_consciousness
            from src.code_index.storage import build_or_load_code_index
            from src.agent.knowledge import load_repo_knowledge
            from src.code.executor import detect_build_tool

            consciousness = build_or_load_consciousness(repo_path, config or {}, repo_url=target_repo_url)
            code_index = build_or_load_code_index(repo_path, config or {}, repo_url=target_repo_url, consciousness=consciousness)
            repo_knowledge = load_repo_knowledge(repo_path)
            build_tool = detect_build_tool(repo_path)

            # 5b. Build reference repo consciousness (structure + code samples)
            ref_consciousness_text = ""
            reference_repo_path = ""
            has_reference = bool(project.reference_repo_url or project.reference_local_path)
            if has_reference:
                try:
                    reference_repo_path = self._clone_reference_repo(
                        project.reference_repo_url,
                        project.reference_local_path,
                        project.reference_branch,
                    )
                    ref_consciousness = _build_ref_consciousness(
                        reference_repo_path,
                        repo_url=project.reference_repo_url or "",
                    )
                    # Render with full detail: structure + samples + signatures
                    ref_consciousness_text = ref_consciousness._render_full(
                        max_samples_chars=25000,
                        structure_depth=4,
                        max_sigs=40,
                    )
                except Exception as ref_err:
                    logger.warning("Could not build reference consciousness: %s", ref_err)

            # 6. Build requirements from recipe instructions + gap context + reference structure
            recipe_instructions = step.get("agent_instructions", step.get("description", ""))
            ref_profile = project.reference_profile or {}
            gap_analysis = project.gap_analysis or {}

            # Build rich reference context
            ref_context_parts = []
            ref_context_parts.append(f"Technologies: {ref_profile.get('technologies', [])}")
            ref_context_parts.append(f"Config sources: {ref_profile.get('config_sources', [])}")

            # Include reference directory structure + code samples
            if ref_consciousness_text:
                ref_context_parts.append("")
                ref_context_parts.append("### Reference Repo Structure & Code Samples")
                ref_context_parts.append(ref_consciousness_text)

            # Include reference dependency details
            ref_deps = ref_profile.get("dependencies", [])
            if ref_deps:
                ref_context_parts.append("")
                ref_context_parts.append("### Reference Dependencies")
                for dep in ref_deps[:30]:
                    ref_context_parts.append(
                        f"  - {dep.get('group', '')}:{dep.get('artifact', '')}:{dep.get('version', '')}"
                    )

            # Include reference API patterns
            ref_endpoints = ref_profile.get("api_endpoints", [])
            if ref_endpoints:
                ref_context_parts.append("")
                ref_context_parts.append("### Reference API Patterns")
                for ep in ref_endpoints[:20]:
                    ref_context_parts.append(
                        f"  - {ep.get('http_method', 'GET')} {ep.get('path', '')} "
                        f"→ {ep.get('class', '')}.{ep.get('method', '')}"
                    )

            ref_context = "\n".join(ref_context_parts)

            # Build reference file reading instruction
            ref_read_instruction = ""
            if reference_repo_path:
                ref_read_instruction = (
                    f"\n\n### Reference Repository Access\n"
                    f"The reference (golden template) repo is available at: {reference_repo_path}\n"
                    f"Use `run_command` with `cat`, `find`, or `ls` on that path to read reference files.\n"
                    f"IMPORTANT: You MUST read actual reference files to match their exact patterns:\n"
                    f"  - Package structure and naming conventions\n"
                    f"  - Class/method organization and coding style\n"
                    f"  - Configuration format and property naming\n"
                    f"  - Test structure and patterns\n"
                    f"  - Build configuration (pom.xml / build.gradle)\n"
                    f"Generate code that follows the reference repo's conventions, NOT generic defaults."
                )

            # Resolve tool context from recipe's attached tools
            tool_context = ""
            recipe_id = step.get("recipe_id", "")
            if recipe_id:
                try:
                    from src.agent.recipe_context import build_recipe_context
                    tool_context = build_recipe_context([recipe_id])
                except Exception as tc_err:
                    logger.debug("Could not build tool context for recipe %s: %s", recipe_id, tc_err)

            tool_section = f"\n{tool_context}\n" if tool_context else ""

            requirements = (
                f"## Migration Task: {step.get('title', '')}\n\n"
                f"### Instructions\n{recipe_instructions}\n\n"
                f"{tool_section}"
                f"### Reference Architecture\n{ref_context}\n\n"
                f"### Gap Context\n"
                f"Technology gaps: {gap_analysis.get('technology_gaps', [])}\n"
                f"Framework migration: {gap_analysis.get('framework_migration', {})}\n"
                f"{ref_read_instruction}\n\n"
                f"CRITICAL: Generate code that matches the reference repo's structure, naming "
                f"conventions, package layout, and coding patterns — NOT generic Spring Boot defaults. "
                f"Read reference files first to understand the exact patterns before making changes.\n\n"
                f"Apply changes to this repository. Do NOT create placeholder or stub files."
            )

            # 7. Call AI agent
            from src.agent.analyzer import generate_changes_with_agent
            ai_cfg = (config or {}).get("ai", {})
            agent_config = (config or {}).get("agent", {})

            result = generate_changes_with_agent(
                requirements=requirements,
                repo_path=repo_path,
                llm_config=ai_cfg,
                consciousness=consciousness,
                agent_config=agent_config,
                config=config,
                repo_url=target_repo_url,
                repo_knowledge=repo_knowledge,
                code_index=code_index,
                build_tool=build_tool,
            )

            # 8. Update step with results
            step["status"] = "completed" if result.success else "failed"
            step["result_summary"] = result.summary
            step["files_affected"] = result.files_changed
            step["completed_at"] = _utcnow().isoformat()

            # 9. Commit + push if files were changed
            if result.files_changed:
                from src.platform.git_ops import stage_and_commit, push_branch
                commit_msg = f"migration: {step.get('title', 'step ' + str(step_index))}"
                stage_and_commit(repo_path, commit_msg)
                try:
                    push_branch(repo_path, target_branch)
                except Exception as push_err:
                    logger.warning("Push failed (may need auth): %s", push_err)
                    step["result_summary"] += f"\n(Push failed: {push_err})"

            # 10. Track token usage
            if result.usage_stats:
                run.total_tokens_used = (run.total_tokens_used or 0) + result.usage_stats.total_tokens

        except Exception as exc:
            step["status"] = "failed"
            step["error"] = str(exc)
            step["completed_at"] = _utcnow().isoformat()
            logger.error("Migration step %d failed: %s", step_index, exc)

    def update_run_target(self, run_id: str, target_repo_url: str, target_branch: str) -> None:
        """Store target repo URL and branch in run artifacts for execution."""
        with get_session() as db:
            run = db.get(MigrationRun, run_id)
            if run:
                artifacts = run.artifacts or {}
                if target_repo_url:
                    artifacts["target_repo_url"] = target_repo_url
                if target_branch:
                    artifacts["target_branch"] = target_branch
                run.artifacts = artifacts
                db.flush()

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
