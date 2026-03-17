"""
Pydantic request/response models for the API layer.
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Repos
# ---------------------------------------------------------------------------

class RepoCreate(BaseModel):
    url: str = ""
    local_path: str = ""
    platform: str = "local"


class RepoResponse(BaseModel):
    id: str
    url: str
    local_path: str
    platform: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SymbolResponse(BaseModel):
    fqn: str = ""
    name: str = ""
    file_path: str = ""
    symbol_type: str = ""
    line_start: int = 0
    line_end: int = 0
    signature: str = ""
    parent_class: str = ""


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

class SessionCreate(BaseModel):
    repo_id: str
    mode: str = "agent"  # agent | plan | ask
    requirements: str = ""
    branch: str = ""  # empty = use current/default branch
    config_overrides: dict = Field(default_factory=dict)
    context: list[dict] = Field(default_factory=list)


class SessionResponse(BaseModel):
    id: str
    repo_id: str
    mode: str
    status: str
    requirements: str = ""
    result_summary: str = ""
    turns_used: int = 0
    trace_id: Optional[str] = None
    log: list[dict] = Field(default_factory=list)
    created_at: Optional[str] = None
    completed_at: Optional[str] = None


class SessionListResponse(BaseModel):
    sessions: list[SessionResponse]
    total: int


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

class ConfigResponse(BaseModel):
    config: dict


class ConfigUpdate(BaseModel):
    updates: dict
    profile_name: str = "default"


# ---------------------------------------------------------------------------
# Traces
# ---------------------------------------------------------------------------

class TraceResponse(BaseModel):
    id: str
    repo_id: str = ""
    session_id: Optional[str] = None
    model: str = ""
    success: bool = False
    turns_used: int = 0
    duration_s: float = 0.0
    total_tokens: int = 0
    total_cost: float = 0.0
    files_changed: list[str] = Field(default_factory=list)
    summary: str = ""
    spans: list[dict] = Field(default_factory=list)
    metrics: dict = Field(default_factory=dict)
    created_at: Optional[str] = None


class TraceListResponse(BaseModel):
    traces: list[TraceResponse]
    total: int


class UsageStatsResponse(BaseModel):
    total_sessions: int = 0
    successful_sessions: int = 0
    failed_sessions: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    total_duration_s: float = 0.0
    success_rate: float = 0.0


# ---------------------------------------------------------------------------
# Ask
# ---------------------------------------------------------------------------

class AskRequest(BaseModel):
    repo_id: str
    question: str


class AskResponse(BaseModel):
    success: bool
    answer: str = ""
    sources: list[str] = Field(default_factory=list)
    turns_used: int = 0


# ---------------------------------------------------------------------------
# JIRA
# ---------------------------------------------------------------------------

class JiraSessionCreate(BaseModel):
    repo_id: str
    repo_path: str = ""


class JiraSessionResponse(BaseModel):
    repo_id: str
    stories: list[dict] = Field(default_factory=list)
    total: int = 0
    completed: int = 0
    succeeded: int = 0
    pending: int = 0
    created_at: Optional[str] = None
    message: str = ""


# ---------------------------------------------------------------------------
# JIRA Runs — tracked JIRA-to-PR generation runs
# ---------------------------------------------------------------------------

class JiraRunCreate(BaseModel):
    repo_id: str
    jira_project: str = ""
    branch: str = ""

class JiraRunResponse(BaseModel):
    id: str
    repo_id: str
    status: str = "queued"
    agent_id: Optional[str] = None
    jira_project: str = ""
    total_stories: int = 0
    completed_stories: int = 0
    succeeded_stories: int = 0
    failed_stories: int = 0
    progress_pct: float = 0.0
    result_summary: str = ""
    artifacts: dict = Field(default_factory=dict)
    log: list[dict] = Field(default_factory=list)
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None

class JiraRunListResponse(BaseModel):
    runs: list[JiraRunResponse]
    total: int


# ---------------------------------------------------------------------------
# WebSocket messages
# ---------------------------------------------------------------------------

class WSMessage(BaseModel):
    type: str  # turn | llm_response | file_changed | complete | error
    data: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Testing Platform — TestProject
# ---------------------------------------------------------------------------

class TestProjectCreate(BaseModel):
    name: str
    repo_id: str = ""
    repo_url: str = ""
    local_path: str = ""
    language: str = "auto"
    framework: str = "auto"
    testing_framework: str = "auto"
    branch: str = "main"
    config: dict = Field(default_factory=dict)
    reference_repo_url: str = ""
    reference_maven_deps: list[str] = Field(default_factory=list)


class TestProjectResponse(BaseModel):
    id: str
    repo_id: str
    name: str
    repo_url: str = ""
    local_path: str = ""
    language: str = "auto"
    framework: str = "auto"
    testing_framework: str = "auto"
    branch: str = "main"
    status: str = "pending"
    discovery_result: dict = Field(default_factory=dict)
    config: dict = Field(default_factory=dict)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class TestProjectListResponse(BaseModel):
    projects: list[TestProjectResponse]
    total: int


# ---------------------------------------------------------------------------
# Testing Platform — Reference Repo Learning
# ---------------------------------------------------------------------------

class ReferenceRepoLearn(BaseModel):
    reference_repo_url: str
    reference_branch: str = "main"
    maven_deps: list[str] = Field(default_factory=list)


class ReferenceLearnResponse(BaseModel):
    steps_learned: int = 0
    features_learned: int = 0
    maven_deps_found: int = 0
    patterns: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Testing Platform — TestRun
# ---------------------------------------------------------------------------

class TestRunCreate(BaseModel):
    project_id: str
    run_type: str = "functional"
    target_scope: str = ""
    strategy: str = "auto"
    config: dict = Field(default_factory=dict)
    branch: str = ""


class TestRunResponse(BaseModel):
    id: str
    project_id: str
    run_type: str = "functional"
    status: str = "queued"
    agent_id: Optional[str] = None
    target_scope: str = ""
    strategy: str = "auto"
    total_tests: int = 0
    passed_tests: int = 0
    failed_tests: int = 0
    skipped_tests: int = 0
    progress_pct: float = 0.0
    result_summary: str = ""
    artifacts: dict = Field(default_factory=dict)
    log: list[dict] = Field(default_factory=list)
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class TestRunListResponse(BaseModel):
    runs: list[TestRunResponse]
    total: int


# ---------------------------------------------------------------------------
# Testing Platform — TestEvidence
# ---------------------------------------------------------------------------

class TestEvidenceResponse(BaseModel):
    id: str
    test_run_id: str
    evidence_type: str = "log"
    title: str = ""
    content: str = ""
    file_path: str = ""
    metadata: dict = Field(default_factory=dict)
    created_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Testing Platform — CoverageReport
# ---------------------------------------------------------------------------

class CoverageReportResponse(BaseModel):
    id: str
    project_id: str
    report_type: str = "code"
    overall_pct: float = 0.0
    line_coverage: float = 0.0
    branch_coverage: float = 0.0
    function_coverage: float = 0.0
    uncovered_areas: list[dict] = Field(default_factory=list)
    gaps: list[dict] = Field(default_factory=list)
    details: dict = Field(default_factory=dict)
    created_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Testing Platform — DataInjectionConfig
# ---------------------------------------------------------------------------

class DataInjectionConfigCreate(BaseModel):
    project_id: str
    name: str
    strategy: str = "synthetic"
    target_entity: str = ""
    schema_definition: dict = Field(default_factory=dict)
    sample_data: list[dict] = Field(default_factory=list)
    environment_rules: dict = Field(default_factory=dict)


class DataInjectionConfigResponse(BaseModel):
    id: str
    project_id: str
    name: str
    strategy: str = "synthetic"
    target_entity: str = ""
    schema_definition: dict = Field(default_factory=dict)
    sample_data: list[dict] = Field(default_factory=list)
    environment_rules: dict = Field(default_factory=dict)
    is_active: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Testing Platform — CustomStep
# ---------------------------------------------------------------------------

class CustomStepCreate(BaseModel):
    project_id: str
    name: str
    step_type: str = "given"
    pattern: str = ""
    implementation: str = ""
    language: str = "java"
    tags: list[str] = Field(default_factory=list)


class CustomStepResponse(BaseModel):
    id: str
    project_id: str
    name: str
    step_type: str = "given"
    pattern: str = ""
    implementation: str = ""
    language: str = "java"
    tags: list[str] = Field(default_factory=list)
    source: str = "user"
    is_active: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Testing Platform — Chat
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    project_id: str
    message: str


class ChatMessageResponse(BaseModel):
    id: str
    project_id: str
    role: str = "user"
    content: str = ""
    metadata: dict = Field(default_factory=dict)
    created_at: Optional[str] = None


class ChatResponse(BaseModel):
    reply: ChatMessageResponse
    context: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Workflows (Goal-Driven Orchestration)
# ---------------------------------------------------------------------------

class WorkflowCreate(BaseModel):
    repo_id: str = ""
    project_id: str = ""
    goal: str
    mode: str = "testing"  # testing | engineering
    branch: str = ""
    token_budget: int = 0  # 0 = unlimited


class SubtaskSchema(BaseModel):
    index: int
    title: str
    description: str
    type: str = "agent"
    status: str = "pending"
    checkpoint: bool = False
    requirements: str = ""
    result_summary: str = ""
    files_changed: list[str] = Field(default_factory=list)
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    attempts: int = 1
    model_used: str = ""
    tokens_used: int = 0


class WorkflowResponse(BaseModel):
    id: str
    repo_id: Optional[str] = None
    project_id: Optional[str] = None
    goal: str
    mode: str
    status: str
    subtasks: list[SubtaskSchema] = Field(default_factory=list)
    current_step: int = 0
    progress_pct: float = 0.0
    result_summary: str = ""
    artifacts: dict = Field(default_factory=dict)
    log: list[dict] = Field(default_factory=list)
    token_budget: int = 0
    total_tokens_used: int = 0
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class WorkflowListResponse(BaseModel):
    workflows: list[WorkflowResponse]
    total: int


# ---------------------------------------------------------------------------
# Migration Platform
# ---------------------------------------------------------------------------

class MigrationProjectCreate(BaseModel):
    name: str
    migration_mode: str = "migration"  # migration | improvement | database
    source_repo_url: str = ""
    source_local_path: str = ""
    source_branch: str = "main"
    reference_repo_url: str = ""
    reference_local_path: str = ""
    reference_branch: str = "main"
    reference_folders: list[str] = Field(default_factory=list)
    config: dict = Field(default_factory=dict)
    source_db: Optional[dict] = None
    destination_db: Optional[dict] = None


class MigrationProjectResponse(BaseModel):
    id: str
    repo_id: str
    name: str
    migration_mode: str = "migration"
    source_repo_url: str = ""
    source_local_path: str = ""
    source_branch: str = "main"
    reference_repo_url: str = ""
    reference_local_path: str = ""
    reference_branch: str = "main"
    reference_folders: list[str] = Field(default_factory=list)
    status: str = "pending"
    source_profile: dict = Field(default_factory=dict)
    reference_profile: dict = Field(default_factory=dict)
    gap_analysis: dict = Field(default_factory=dict)
    improvement_analysis: dict = Field(default_factory=dict)
    capacity_current: dict = Field(default_factory=dict)
    capacity_target: dict = Field(default_factory=dict)
    selected_recipes: list[str] = Field(default_factory=list)
    config: dict = Field(default_factory=dict)
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class MigrationProjectListResponse(BaseModel):
    projects: list[MigrationProjectResponse]
    total: int


class MigrationRecipeResponse(BaseModel):
    id: str
    name: str
    category: str
    description: str
    priority: int
    tags: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    agent_instructions: str = ""
    tool_ids: list[str] = Field(default_factory=list)
    is_custom: bool = False


class MigrationRoadmapStep(BaseModel):
    index: int
    title: str
    description: str
    category: str
    recipe_id: str
    status: str = "pending"
    priority: int = 0
    files_affected: list[str] = Field(default_factory=list)
    result_summary: str = ""
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class MigrationRunResponse(BaseModel):
    id: str
    project_id: str
    status: str = "queued"
    roadmap_steps: list[dict] = Field(default_factory=list)
    current_step: int = 0
    progress_pct: float = 0.0
    log: list[dict] = Field(default_factory=list)
    result_summary: str = ""
    artifacts: dict = Field(default_factory=dict)
    total_tokens_used: int = 0
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class MigrationRunListResponse(BaseModel):
    runs: list[MigrationRunResponse]
    total: int


class CapacityTargetUpdate(BaseModel):
    capacity_target: dict


class RecipeSelectionRequest(BaseModel):
    recipe_ids: list[str]


class CustomRecipeCreate(BaseModel):
    name: str
    category: str = "custom"
    description: str = ""
    priority: int = 50
    tags: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    agent_instructions: str = ""
    source_framework: str = ""
    target_framework: str = ""
    tool_ids: list[str] = Field(default_factory=list)


class CustomRecipeUpdate(BaseModel):
    name: str | None = None
    category: str | None = None
    description: str | None = None
    priority: int | None = None
    tags: list[str] | None = None
    prerequisites: list[str] | None = None
    agent_instructions: str | None = None
    source_framework: str | None = None
    target_framework: str | None = None
    tool_ids: list[str] | None = None


class CustomRecipeResponse(BaseModel):
    id: str
    name: str
    category: str
    description: str
    priority: int
    tags: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    agent_instructions: str = ""
    source_framework: str = ""
    target_framework: str = ""
    tool_ids: list[str] = Field(default_factory=list)
    is_custom: bool = True


# ---------------------------------------------------------------------------
# Custom Tools — user-defined agent tools for migration, chat, testing
# ---------------------------------------------------------------------------

class CustomToolCreate(BaseModel):
    name: str
    description: str = ""
    tool_type: str = "agent"  # agent | validator | transformer | analyzer
    enabled_for_migration: bool = False
    enabled_for_chat: bool = False
    enabled_for_testing: bool = False
    agent_instructions: str = ""
    goal: str = ""
    allowed_tools: list[str] = Field(default_factory=list)
    parameters: dict = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    max_turns: int = 20
    model: str = ""
    timeout_seconds: int = 300


class CustomToolUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    tool_type: str | None = None
    enabled_for_migration: bool | None = None
    enabled_for_chat: bool | None = None
    enabled_for_testing: bool | None = None
    agent_instructions: str | None = None
    goal: str | None = None
    allowed_tools: list[str] | None = None
    parameters: dict | None = None
    tags: list[str] | None = None
    prerequisites: list[str] | None = None
    max_turns: int | None = None
    model: str | None = None
    timeout_seconds: int | None = None
    is_active: bool | None = None


class CustomToolResponse(BaseModel):
    id: str
    name: str
    description: str = ""
    tool_type: str = "agent"
    enabled_for_migration: bool = False
    enabled_for_chat: bool = False
    enabled_for_testing: bool = False
    agent_instructions: str = ""
    goal: str = ""
    allowed_tools: list[str] = Field(default_factory=list)
    parameters: dict = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    max_turns: int = 20
    model: str = ""
    timeout_seconds: int = 300
    is_active: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class CustomToolListResponse(BaseModel):
    tools: list[CustomToolResponse]
    total: int
