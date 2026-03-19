"""
SQLAlchemy ORM models — unified data layer for code-autonomy.

Consolidates 7 independent JSON/pickle stores into a single relational schema.
Supports SQLite (single-node) and PostgreSQL (multi-tenant) via DATABASE_URL.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship

from sqlalchemy import JSON


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return uuid.uuid4().hex[:16]


# ---------------------------------------------------------------------------
# Repo — registered repository
# ---------------------------------------------------------------------------

class Repo(Base):
    __tablename__ = "repos"

    id = Column(String(64), primary_key=True)  # repo_id hash (compute_repo_id)
    url = Column(String(1024), nullable=False, default="")
    local_path = Column(String(1024), nullable=False, default="")
    platform = Column(String(32), nullable=False, default="local")  # github | bitbucket | local
    nickname = Column(String(256), nullable=False, default="")  # friendly display name
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    # Relationships
    sessions = relationship("Session", back_populates="repo", cascade="all, delete-orphan")
    knowledge_entries = relationship("Knowledge", back_populates="repo", cascade="all, delete-orphan")
    consciousness = relationship("Consciousness", back_populates="repo", uselist=False, cascade="all, delete-orphan")
    gcc_state = relationship("GCCState", back_populates="repo", uselist=False, cascade="all, delete-orphan")
    jira_sessions = relationship("JiraSession", back_populates="repo", cascade="all, delete-orphan")
    jira_runs = relationship("JiraRun", back_populates="repo", cascade="all, delete-orphan")
    test_projects = relationship("TestProject", back_populates="repo", cascade="all, delete-orphan")
    migration_projects = relationship("MigrationProject", back_populates="repo", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Repo id={self.id!r} url={self.url!r}>"


# ---------------------------------------------------------------------------
# Session — agent/plan/ask execution session
# ---------------------------------------------------------------------------

class Session(Base):
    __tablename__ = "sessions"

    id = Column(String(64), primary_key=True, default=_uuid)
    repo_id = Column(String(64), ForeignKey("repos.id"), nullable=False, index=True)
    mode = Column(String(32), nullable=False, default="agent")  # agent | plan | ask | jira | legacy
    status = Column(String(32), nullable=False, default="running")  # running | completed | failed | paused
    requirements = Column(Text, nullable=False, default="")
    result_summary = Column(Text, nullable=False, default="")
    turns_used = Column(Integer, nullable=False, default=0)
    trace_id = Column(String(64), nullable=True)
    log = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    repo = relationship("Repo", back_populates="sessions")
    checkpoints = relationship("Checkpoint", back_populates="session", cascade="all, delete-orphan")
    traces = relationship("Trace", back_populates="session", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Session id={self.id!r} mode={self.mode!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# Checkpoint — agent run snapshot for resumption
# ---------------------------------------------------------------------------

class Checkpoint(Base):
    __tablename__ = "checkpoints"

    id = Column(String(64), primary_key=True, default=_uuid)
    session_id = Column(String(64), ForeignKey("sessions.id"), nullable=False, index=True)
    repo_id = Column(String(64), nullable=False, index=True)
    turns_used = Column(Integer, nullable=False, default=0)
    working_memory = Column(JSON, nullable=False, default=dict)
    files_changed = Column(JSON, nullable=False, default=list)
    summary = Column(Text, nullable=False, default="")
    pending_work = Column(Text, nullable=False, default="")
    requirement_hash = Column(String(64), nullable=False, default="")
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    # Relationships
    session = relationship("Session", back_populates="checkpoints")

    def __repr__(self) -> str:
        return f"<Checkpoint id={self.id!r} session={self.session_id!r}>"


# ---------------------------------------------------------------------------
# Trace — execution trace record
# ---------------------------------------------------------------------------

class Trace(Base):
    __tablename__ = "traces"

    id = Column(String(64), primary_key=True)  # trace_id from TraceCollector
    session_id = Column(String(64), ForeignKey("sessions.id"), nullable=True, index=True)
    repo_id = Column(String(64), nullable=False, index=True)
    spans = Column(JSON, nullable=False, default=list)
    total_tokens = Column(Integer, nullable=False, default=0)
    total_cost = Column(Float, nullable=False, default=0.0)
    duration_s = Column(Float, nullable=False, default=0.0)
    model = Column(String(128), nullable=False, default="")
    success = Column(Boolean, nullable=False, default=False)
    turns_used = Column(Integer, nullable=False, default=0)
    files_changed = Column(JSON, nullable=False, default=list)
    summary = Column(Text, nullable=False, default="")
    metrics = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    # Relationships
    session = relationship("Session", back_populates="traces")

    def __repr__(self) -> str:
        return f"<Trace id={self.id!r} repo={self.repo_id!r}>"


# ---------------------------------------------------------------------------
# Knowledge — persistent learning record per repo
# ---------------------------------------------------------------------------

class Knowledge(Base):
    __tablename__ = "knowledge"

    id = Column(String(64), primary_key=True, default=_uuid)
    repo_id = Column(String(64), ForeignKey("repos.id"), nullable=False, index=True)
    key = Column(String(256), nullable=False, default="")
    content = Column(Text, nullable=False, default="")
    source = Column(String(32), nullable=False, default="agent")  # agent | user | auto
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    # Relationships
    repo = relationship("Repo", back_populates="knowledge_entries")

    __table_args__ = (
        UniqueConstraint("repo_id", "key", name="uq_knowledge_repo_key"),
    )

    def __repr__(self) -> str:
        return f"<Knowledge id={self.id!r} repo={self.repo_id!r} key={self.key!r}>"


# ---------------------------------------------------------------------------
# GCCState — Git Context Controller state per repo
# ---------------------------------------------------------------------------

class GCCState(Base):
    __tablename__ = "gcc_states"

    repo_id = Column(String(64), ForeignKey("repos.id"), primary_key=True)
    state_data = Column(JSON, nullable=False, default=dict)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    # Relationships
    repo = relationship("Repo", back_populates="gcc_state")

    def __repr__(self) -> str:
        return f"<GCCState repo={self.repo_id!r}>"


# ---------------------------------------------------------------------------
# Consciousness — project consciousness cache per repo
# ---------------------------------------------------------------------------

class Consciousness(Base):
    __tablename__ = "consciousness"

    repo_id = Column(String(64), ForeignKey("repos.id"), primary_key=True)
    structure_tree = Column(Text, nullable=False, default="")
    file_signatures = Column(JSON, nullable=False, default=list)
    implementation_samples = Column(JSON, nullable=False, default=list)
    conventions = Column(JSON, nullable=False, default=dict)
    indexed_at = Column(Float, nullable=False, default=0.0)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    # Relationships
    repo = relationship("Repo", back_populates="consciousness")

    def __repr__(self) -> str:
        return f"<Consciousness repo={self.repo_id!r}>"


# ---------------------------------------------------------------------------
# JiraSession — JIRA multi-story processing session
# ---------------------------------------------------------------------------

class JiraSession(Base):
    __tablename__ = "jira_sessions"

    id = Column(String(64), primary_key=True, default=_uuid)
    repo_id = Column(String(64), ForeignKey("repos.id"), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="active")  # active | completed | failed
    stories = Column(JSON, nullable=False, default=list)
    config = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    # Relationships
    repo = relationship("Repo", back_populates="jira_sessions")

    def __repr__(self) -> str:
        return f"<JiraSession id={self.id!r} repo={self.repo_id!r}>"


# ---------------------------------------------------------------------------
# JiraRun — tracked JIRA-to-PR generation run (mirrors TestRun pattern)
# ---------------------------------------------------------------------------

class JiraRun(Base):
    __tablename__ = "jira_runs"

    id = Column(String(64), primary_key=True, default=_uuid)
    repo_id = Column(String(64), ForeignKey("repos.id"), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="queued")
    # queued | running | completed | failed | error | cancelled
    agent_id = Column(String(64), nullable=True)

    # JIRA-specific
    jira_project = Column(String(64), nullable=False, default="")
    total_stories = Column(Integer, nullable=False, default=0)
    completed_stories = Column(Integer, nullable=False, default=0)
    succeeded_stories = Column(Integer, nullable=False, default=0)
    failed_stories = Column(Integer, nullable=False, default=0)

    # Shared tracking (same pattern as TestRun)
    progress_pct = Column(Float, nullable=False, default=0.0)
    log = Column(JSON, nullable=False, default=list)
    result_summary = Column(Text, nullable=False, default="")
    artifacts = Column(JSON, nullable=False, default=dict)
    config = Column(JSON, nullable=False, default=dict)

    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    repo = relationship("Repo", back_populates="jira_runs")

    def __repr__(self) -> str:
        return f"<JiraRun id={self.id!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# ConfigProfile — named configuration profiles
# ---------------------------------------------------------------------------

class ConfigProfile(Base):
    __tablename__ = "config_profiles"

    id = Column(String(64), primary_key=True, default=_uuid)
    name = Column(String(128), nullable=False, unique=True)
    config_data = Column(JSON, nullable=False, default=dict)
    is_active = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    def __repr__(self) -> str:
        return f"<ConfigProfile name={self.name!r} active={self.is_active}>"


# ---------------------------------------------------------------------------
# ModelConfig — user-configured LLM models for per-session selection
# ---------------------------------------------------------------------------

class ModelConfig(Base):
    __tablename__ = "model_configs"

    id = Column(String(64), primary_key=True, default=_uuid)
    label = Column(String(128), nullable=False)
    provider = Column(String(32), nullable=False)  # openai | anthropic | gemini | azure | bedrock
    model = Column(String(256), nullable=False)
    api_key = Column(String(1024), nullable=False, default="")
    base_url = Column(String(1024), nullable=False, default="")
    extra_config = Column(JSON, nullable=False, default=dict)
    is_default = Column(Boolean, nullable=False, default=False)
    is_system = Column(Boolean, nullable=False, default=False)  # True = seeded from config.ini, read-only
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    def __repr__(self) -> str:
        return f"<ModelConfig id={self.id!r} label={self.label!r} provider={self.provider!r}>"


# ---------------------------------------------------------------------------
# TestProject — onboarded repository for testing
# ---------------------------------------------------------------------------

class TestProject(Base):
    __tablename__ = "test_projects"

    id = Column(String(64), primary_key=True, default=_uuid)
    repo_id = Column(String(64), ForeignKey("repos.id"), nullable=False, index=True)
    name = Column(String(256), nullable=False)
    repo_url = Column(String(1024), nullable=False, default="")
    local_path = Column(String(1024), nullable=False, default="")
    language = Column(String(32), nullable=False, default="auto")  # java | python | auto
    framework = Column(String(64), nullable=False, default="auto")  # spring | django | flask | auto
    testing_framework = Column(String(64), nullable=False, default="auto")  # junit | pytest | cucumber | auto
    branch = Column(String(256), nullable=False, default="main")
    status = Column(String(32), nullable=False, default="pending")  # pending | indexing | ready | error
    discovery_result = Column(JSON, nullable=False, default=dict)  # auto-discovered endpoints, services, etc.
    config = Column(JSON, nullable=False, default=dict)  # custom overrides
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    # Relationships
    repo = relationship("Repo", back_populates="test_projects")
    test_runs = relationship("TestRun", back_populates="project", cascade="all, delete-orphan")
    coverage_reports = relationship("CoverageReport", back_populates="project", cascade="all, delete-orphan")
    data_injection_configs = relationship("DataInjectionConfig", back_populates="project", cascade="all, delete-orphan")
    custom_steps = relationship("CustomStep", back_populates="project", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<TestProject id={self.id!r} name={self.name!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# TestRun — agent execution for test generation/execution
# ---------------------------------------------------------------------------

class TestRun(Base):
    __tablename__ = "test_runs"

    id = Column(String(64), primary_key=True, default=_uuid)
    project_id = Column(String(64), ForeignKey("test_projects.id"), nullable=False, index=True)
    run_type = Column(String(32), nullable=False, default="functional")  # functional | security | regression | smoke
    status = Column(String(32), nullable=False, default="queued")  # queued | running | passed | failed | error | cancelled
    agent_id = Column(String(64), nullable=True)  # tracking which agent is working
    target_scope = Column(Text, nullable=False, default="")  # which services/endpoints to test
    strategy = Column(String(64), nullable=False, default="auto")  # auto | bdd | unit | integration | e2e | penetration
    branch = Column(String(256), nullable=False, default="main")
    total_tests = Column(Integer, nullable=False, default=0)
    passed_tests = Column(Integer, nullable=False, default=0)
    failed_tests = Column(Integer, nullable=False, default=0)
    skipped_tests = Column(Integer, nullable=False, default=0)
    progress_pct = Column(Float, nullable=False, default=0.0)
    log = Column(JSON, nullable=False, default=list)  # list of log entries
    result_summary = Column(Text, nullable=False, default="")
    artifacts = Column(JSON, nullable=False, default=dict)  # generated files, reports
    config = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    project = relationship("TestProject", back_populates="test_runs")
    evidences = relationship("TestEvidence", back_populates="test_run", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<TestRun id={self.id!r} type={self.run_type!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# TestEvidence — test artifacts, screenshots, logs
# ---------------------------------------------------------------------------

class TestEvidence(Base):
    __tablename__ = "test_evidences"

    id = Column(String(64), primary_key=True, default=_uuid)
    test_run_id = Column(String(64), ForeignKey("test_runs.id"), nullable=False, index=True)
    evidence_type = Column(String(32), nullable=False, default="log")  # log | screenshot | report | file | diff
    title = Column(String(256), nullable=False, default="")
    content = Column(Text, nullable=False, default="")  # text content or base64 for binary
    file_path = Column(String(1024), nullable=False, default="")
    extra_data = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    # Relationships
    test_run = relationship("TestRun", back_populates="evidences")

    def __repr__(self) -> str:
        return f"<TestEvidence id={self.id!r} type={self.evidence_type!r}>"


# ---------------------------------------------------------------------------
# CoverageReport — coverage analysis results
# ---------------------------------------------------------------------------

class CoverageReport(Base):
    __tablename__ = "coverage_reports"

    id = Column(String(64), primary_key=True, default=_uuid)
    project_id = Column(String(64), ForeignKey("test_projects.id"), nullable=False, index=True)
    report_type = Column(String(32), nullable=False, default="code")  # code | functional | api | security
    overall_pct = Column(Float, nullable=False, default=0.0)
    line_coverage = Column(Float, nullable=False, default=0.0)
    branch_coverage = Column(Float, nullable=False, default=0.0)
    function_coverage = Column(Float, nullable=False, default=0.0)
    uncovered_areas = Column(JSON, nullable=False, default=list)  # list of uncovered functions/endpoints
    gaps = Column(JSON, nullable=False, default=list)  # coverage gaps with suggestions
    details = Column(JSON, nullable=False, default=dict)  # per-file breakdown
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)

    # Relationships
    project = relationship("TestProject", back_populates="coverage_reports")

    def __repr__(self) -> str:
        return f"<CoverageReport id={self.id!r} type={self.report_type!r} pct={self.overall_pct}>"


# ---------------------------------------------------------------------------
# DataInjectionConfig — data injection strategy configuration
# ---------------------------------------------------------------------------

class DataInjectionConfig(Base):
    __tablename__ = "data_injection_configs"

    id = Column(String(64), primary_key=True, default=_uuid)
    project_id = Column(String(64), ForeignKey("test_projects.id"), nullable=False, index=True)
    name = Column(String(256), nullable=False)
    strategy = Column(String(64), nullable=False, default="synthetic")  # synthetic | factory | pool | masked | environment
    target_entity = Column(String(256), nullable=False, default="")  # e.g. "User", "Order", "Account"
    schema_definition = Column(JSON, nullable=False, default=dict)  # field definitions with types/constraints
    sample_data = Column(JSON, nullable=False, default=list)  # generated sample data
    environment_rules = Column(JSON, nullable=False, default=dict)  # env-specific overrides (dev/staging/prod)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    # Relationships
    project = relationship("TestProject", back_populates="data_injection_configs")

    def __repr__(self) -> str:
        return f"<DataInjectionConfig id={self.id!r} name={self.name!r}>"


# ---------------------------------------------------------------------------
# CustomStep — reusable test step definitions
# ---------------------------------------------------------------------------

class CustomStep(Base):
    __tablename__ = "custom_steps"

    id = Column(String(64), primary_key=True, default=_uuid)
    project_id = Column(String(64), ForeignKey("test_projects.id"), nullable=False, index=True)
    name = Column(String(256), nullable=False)
    step_type = Column(String(32), nullable=False, default="given")  # given | when | then | and
    pattern = Column(String(1024), nullable=False, default="")  # Gherkin pattern e.g. "the user is authenticated"
    implementation = Column(Text, nullable=False, default="")  # code implementation
    language = Column(String(32), nullable=False, default="java")
    tags = Column(JSON, nullable=False, default=list)  # categorization tags
    source = Column(String(32), nullable=False, default="user")  # user | discovered | generated
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    # Relationships
    project = relationship("TestProject", back_populates="custom_steps")

    def __repr__(self) -> str:
        return f"<CustomStep id={self.id!r} name={self.name!r}>"


# ---------------------------------------------------------------------------
# ChatMessage — conversation history for natural language interaction
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Workflow — goal-driven orchestration (Workflow Mode)
# ---------------------------------------------------------------------------

class Workflow(Base):
    __tablename__ = "workflows"

    id = Column(String(64), primary_key=True, default=_uuid)
    repo_id = Column(String(64), ForeignKey("repos.id"), nullable=True, index=True)
    project_id = Column(String(64), ForeignKey("test_projects.id"), nullable=True)
    goal = Column(Text, nullable=False, default="")
    mode = Column(String(32), nullable=False, default="testing")  # testing | engineering
    status = Column(String(32), nullable=False, default="planning")
        # planning | running | paused | completed | failed | cancelled
    subtasks = Column(JSON, nullable=False, default=list)
    current_step = Column(Integer, nullable=False, default=0)
    progress_pct = Column(Float, nullable=False, default=0.0)
    result_summary = Column(Text, nullable=False, default="")
    artifacts = Column(JSON, nullable=False, default=dict)
    log = Column(JSON, nullable=False, default=list)
    config = Column(JSON, nullable=False, default=dict)
    token_budget = Column(Integer, nullable=False, default=0)        # 0 = unlimited
    total_tokens_used = Column(Integer, nullable=False, default=0)   # running total
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<Workflow id={self.id!r} goal={self.goal[:40]!r} status={self.status!r}>"


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(String(64), primary_key=True, default=_uuid)
    project_id = Column(String(64), ForeignKey("test_projects.id"), nullable=False, index=True)
    role = Column(String(16), nullable=False, default="user")  # user | assistant | system
    content = Column(Text, nullable=False, default="")
    extra_data = Column(JSON, nullable=False, default=dict)  # tool calls, references, etc.
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)


# ---------------------------------------------------------------------------
# MigrationProject — migration from source repo to reference golden template
# ---------------------------------------------------------------------------

class MigrationProject(Base):
    __tablename__ = "migration_projects"

    id = Column(String(64), primary_key=True, default=_uuid)
    repo_id = Column(String(64), ForeignKey("repos.id"), nullable=False, index=True)
    name = Column(String(256), nullable=False)
    migration_mode = Column(String(32), nullable=False, default="migration")
    # migration — source repo migrated toward reference golden template
    # improvement — existing dest repo assessed for quality, completeness, testing, performance
    source_repo_url = Column(String(1024), nullable=False, default="")
    source_local_path = Column(String(1024), nullable=False, default="")
    source_branch = Column(String(256), nullable=False, default="main")
    reference_repo_url = Column(String(1024), nullable=False, default="")
    reference_local_path = Column(String(1024), nullable=False, default="")
    reference_branch = Column(String(256), nullable=False, default="main")
    reference_folders = Column(JSON, nullable=False, default=list)  # selected folders from reference
    status = Column(String(32), nullable=False, default="pending")
    # pending | analyzing | analyzed | executing | completed | failed
    source_profile = Column(JSON, nullable=False, default=dict)
    reference_profile = Column(JSON, nullable=False, default=dict)
    gap_analysis = Column(JSON, nullable=False, default=dict)
    improvement_analysis = Column(JSON, nullable=False, default=dict)
    # Standalone quality assessment: test coverage, structure, performance, error handling, etc.
    capacity_current = Column(JSON, nullable=False, default=dict)
    capacity_target = Column(JSON, nullable=False, default=dict)
    selected_recipes = Column(JSON, nullable=False, default=list)
    config = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    # Relationships
    repo = relationship("Repo", back_populates="migration_projects")
    migration_runs = relationship("MigrationRun", back_populates="project", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<MigrationProject id={self.id!r} name={self.name!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# CustomMigrationRecipe — user-defined migration recipes (DB-backed)
# ---------------------------------------------------------------------------

class CustomMigrationRecipe(Base):
    __tablename__ = "custom_migration_recipes"

    id = Column(String(128), primary_key=True, default=_uuid)
    name = Column(String(256), nullable=False)
    category = Column(String(64), nullable=False, default="custom")
    description = Column(Text, nullable=False, default="")
    priority = Column(Integer, nullable=False, default=50)
    tags = Column(JSON, nullable=False, default=list)
    prerequisites = Column(JSON, nullable=False, default=list)
    agent_instructions = Column(Text, nullable=False, default="")
    source_framework = Column(String(64), nullable=False, default="")  # e.g. "Nucleus", "JISI"
    target_framework = Column(String(64), nullable=False, default="")  # e.g. "Photon"
    tool_ids = Column(JSON, nullable=False, default=list)  # custom tool IDs to run with this recipe
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    def __repr__(self) -> str:
        return f"<CustomMigrationRecipe id={self.id!r} name={self.name!r}>"


# ---------------------------------------------------------------------------
# MigrationRun — tracked migration execution run
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# CustomTool — user-defined agent tools for migration, chat, testing
# ---------------------------------------------------------------------------

class CustomTool(Base):
    __tablename__ = "custom_tools"

    id = Column(String(64), primary_key=True, default=_uuid)
    name = Column(String(256), nullable=False)
    description = Column(Text, nullable=False, default="")
    tool_type = Column(String(32), nullable=False, default="agent")
    # agent — autonomous agent tool
    # validator — pre/post validation
    # transformer — code transformation
    # analyzer — analysis/reporting

    # Where this tool can be used
    enabled_for_migration = Column(Boolean, nullable=False, default=False)
    enabled_for_chat = Column(Boolean, nullable=False, default=False)
    enabled_for_testing = Column(Boolean, nullable=False, default=False)

    # Agent instructions — the prompt/behavior definition
    agent_instructions = Column(Text, nullable=False, default="")

    # Goal — what this tool should achieve (especially for migration runs)
    goal = Column(Text, nullable=False, default="")

    # Configuration
    allowed_tools = Column(JSON, nullable=False, default=list)
    # e.g. ["Read", "Edit", "Bash", "Grep"]
    parameters = Column(JSON, nullable=False, default=dict)
    # custom parameters the tool accepts
    credential_config = Column(JSON, nullable=False, default=dict)
    # credential configuration: {auth_type, config_section, username, password, token, ...}
    tags = Column(JSON, nullable=False, default=list)
    prerequisites = Column(JSON, nullable=False, default=list)
    # other custom_tool IDs that must run first

    # Execution settings
    max_turns = Column(Integer, nullable=False, default=20)
    model = Column(String(64), nullable=False, default="")  # legacy — prefer model_config_id
    model_config_id = Column(String(64), ForeignKey("model_configs.id"), nullable=True)
    timeout_seconds = Column(Integer, nullable=False, default=300)

    # Relationship — eagerly resolve model config
    model_config = relationship("ModelConfig", uselist=False, foreign_keys=[model_config_id])

    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    def __repr__(self) -> str:
        return f"<CustomTool id={self.id!r} name={self.name!r} type={self.tool_type!r}>"


class MigrationRun(Base):
    __tablename__ = "migration_runs"

    id = Column(String(64), primary_key=True, default=_uuid)
    project_id = Column(String(64), ForeignKey("migration_projects.id"), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="queued")
    # queued | running | paused | completed | failed | cancelled
    roadmap_steps = Column(JSON, nullable=False, default=list)
    # Each step: {index, title, description, category, recipe_id, status, priority,
    #             files_affected, result_summary, error, started_at, completed_at}
    current_step = Column(Integer, nullable=False, default=0)
    progress_pct = Column(Float, nullable=False, default=0.0)
    log = Column(JSON, nullable=False, default=list)
    result_summary = Column(Text, nullable=False, default="")
    artifacts = Column(JSON, nullable=False, default=dict)
    total_tokens_used = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_utcnow)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    project = relationship("MigrationProject", back_populates="migration_runs")

    def __repr__(self) -> str:
        return f"<MigrationRun id={self.id!r} status={self.status!r}>"
