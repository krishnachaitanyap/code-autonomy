/**
 * API client — typed fetch wrapper for the Code Autonomy REST API.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || '/api';

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const url = `${API_BASE}${path}`;
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  };

  const apiKey = process.env.NEXT_PUBLIC_API_KEY;
  if (apiKey) {
    headers['X-API-Key'] = apiKey;
  }

  const res = await fetch(url, { ...options, headers });

  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `API error: ${res.status}`);
  }

  return res.json();
}

// ---------------------------------------------------------------------------
// Repos
// ---------------------------------------------------------------------------

export interface Repo {
  id: string;
  url: string;
  local_path: string;
  platform: string;
  created_at: string;
  updated_at: string;
}

export interface DownstreamService {
  name: string;
  client_type: string;
  url: string;
  http_method?: string;
  auth_type?: string;
  files_referencing?: string[];
  confidence?: string;
  source_files?: string[];
  source_classes?: string[];
  invoking_endpoints?: ApiEndpointEntry[];
  regions?: string[];
}

export interface DataStore {
  type: string;
  entities: string[];
  url_pattern: string;
  source_files?: string[];
  source_classes?: string[];
  invoking_endpoints?: ApiEndpointEntry[];
}

export interface MessagingEntry {
  type: string;
  topic: string;
  group: string;
  direction: string;
  source_files?: string[];
  source_classes?: string[];
  invoking_endpoints?: ApiEndpointEntry[];
}

export interface ApiEndpointEntry {
  class: string;
  method: string;
  path: string;
  http_method: string;
  impacted_services?: string[];
  impacted_datastores?: string[];
  impacted_messaging?: string[];
}

export interface RepoDependencies {
  downstream_services: DownstreamService[];
  data_stores: DataStore[];
  messaging: MessagingEntry[];
  api_endpoints: ApiEndpointEntry[];
}

export interface IdentifiedDependencies {
  identified_services: DownstreamService[];
  search_terms_used: string[];
  prompt: string;
}

export const repos = {
  list: () => request<Repo[]>('/repos'),
  get: (id: string) => request<Repo>(`/repos/${id}`),
  create: (data: { url?: string; local_path?: string; platform?: string }) =>
    request<Repo>('/repos', { method: 'POST', body: JSON.stringify(data) }),
  delete: (id: string) => {
    const url = `${API_BASE}/repos/${id}`;
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    const apiKey = process.env.NEXT_PUBLIC_API_KEY;
    if (apiKey) headers['X-API-Key'] = apiKey;
    return fetch(url, { method: 'DELETE', headers }).then(res => {
      if (!res.ok) throw new Error(`Delete failed: ${res.status}`);
    });
  },
  getSkills: (id: string) =>
    request<{ content: string }>(`/repos/${id}/skills`),
  updateSkills: (id: string, content: string) =>
    request<{ content: string }>(`/repos/${id}/skills`, {
      method: 'PUT',
      body: JSON.stringify({ content }),
    }),
  symbols: (id: string, filePath?: string) =>
    request<any[]>(`/repos/${id}/symbols${filePath ? `?file_path=${filePath}` : ''}`),
  branches: (id: string) =>
    request<{ branches: string[] }>(`/repos/${id}/branches`),
  generateSkills: (id: string) =>
    request<{ content: string }>(`/repos/${id}/skills/generate`, { method: 'POST' }),
  getClaudeMd: (id: string) =>
    request<{ content: string }>(`/repos/${id}/claude-md`),
  updateClaudeMd: (id: string, content: string) =>
    request<{ content: string }>(`/repos/${id}/claude-md`, {
      method: 'PUT',
      body: JSON.stringify({ content }),
    }),
  generateClaudeMd: (id: string) =>
    request<{ content: string }>(`/repos/${id}/claude-md/generate`, { method: 'POST' }),
  getDependencies: (id: string) =>
    request<RepoDependencies>(`/repos/${id}/dependencies`),
  identifyDependencies: (id: string, prompt: string) =>
    request<IdentifiedDependencies>(`/repos/${id}/dependencies/identify`, {
      method: 'POST',
      body: JSON.stringify({ prompt }),
    }),
};

// ---------------------------------------------------------------------------
// Sessions
// ---------------------------------------------------------------------------

export interface Session {
  id: string;
  repo_id: string;
  mode: string;
  status: string;
  requirements: string;
  result_summary: string;
  turns_used: number;
  trace_id: string | null;
  log: Record<string, any>[];
  created_at: string;
  completed_at: string;
}

export const sessions = {
  list: (params?: { repo_id?: string; status?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.repo_id) qs.set('repo_id', params.repo_id);
    if (params?.status) qs.set('status', params.status);
    if (params?.limit) qs.set('limit', String(params.limit));
    const query = qs.toString() ? `?${qs}` : '';
    return request<{ sessions: Session[]; total: number }>(`/sessions${query}`);
  },
  get: (id: string) => request<Session>(`/sessions/${id}`),
  create: (data: { repo_id: string; mode: string; requirements: string; branch?: string; context?: Array<{role: string; content: string}> }) =>
    request<Session>('/sessions', { method: 'POST', body: JSON.stringify(data) }),
  cancel: (id: string) =>
    request<{ status: string }>(`/sessions/${id}/cancel`, { method: 'POST' }),
  resume: (id: string) =>
    request<Session>(`/sessions/${id}/resume`, { method: 'POST' }),
};

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

export const config = {
  get: () => request<{ config: Record<string, any> }>('/config'),
  update: (updates: Record<string, any>, profileName?: string) =>
    request<{ config: Record<string, any> }>('/config', {
      method: 'PUT',
      body: JSON.stringify({ updates, profile_name: profileName || 'default' }),
    }),
};

// ---------------------------------------------------------------------------
// Traces
// ---------------------------------------------------------------------------

export interface Trace {
  id: string;
  repo_id: string;
  model: string;
  success: boolean;
  turns_used: number;
  duration_s: number;
  total_tokens: number;
  summary: string;
  spans: any[];
  metrics: Record<string, any>;
  created_at: string;
}

export interface UsageStats {
  total_sessions: number;
  successful_sessions: number;
  failed_sessions: number;
  total_tokens: number;
  total_cost: number;
  total_duration_s: number;
  success_rate: number;
}

export const traces = {
  list: (params?: { repo_id?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.repo_id) qs.set('repo_id', params.repo_id);
    if (params?.limit) qs.set('limit', String(params.limit));
    const query = qs.toString() ? `?${qs}` : '';
    return request<{ traces: Trace[]; total: number }>(`/traces${query}`);
  },
  get: (id: string) => request<Trace>(`/traces/${id}`),
  stats: (repoId?: string) =>
    request<UsageStats>(`/traces/stats${repoId ? `?repo_id=${repoId}` : ''}`),
};

// ---------------------------------------------------------------------------
// Ask
// ---------------------------------------------------------------------------

export const ask = {
  question: (repoId: string, question: string) =>
    request<{ success: boolean; answer: string; sources: string[]; turns_used: number }>('/ask', {
      method: 'POST',
      body: JSON.stringify({ repo_id: repoId, question }),
    }),
};

// ---------------------------------------------------------------------------
// JIRA
// ---------------------------------------------------------------------------

export interface JiraRun {
  id: string;
  repo_id: string;
  status: string;
  agent_id: string | null;
  jira_project: string;
  total_stories: number;
  completed_stories: number;
  succeeded_stories: number;
  failed_stories: number;
  progress_pct: number;
  result_summary: string;
  artifacts: Record<string, any>;
  log: Record<string, any>[];
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export const jira = {
  // Sessions (legacy)
  start: (repoId: string) =>
    request<any>('/jira/sessions', {
      method: 'POST',
      body: JSON.stringify({ repo_id: repoId }),
    }),
  status: (repoId: string) => request<any>(`/jira/sessions/${repoId}`),

  // Runs (tracked JIRA-to-PR runs)
  listRuns: (params?: { repo_id?: string; status?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.repo_id) qs.set('repo_id', params.repo_id);
    if (params?.status) qs.set('status', params.status);
    if (params?.limit) qs.set('limit', String(params.limit));
    const query = qs.toString() ? `?${qs}` : '';
    return request<{ runs: JiraRun[]; total: number }>(`/jira/runs${query}`);
  },
  getRun: (id: string) => request<JiraRun>(`/jira/runs/${id}`),
  createRun: (data: { repo_id: string; jira_project?: string; branch?: string }) =>
    request<JiraRun>('/jira/runs', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  cancelRun: (id: string) =>
    request<{ status: string }>(`/jira/runs/${id}/cancel`, { method: 'POST' }),
  retryRun: (id: string) =>
    request<JiraRun>(`/jira/runs/${id}/retry`, { method: 'POST' }),
};

// ---------------------------------------------------------------------------
// Testing Platform
// ---------------------------------------------------------------------------

export interface TestProject {
  id: string;
  repo_id: string;
  name: string;
  repo_url: string;
  local_path: string;
  language: string;
  framework: string;
  testing_framework: string;
  branch: string;
  status: string;
  discovery_result: Record<string, any>;
  config: Record<string, any>;
  created_at: string;
  updated_at: string;
}

export interface TestRun {
  id: string;
  project_id: string;
  run_type: string;
  status: string;
  agent_id: string | null;
  target_scope: string;
  strategy: string;
  total_tests: number;
  passed_tests: number;
  failed_tests: number;
  skipped_tests: number;
  progress_pct: number;
  result_summary: string;
  artifacts: Record<string, any>;
  log: Record<string, any>[];
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface TestEvidence {
  id: string;
  test_run_id: string;
  evidence_type: string;
  title: string;
  content: string;
  file_path: string;
  metadata: Record<string, any>;
  created_at: string;
}

export interface CoverageReport {
  id: string;
  project_id: string;
  report_type: string;
  overall_pct: number;
  line_coverage: number;
  branch_coverage: number;
  function_coverage: number;
  uncovered_areas: Record<string, any>[];
  gaps: Record<string, any>[];
  details: Record<string, any>;
  created_at: string;
}

export interface StrategyBreakdown {
  strategy: string;
  display_name: string;
  test_file_count: number;
  test_files: string[];
  estimated_tests: number;
  run_count: number;
  total_tests: number;
  passed: number;
  failed: number;
  skipped: number;
  pass_rate: number;
  latest_run_status: string | null;
  latest_run_at: string | null;
  covered_endpoints: string[];
  covered_services: string[];
  coverage_pct: number;
}

export interface TestRunSummary {
  total_runs: number;
  total_estimated_tests: number;
  total_tests_executed: number;
  overall_pass_rate: number;
  strategies_executed: string[];
  strategies_missing: string[];
}

export interface CoverageDetails {
  total_endpoints: number;
  total_services: number;
  total_test_files: number;
  total_specifications: number;
  frameworks: string[];
  strategy_breakdown?: Record<string, StrategyBreakdown>;
  test_run_summary?: TestRunSummary;
  sonarqube?: Record<string, any>;
}

export interface DataInjectionConfig {
  id: string;
  project_id: string;
  name: string;
  strategy: string;
  target_entity: string;
  schema_definition: Record<string, any>;
  sample_data: Record<string, any>[];
  environment_rules: Record<string, any>;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface CustomStep {
  id: string;
  project_id: string;
  name: string;
  step_type: string;
  pattern: string;
  implementation: string;
  language: string;
  tags: string[];
  source: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ChatMessage {
  id: string;
  project_id: string;
  role: string;
  content: string;
  metadata: Record<string, any>;
  created_at: string;
}

export interface TestingStats {
  total_projects: number;
  total_runs: number;
  passed_runs: number;
  failed_runs: number;
  running_runs: number;
  success_rate: number;
  avg_coverage: number;
}

export interface ReferenceLearnResult {
  steps_learned: number;
  features_learned: number;
  maven_deps_found: number;
  patterns: {
    step_definitions: Array<{ step_type: string; pattern: string; implementation: string }>;
    feature_summaries: Array<{ file: string; content: string; scenario_count: number }>;
    maven_dependencies: Array<{ groupId: string; artifactId: string; version: string; scope: string }>;
  };
}

// ---------------------------------------------------------------------------
// Workflows (Goal-Driven Orchestration)
// ---------------------------------------------------------------------------

export interface WorkflowSubtask {
  index: number;
  title: string;
  description: string;
  type: string;
  status: string;
  checkpoint: boolean;
  requirements: string;
  result_summary: string;
  files_changed: string[];
  error: string | null;
  started_at: string | null;
  completed_at: string | null;
  attempts: number;
  model_used: string;
  tokens_used: number;
}

export interface Workflow {
  id: string;
  repo_id: string | null;
  project_id: string | null;
  goal: string;
  mode: string;
  status: string;
  subtasks: WorkflowSubtask[];
  current_step: number;
  progress_pct: number;
  result_summary: string;
  artifacts: Record<string, any>;
  log: Record<string, any>[];
  token_budget: number;
  total_tokens_used: number;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export const workflows = {
  list: (params?: { status?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.status) qs.set('status', params.status);
    if (params?.limit) qs.set('limit', String(params.limit));
    const query = qs.toString() ? `?${qs}` : '';
    return request<{ workflows: Workflow[]; total: number }>(`/workflows${query}`);
  },
  get: (id: string) => request<Workflow>(`/workflows/${id}`),
  create: (data: { repo_id?: string; project_id?: string; goal: string; mode?: string; branch?: string; token_budget?: number }) =>
    request<Workflow>('/workflows', { method: 'POST', body: JSON.stringify(data) }),
  resume: (id: string) => request<Workflow>(`/workflows/${id}/resume`, { method: 'POST' }),
  cancel: (id: string) => request<{ status: string }>(`/workflows/${id}/cancel`, { method: 'POST' }),
};

// ---------------------------------------------------------------------------
// Testing Platform
// ---------------------------------------------------------------------------

export const testing = {
  // Projects
  listProjects: (params?: { status?: string; repo_id?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.status) qs.set('status', params.status);
    if (params?.repo_id) qs.set('repo_id', params.repo_id);
    if (params?.limit) qs.set('limit', String(params.limit));
    const query = qs.toString() ? `?${qs}` : '';
    return request<{ projects: TestProject[]; total: number }>(`/testing/projects${query}`);
  },
  getProject: (id: string) => request<TestProject>(`/testing/projects/${id}`),
  createProject: (data: {
    name: string;
    repo_id?: string;
    repo_url?: string;
    local_path?: string;
    language?: string;
    framework?: string;
    testing_framework?: string;
    branch?: string;
    reference_repo_url?: string;
    reference_maven_deps?: string[];
  }) =>
    request<TestProject>('/testing/projects', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  discoverProject: (id: string) =>
    request<TestProject>(`/testing/projects/${id}/discover`, { method: 'POST' }),
  deleteProject: (id: string) =>
    request<void>(`/testing/projects/${id}`, { method: 'DELETE' }),
  learnReference: (projectId: string, data: {
    reference_repo_url: string;
    reference_branch?: string;
    maven_deps?: string[];
  }) =>
    request<ReferenceLearnResult>(`/testing/projects/${projectId}/learn-reference`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  // Runs
  listRuns: (params?: { project_id?: string; status?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.project_id) qs.set('project_id', params.project_id);
    if (params?.status) qs.set('status', params.status);
    if (params?.limit) qs.set('limit', String(params.limit));
    const query = qs.toString() ? `?${qs}` : '';
    return request<{ runs: TestRun[]; total: number }>(`/testing/runs${query}`);
  },
  getRun: (id: string) => request<TestRun>(`/testing/runs/${id}`),
  createRun: (data: {
    project_id: string;
    run_type?: string;
    target_scope?: string;
    strategy?: string;
    branch?: string;
  }) =>
    request<TestRun>('/testing/runs', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  cancelRun: (id: string) =>
    request<{ status: string }>(`/testing/runs/${id}/cancel`, { method: 'POST' }),
  retryRun: (id: string) =>
    request<TestRun>(`/testing/runs/${id}/retry`, { method: 'POST' }),
  listEvidences: (runId: string) =>
    request<TestEvidence[]>(`/testing/runs/${runId}/evidences`),

  // Coverage
  listCoverage: (projectId: string) =>
    request<CoverageReport[]>(`/testing/coverage/${projectId}`),
  analyzeCoverage: (projectId: string, branch?: string, sonarqubeProjectKey?: string) => {
    const qs = new URLSearchParams();
    if (branch) qs.set('branch', branch);
    if (sonarqubeProjectKey) qs.set('sonarqube_project_key', sonarqubeProjectKey);
    const query = qs.toString() ? `?${qs}` : '';
    return request<CoverageReport>(`/testing/coverage/${projectId}/analyze${query}`, { method: 'POST' });
  },

  // Data Injection
  listDataInjection: (projectId: string) =>
    request<DataInjectionConfig[]>(`/testing/data-injection/${projectId}`),
  createDataInjection: (data: {
    project_id: string;
    name: string;
    strategy?: string;
    target_entity?: string;
    schema_definition?: Record<string, any>;
    environment_rules?: Record<string, any>;
  }) =>
    request<DataInjectionConfig>('/testing/data-injection', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  deleteDataInjection: (id: string) =>
    request<void>(`/testing/data-injection/${id}`, { method: 'DELETE' }),
  generateSampleData: (id: string, count?: number) =>
    request<DataInjectionConfig>(`/testing/data-injection/${id}/generate-sample?count=${count || 5}`, {
      method: 'POST',
    }),

  // Custom Steps
  listCustomSteps: (projectId: string) =>
    request<CustomStep[]>(`/testing/custom-steps/${projectId}`),
  createCustomStep: (data: {
    project_id: string;
    name: string;
    step_type?: string;
    pattern?: string;
    implementation?: string;
    language?: string;
    tags?: string[];
  }) =>
    request<CustomStep>('/testing/custom-steps', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  deleteCustomStep: (id: string) =>
    request<void>(`/testing/custom-steps/${id}`, { method: 'DELETE' }),
  discoverCustomSteps: (projectId: string) =>
    request<CustomStep[]>(`/testing/custom-steps/${projectId}/discover`, { method: 'POST' }),

  // Chat
  chat: (projectId: string, message: string) =>
    request<{ reply: ChatMessage; context: Record<string, any> }>('/testing/chat', {
      method: 'POST',
      body: JSON.stringify({ project_id: projectId, message }),
    }),
  chatHistory: (projectId: string, limit?: number) =>
    request<ChatMessage[]>(`/testing/chat/${projectId}/history?limit=${limit || 50}`),

  // Stats
  stats: () => request<TestingStats>('/testing/stats'),
};

// ---------------------------------------------------------------------------
// Migration Platform
// ---------------------------------------------------------------------------

export interface DatabaseConnectionConfig {
  engine: string;     // postgresql | mysql | oracle | sqlserver
  host: string;
  port: string;
  database: string;
  schema?: string;
  jdbc_url?: string;
  username?: string;
}

export interface MigrationProject {
  id: string;
  repo_id: string;
  name: string;
  migration_mode: string; // "migration" | "improvement" | "database"
  source_repo_url: string;
  source_local_path: string;
  source_branch: string;
  reference_repo_url: string;
  reference_local_path: string;
  reference_branch: string;
  reference_folders: string[];
  status: string;
  source_profile: Record<string, any>;
  reference_profile: Record<string, any>;
  gap_analysis: Record<string, any>;
  improvement_analysis: Record<string, any>;
  capacity_current: Record<string, any>;
  capacity_target: Record<string, any>;
  selected_recipes: string[];
  config: Record<string, any>;
  created_at: string;
  updated_at: string;
}

export interface MigrationRecipe {
  id: string;
  name: string;
  category: string;
  description: string;
  priority: number;
  tags: string[];
  prerequisites: string[];
  agent_instructions: string;
}

export interface MigrationRoadmapStep {
  index: number;
  title: string;
  description: string;
  category: string;
  recipe_id: string;
  status: string;
  priority: number;
  files_affected: string[];
  result_summary: string;
  error: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface MigrationRun {
  id: string;
  project_id: string;
  status: string;
  roadmap_steps: MigrationRoadmapStep[];
  current_step: number;
  progress_pct: number;
  log: Record<string, any>[];
  result_summary: string;
  artifacts: Record<string, any>;
  total_tokens_used: number;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface MigrationStats {
  total_projects: number;
  analyzed_projects: number;
  total_runs: number;
  completed_runs: number;
  running_runs: number;
  failed_runs: number;
}

export const migrations = {
  // Projects
  listProjects: (params?: { status?: string; repo_id?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.status) qs.set('status', params.status);
    if (params?.repo_id) qs.set('repo_id', params.repo_id);
    if (params?.limit) qs.set('limit', String(params.limit));
    const query = qs.toString() ? `?${qs}` : '';
    return request<{ projects: MigrationProject[]; total: number }>(`/migrations/projects${query}`);
  },
  getProject: (id: string) => request<MigrationProject>(`/migrations/projects/${id}`),
  createProject: (data: {
    name: string;
    migration_mode?: string;
    source_repo_url?: string;
    source_local_path?: string;
    source_branch?: string;
    reference_repo_url?: string;
    reference_local_path?: string;
    reference_branch?: string;
    reference_folders?: string[];
    config?: Record<string, any>;
    source_db?: DatabaseConnectionConfig;
    destination_db?: DatabaseConnectionConfig;
  }) =>
    request<MigrationProject>('/migrations/projects', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  deleteProject: (id: string) =>
    request<void>(`/migrations/projects/${id}`, { method: 'DELETE' }),
  analyzeProject: (id: string) =>
    request<MigrationProject>(`/migrations/projects/${id}/analyze`, { method: 'POST' }),
  testConnection: (projectId: string, target: 'source' | 'destination') =>
    request<{ status: string; target: string; message: string }>(
      `/migrations/projects/${projectId}/test-connection?target=${target}`,
      { method: 'POST' },
    ),

  // Capacity
  updateCapacityTarget: (id: string, capacity_target: Record<string, any>) =>
    request<MigrationProject>(`/migrations/projects/${id}/capacity`, {
      method: 'PUT',
      body: JSON.stringify({ capacity_target }),
    }),

  // Recipes
  listRecipes: () => request<MigrationRecipe[]>('/migrations/recipes'),
  getRecommendedRecipes: (projectId: string) =>
    request<MigrationRecipe[]>(`/migrations/projects/${projectId}/recipes`),
  setSelectedRecipes: (projectId: string, recipe_ids: string[]) =>
    request<MigrationProject>(`/migrations/projects/${projectId}/recipes`, {
      method: 'PUT',
      body: JSON.stringify({ recipe_ids }),
    }),

  // Roadmap
  generateRoadmap: (projectId: string) =>
    request<MigrationRun>(`/migrations/projects/${projectId}/roadmap`, { method: 'POST' }),

  // Runs
  listRuns: (params?: { project_id?: string; status?: string; limit?: number }) => {
    const qs = new URLSearchParams();
    if (params?.project_id) qs.set('project_id', params.project_id);
    if (params?.status) qs.set('status', params.status);
    if (params?.limit) qs.set('limit', String(params.limit));
    const query = qs.toString() ? `?${qs}` : '';
    return request<{ runs: MigrationRun[]; total: number }>(`/migrations/runs${query}`);
  },
  getRun: (id: string) => request<MigrationRun>(`/migrations/runs/${id}`),
  executeRun: (id: string) =>
    request<MigrationRun>(`/migrations/runs/${id}/execute`, { method: 'POST' }),
  executeStep: (runId: string, stepIndex: number) =>
    request<MigrationRun>(`/migrations/runs/${runId}/execute-step?step_index=${stepIndex}`, {
      method: 'POST',
    }),
  cancelRun: (id: string) =>
    request<{ status: string }>(`/migrations/runs/${id}/cancel`, { method: 'POST' }),

  // Stats
  stats: () => request<MigrationStats>('/migrations/stats'),
};
