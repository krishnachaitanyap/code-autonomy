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
    config_overrides: dict = Field(default_factory=dict)


class SessionResponse(BaseModel):
    id: str
    repo_id: str
    mode: str
    status: str
    requirements: str = ""
    result_summary: str = ""
    turns_used: int = 0
    trace_id: Optional[str] = None
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
    repo_url: str = ""
    local_path: str = ""
    language: str = "auto"
    framework: str = "auto"
    testing_framework: str = "auto"
    branch: str = "main"
    config: dict = Field(default_factory=dict)


class TestProjectResponse(BaseModel):
    id: str
    repo_id: Optional[str] = None
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
# Testing Platform — TestRun
# ---------------------------------------------------------------------------

class TestRunCreate(BaseModel):
    project_id: str
    run_type: str = "functional"
    target_scope: str = ""
    strategy: str = "auto"
    config: dict = Field(default_factory=dict)


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
