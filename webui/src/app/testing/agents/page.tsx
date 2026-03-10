'use client';

import { Suspense, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import {
  testing, jira, repos, workflows as workflowsApi,
  type TestRun, type TestProject, type TestEvidence, type JiraRun, type Repo,
  type ReferenceLearnResult, type Workflow, type WorkflowSubtask,
} from '@/lib/api';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type RunKind = 'test' | 'jira' | 'workflow';
type RunFilter = 'all' | 'test' | 'jira' | 'workflow';
type DetailTab = 'activity' | 'evidence' | 'artifacts';

type LogEntry = {
  timestamp: string;
  stage: string;
  detail: string;
  progress: number;
};

/** Unified run — wraps both TestRun and JiraRun for the UI. */
type UnifiedRun = {
  kind: RunKind;
  id: string;
  status: string;
  progress_pct: number;
  log: LogEntry[];
  result_summary: string;
  artifacts: Record<string, any>;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  agent_id: string | null;
  // Test-specific
  project_id?: string;
  run_type?: string;
  strategy?: string;
  total_tests?: number;
  passed_tests?: number;
  failed_tests?: number;
  skipped_tests?: number;
  target_scope?: string;
  // JIRA-specific
  repo_id?: string;
  jira_project?: string;
  total_stories?: number;
  completed_stories?: number;
  succeeded_stories?: number;
  failed_stories?: number;
  // Workflow-specific
  goal?: string;
  mode?: string;
  subtasks?: WorkflowSubtask[];
  current_step?: number;
  token_budget?: number;
  total_tokens_used?: number;
};

function testToUnified(r: TestRun): UnifiedRun {
  return {
    kind: 'test', id: r.id, status: r.status, progress_pct: r.progress_pct,
    log: r.log as LogEntry[], result_summary: r.result_summary, artifacts: r.artifacts,
    created_at: r.created_at, started_at: r.started_at, completed_at: r.completed_at,
    agent_id: r.agent_id, project_id: r.project_id, run_type: r.run_type,
    strategy: r.strategy, total_tests: r.total_tests, passed_tests: r.passed_tests,
    failed_tests: r.failed_tests, skipped_tests: r.skipped_tests, target_scope: r.target_scope,
  };
}

function jiraToUnified(r: JiraRun): UnifiedRun {
  return {
    kind: 'jira', id: r.id, status: r.status, progress_pct: r.progress_pct,
    log: r.log as LogEntry[], result_summary: r.result_summary, artifacts: r.artifacts,
    created_at: r.created_at, started_at: r.started_at, completed_at: r.completed_at,
    agent_id: r.agent_id, repo_id: r.repo_id, jira_project: r.jira_project,
    total_stories: r.total_stories, completed_stories: r.completed_stories,
    succeeded_stories: r.succeeded_stories, failed_stories: r.failed_stories,
  };
}

function workflowToUnified(w: Workflow): UnifiedRun {
  // Convert workflow log to LogEntry format
  const log: LogEntry[] = (w.log || []).map((entry: any) => ({
    timestamp: entry.timestamp || '',
    stage: entry.event || 'info',
    detail: entry.message || '',
    progress: 0,
  }));
  return {
    kind: 'workflow', id: w.id, status: w.status, progress_pct: w.progress_pct,
    log, result_summary: w.result_summary, artifacts: w.artifacts || {},
    created_at: w.created_at, started_at: w.started_at, completed_at: w.completed_at,
    agent_id: null, goal: w.goal, mode: w.mode, subtasks: w.subtasks,
    current_step: w.current_step, project_id: w.project_id || undefined,
    repo_id: w.repo_id || undefined,
    token_budget: w.token_budget, total_tokens_used: w.total_tokens_used,
  };
}

function subtaskStatusIcon(status: string): string {
  if (status === 'completed') return '\u2713';
  if (status === 'running') return '\u25b8';
  if (status === 'failed') return '\u2717';
  if (status === 'skipped') return '\u2014';
  return '\u25cb';
}

function subtaskStatusColor(status: string): string {
  if (status === 'completed') return 'text-green-500';
  if (status === 'running') return 'text-blue-500';
  if (status === 'failed') return 'text-red-500';
  if (status === 'skipped') return 'text-gray-400';
  return 'text-gray-400';
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch { return ''; }
}

function stageIcon(stage: string): string {
  if (stage === 'tool_call') return '\u25b8';
  if (stage === 'error' || stage === 'story_error') return '\u2717';
  if (['complete', 'result', 'story_success', 'story_pr', 'subtask_complete', 'workflow_complete'].includes(stage) || stage.startsWith('discovery_result')) return '\u2713';
  if (stage === 'story_branch' || stage === 'subtask_start') return '\u25b8';
  if (stage === 'checkpoint') return '\u23f8';
  if (stage === 'retry') return '\u21bb';
  if (stage === 'budget_exceeded') return '\u26a0';
  if (stage === 'error_classification') return '\u26a0';
  if (stage === 'error_suggestion') return '\u{1F4A1}';
  return '$';
}

function stageColor(stage: string): string {
  if (stage === 'tool_call' || stage === 'story_branch') return 'text-yellow-400';
  if (stage === 'error' || stage === 'story_error') return 'text-red-400';
  if (['complete', 'result', 'story_success', 'workflow_complete'].includes(stage)) return 'text-green-400';
  if (stage === 'story_pr') return 'text-blue-400';
  if (stage.startsWith('discovery_result')) return 'text-green-400';
  if (stage === 'test_output') return 'text-gray-300';
  if (stage === 'subtask_start') return 'text-teal-400';
  if (stage === 'subtask_complete') return 'text-green-400';
  if (stage === 'checkpoint') return 'text-amber-400';
  if (stage === 'retry') return 'text-orange-400';
  if (stage === 'budget_exceeded') return 'text-red-400';
  if (stage === 'error_classification') return 'text-orange-300';
  if (stage === 'error_suggestion') return 'text-amber-300';
  return 'text-cyan-400';
}

function isStageHeader(stage: string): boolean {
  return [
    'initializing', 'resolving_repo', 'discovery', 'building_requirements',
    'generating_tests', 'executing_tests', 'parsing_results',
    'recording_evidence', 'complete', 'error',
    // JIRA stages
    'authenticating', 'fetching_stories', 'analyzing_codebase',
    'processing_story', 'finalizing', 'story_start',
    // Workflow stages
    'subtask_start', 'subtask_complete', 'checkpoint', 'workflow_complete',
    'retry', 'budget_exceeded',
    // Error classification stages
    'error_classification', 'error_suggestion',
  ].includes(stage);
}

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

export default function AgentsPageWrapper() {
  return (
    <Suspense fallback={<div className="flex items-center justify-center min-h-[60vh]"><div className="w-6 h-6 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin" /></div>}>
      <AgentsPage />
    </Suspense>
  );
}

function AgentsPage() {
  const searchParams = useSearchParams();
  const projectFilter = searchParams.get('project') || '';

  const [runs, setRuns] = useState<UnifiedRun[]>([]);
  const [projects, setProjects] = useState<TestProject[]>([]);
  const [repoList, setRepoList] = useState<Repo[]>([]);
  const [selectedRun, setSelectedRun] = useState<UnifiedRun | null>(null);
  const [evidences, setEvidences] = useState<TestEvidence[]>([]);
  const [loading, setLoading] = useState(true);
  const [showNewRun, setShowNewRun] = useState(false);
  const [activeTab, setActiveTab] = useState<DetailTab>('activity');
  const [runFilter, setRunFilter] = useState<RunFilter>('all');

  // New run form
  const [newRunKind, setNewRunKind] = useState<RunKind>('test');
  const [newTestRun, setNewTestRun] = useState({
    project_id: projectFilter,
    run_type: 'functional',
    strategy: 'auto',
    target_scope: '',
  });
  const [newJiraRun, setNewJiraRun] = useState({ repo_id: '', jira_project: '' });
  const [newWorkflow, setNewWorkflow] = useState({ goal: '', project_id: projectFilter, mode: 'testing' as 'testing' | 'engineering', token_budget: 0 });

  // Branch selector state
  const [branch, setBranch] = useState('main');
  const [branchList, setBranchList] = useState<string[]>([]);
  const [loadingBranches, setLoadingBranches] = useState(false);

  // Reference repo learning state
  const [showRefRepo, setShowRefRepo] = useState(false);
  const [refRepoUrl, setRefRepoUrl] = useState('');
  const [refRepoBranch, setRefRepoBranch] = useState('main');
  const [refMavenDeps, setRefMavenDeps] = useState('');
  const [learningRef, setLearningRef] = useState(false);
  const [refLearnResult, setRefLearnResult] = useState<ReferenceLearnResult | null>(null);

  const terminalRef = useRef<HTMLDivElement>(null);

  // Load branches when project/repo selection changes
  useEffect(() => {
    const selectedId = newRunKind === 'test' ? newTestRun.project_id : newRunKind === 'workflow' ? newWorkflow.project_id : newJiraRun.repo_id;
    if (!selectedId) {
      setBranchList([]);
      setBranch('main');
      return;
    }
    // Find repo ID: check repos first, then match via projects
    let repoId = repoList.find((r) => r.id === selectedId)?.id;
    if (!repoId) {
      const proj = projects.find((p) => p.id === selectedId);
      if (proj) {
        const matchedRepo = repoList.find((r) => r.url === proj.repo_url);
        repoId = matchedRepo?.id;
      }
    }
    if (!repoId) {
      // selectedId might be a repo_id directly (from repos in the dropdown)
      repoId = selectedId;
    }
    setBranchList([]);
    setBranch('main');
    setLoadingBranches(true);
    repos.branches(repoId)
      .then((r) => {
        const list = r.branches || [];
        setBranchList(list);
        if (list.length > 0) {
          setBranch(list.includes('main') ? 'main' : list[0]);
        }
      })
      .catch(() => {
        setBranchList([]);
        setBranch('main');
      })
      .finally(() => setLoadingBranches(false));
  }, [newTestRun.project_id, newJiraRun.repo_id, newWorkflow.project_id, newRunKind, repoList, projects]);

  // Load initial data
  useEffect(() => { loadData(); }, [projectFilter]);

  // Polling: refresh selected run every 2s while running/paused(workflow)
  useEffect(() => {
    const shouldPoll = selectedRun && (
      selectedRun.status === 'running' ||
      (selectedRun.kind === 'workflow' && selectedRun.status === 'paused')
    );
    if (!shouldPoll || !selectedRun) return;

    const interval = setInterval(async () => {
      try {
        let fresh: UnifiedRun;
        if (selectedRun.kind === 'test') {
          fresh = testToUnified(await testing.getRun(selectedRun.id));
        } else if (selectedRun.kind === 'workflow') {
          fresh = workflowToUnified(await workflowsApi.get(selectedRun.id));
        } else {
          fresh = jiraToUnified(await jira.getRun(selectedRun.id));
        }
        setSelectedRun(fresh);

        // Refresh runs list
        await loadRunsList();

        // If complete, fetch evidences for test runs
        if (fresh.status !== 'running' && fresh.kind === 'test') {
          const ev = await testing.listEvidences(fresh.id);
          setEvidences(ev);
        }
      } catch { /* ignore */ }
    }, 2000);

    return () => clearInterval(interval);
  }, [selectedRun?.id, selectedRun?.status]);

  // Auto-scroll terminal
  useEffect(() => {
    if (terminalRef.current && activeTab === 'activity') {
      terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
    }
  }, [selectedRun?.log, activeTab]);

  async function loadRunsList() {
    const [testResult, jiraResult, wfResult] = await Promise.all([
      testing.listRuns({ project_id: projectFilter || undefined, limit: 50 }),
      jira.listRuns({ limit: 50 }),
      workflowsApi.list({ limit: 50 }),
    ]);
    const merged = [
      ...testResult.runs.map(testToUnified),
      ...jiraResult.runs.map(jiraToUnified),
      ...wfResult.workflows.map(workflowToUnified),
    ].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
    setRuns(merged);
  }

  async function loadData() {
    setLoading(true);
    try {
      const [testResult, jiraResult, wfResult, p] = await Promise.all([
        testing.listRuns({ project_id: projectFilter || undefined, limit: 50 }),
        jira.listRuns({ limit: 50 }),
        workflowsApi.list({ limit: 50 }),
        testing.listProjects({ limit: 100 }),
      ]);
      const merged = [
        ...testResult.runs.map(testToUnified),
        ...jiraResult.runs.map(jiraToUnified),
        ...wfResult.workflows.map(workflowToUnified),
      ].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
      setRuns(merged);
      setProjects(p.projects);

      // Load repos for JIRA run form
      try {
        const r = await repos.list();
        setRepoList(Array.isArray(r) ? r : []);
      } catch { /* repos API may not have the list */ }
    } catch (err) {
      console.error('Failed to load runs:', err);
    } finally {
      setLoading(false);
    }
  }

  async function handleSelectRun(run: UnifiedRun) {
    // For workflows, fetch fresh data to get subtasks
    if (run.kind === 'workflow') {
      try {
        const fresh = workflowToUnified(await workflowsApi.get(run.id));
        setSelectedRun(fresh);
      } catch {
        setSelectedRun(run);
      }
    } else {
      setSelectedRun(run);
    }
    setActiveTab('activity');
    if (run.kind === 'test') {
      try {
        const ev = await testing.listEvidences(run.id);
        setEvidences(ev);
      } catch { setEvidences([]); }
    } else {
      setEvidences([]);
    }
  }

  async function handleCreateRun(e: React.FormEvent) {
    e.preventDefault();
    try {
      let created: UnifiedRun;
      if (newRunKind === 'test') {
        const r = await testing.createRun({ ...newTestRun, branch });
        created = testToUnified(r);
      } else if (newRunKind === 'workflow') {
        const r = await workflowsApi.create({
          goal: newWorkflow.goal,
          project_id: newWorkflow.project_id,
          mode: newWorkflow.mode,
          branch,
          token_budget: newWorkflow.token_budget || undefined,
        });
        created = workflowToUnified(r);
      } else {
        const r = await jira.createRun({ ...newJiraRun, branch });
        created = jiraToUnified(r);
      }
      setShowNewRun(false);
      await loadData();
      setSelectedRun(created);
      setActiveTab('activity');
    } catch (err) {
      console.error('Failed to create run:', err);
    }
  }

  async function handleCancel(run: UnifiedRun) {
    try {
      if (run.kind === 'test') await testing.cancelRun(run.id);
      else if (run.kind === 'workflow') await workflowsApi.cancel(run.id);
      else await jira.cancelRun(run.id);
      loadData();
    } catch (err) {
      console.error('Failed to cancel run:', err);
    }
  }

  async function handleRetry(run: UnifiedRun) {
    try {
      if (run.kind === 'test') await testing.retryRun(run.id);
      else await jira.retryRun(run.id);
      loadData();
    } catch (err) {
      console.error('Failed to retry run:', err);
    }
  }

  async function handleResumeWorkflow(run: UnifiedRun) {
    try {
      const fresh = await workflowsApi.resume(run.id);
      setSelectedRun(workflowToUnified(fresh));
      loadData();
    } catch (err) {
      console.error('Failed to resume workflow:', err);
    }
  }

  const statusColor: Record<string, string> = {
    queued: 'bg-gray-100 text-gray-700',
    running: 'bg-blue-100 text-blue-700',
    passed: 'bg-green-100 text-green-700',
    completed: 'bg-green-100 text-green-700',
    failed: 'bg-red-100 text-red-700',
    error: 'bg-red-100 text-red-700',
    cancelled: 'bg-yellow-100 text-yellow-700',
    paused: 'bg-amber-100 text-amber-700',
    planning: 'bg-gray-100 text-gray-700',
  };

  const filteredRuns = runs.filter((r) => runFilter === 'all' || r.kind === runFilter);
  const isRunning = selectedRun?.status === 'running';
  const logEntries: LogEntry[] = (selectedRun?.log as LogEntry[]) || [];

  if (loading) {
    return <p className="text-gray-500">Loading agent runs...</p>;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Agent Monitor</h1>
        <button
          onClick={() => setShowNewRun(!showNewRun)}
          className="px-4 py-2 bg-indigo-600 text-white rounded-md text-sm font-medium hover:bg-indigo-700"
        >
          + New Run
        </button>
      </div>

      {/* New run form */}
      {showNewRun && (
        <form onSubmit={handleCreateRun} className="bg-white rounded-lg border border-gray-200 p-4 space-y-4">
          {/* Run kind toggle */}
          <div className="flex gap-2 mb-2">
            <button type="button"
              onClick={() => setNewRunKind('test')}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                newRunKind === 'test' ? 'bg-indigo-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >Test Run</button>
            <button type="button"
              onClick={() => setNewRunKind('jira')}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                newRunKind === 'jira' ? 'bg-purple-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >JIRA Run</button>
            <button type="button"
              onClick={() => setNewRunKind('workflow')}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                newRunKind === 'workflow' ? 'bg-teal-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >Workflow</button>
          </div>

          {newRunKind === 'workflow' ? (
            <div className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Goal</label>
                <textarea
                  value={newWorkflow.goal}
                  onChange={(e) => setNewWorkflow({ ...newWorkflow, goal: e.target.value })}
                  placeholder="e.g. Add comprehensive security BDD tests for all REST endpoints with OWASP Top 10 coverage..."
                  className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
                  rows={3}
                  required
                />
              </div>
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Project / Repository</label>
                  <select
                    value={newWorkflow.project_id}
                    onChange={(e) => setNewWorkflow({ ...newWorkflow, project_id: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
                  >
                    <option value="">Select project...</option>
                    {projects.map((p) => (
                      <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Branch</label>
                  <select
                    value={branch}
                    onChange={(e) => setBranch(e.target.value)}
                    className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
                    disabled={loadingBranches || branchList.length === 0}
                  >
                    {loadingBranches ? (
                      <option>Loading...</option>
                    ) : branchList.length === 0 ? (
                      <option value="main">main</option>
                    ) : (
                      branchList.map((b) => (
                        <option key={b} value={b}>{b}</option>
                      ))
                    )}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Mode</label>
                  <div className="flex gap-3 mt-1.5">
                    <label className="flex items-center gap-1.5 text-sm text-gray-700 cursor-pointer">
                      <input
                        type="radio"
                        name="wf-mode"
                        checked={newWorkflow.mode === 'testing'}
                        onChange={() => setNewWorkflow({ ...newWorkflow, mode: 'testing' })}
                        className="text-teal-600"
                      />
                      Testing
                    </label>
                    <label className="flex items-center gap-1.5 text-sm text-gray-700 cursor-pointer">
                      <input
                        type="radio"
                        name="wf-mode"
                        checked={newWorkflow.mode === 'engineering'}
                        onChange={() => setNewWorkflow({ ...newWorkflow, mode: 'engineering' })}
                        className="text-teal-600"
                      />
                      Engineering
                    </label>
                  </div>
                </div>
              </div>
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">
                    Token Budget <span className="text-gray-400 font-normal">(0 = unlimited)</span>
                  </label>
                  <input
                    type="number"
                    min="0"
                    step="1000"
                    value={newWorkflow.token_budget || ''}
                    onChange={(e) => setNewWorkflow({ ...newWorkflow, token_budget: parseInt(e.target.value) || 0 })}
                    placeholder="0 (unlimited)"
                    className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
                  />
                </div>
              </div>
            </div>
          ) : newRunKind === 'test' ? (
            <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Project / Repository</label>
                <select
                  value={newTestRun.project_id}
                  onChange={(e) => setNewTestRun({ ...newTestRun, project_id: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
                  required
                >
                  <option value="">Select project...</option>
                  {projects.map((p) => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                  {repoList.length > 0 && projects.length > 0 && (
                    <option disabled>── Repositories ──</option>
                  )}
                  {repoList
                    .filter((r) => !projects.some((p) => p.repo_url === r.url))
                    .map((r) => (
                      <option key={`repo-${r.id}`} value={r.id}>
                        {r.url || r.local_path || r.id}
                      </option>
                    ))}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Branch</label>
                <select
                  value={branch}
                  onChange={(e) => setBranch(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
                  disabled={loadingBranches || branchList.length === 0}
                >
                  {loadingBranches ? (
                    <option>Loading...</option>
                  ) : branchList.length === 0 ? (
                    <option value="main">main</option>
                  ) : (
                    branchList.map((b) => (
                      <option key={b} value={b}>{b}</option>
                    ))
                  )}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Type</label>
                <select
                  value={newTestRun.run_type}
                  onChange={(e) => setNewTestRun({ ...newTestRun, run_type: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
                >
                  <option value="functional">Functional</option>
                  <option value="security">Security</option>
                  <option value="regression">Regression</option>
                  <option value="smoke">Smoke</option>
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Strategy</label>
                <select
                  value={newTestRun.strategy}
                  onChange={(e) => setNewTestRun({ ...newTestRun, strategy: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
                >
                  <option value="auto">Auto</option>
                  <option value="bdd">BDD / Cucumber</option>
                  <option value="security_bdd">Security BDD</option>
                  <option value="unit">Unit</option>
                  <option value="integration">Integration</option>
                  <option value="e2e">End-to-End</option>
                  <option value="contract">Contract</option>
                  <option value="soap">SOAP</option>
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Scope</label>
                <input
                  type="text"
                  value={newTestRun.target_scope}
                  onChange={(e) => setNewTestRun({ ...newTestRun, target_scope: e.target.value })}
                  placeholder="All endpoints"
                  className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
                />
              </div>
            </div>
          ) : (
            <div className="grid grid-cols-3 gap-4">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Repository</label>
                <select
                  value={newJiraRun.repo_id}
                  onChange={(e) => setNewJiraRun({ ...newJiraRun, repo_id: e.target.value })}
                  className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
                  required
                >
                  <option value="">Select repository...</option>
                  {repoList.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.url || r.local_path || r.id}
                    </option>
                  ))}
                  {repoList.length === 0 && projects.map((p) => (
                    <option key={p.id} value={p.repo_id || p.id}>
                      {p.name} ({p.repo_url || p.local_path})
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Branch</label>
                <select
                  value={branch}
                  onChange={(e) => setBranch(e.target.value)}
                  className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
                  disabled={loadingBranches || branchList.length === 0}
                >
                  {loadingBranches ? (
                    <option>Loading...</option>
                  ) : branchList.length === 0 ? (
                    <option value="main">main</option>
                  ) : (
                    branchList.map((b) => (
                      <option key={b} value={b}>{b}</option>
                    ))
                  )}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">JIRA Project Key</label>
                <input
                  type="text"
                  value={newJiraRun.jira_project}
                  onChange={(e) => setNewJiraRun({ ...newJiraRun, jira_project: e.target.value })}
                  placeholder="e.g. PROJ"
                  className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
                />
              </div>
            </div>
          )}

          {/* Reference Repository (collapsible) */}
          {newRunKind === 'test' && (
            <div className="border border-gray-200 rounded-lg">
              <button
                type="button"
                onClick={() => setShowRefRepo(!showRefRepo)}
                className="w-full flex items-center justify-between px-4 py-2.5 text-sm text-gray-700 hover:bg-gray-50 rounded-lg"
              >
                <span className="flex items-center gap-2">
                  <span className="text-xs">{showRefRepo ? '\u25BC' : '\u25B6'}</span>
                  Reference Repository
                  {refLearnResult && (
                    <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded">
                      {refLearnResult.steps_learned} steps, {refLearnResult.features_learned} features
                    </span>
                  )}
                </span>
                <span className="text-xs text-gray-400">Optional</span>
              </button>

              {showRefRepo && (
                <div className="px-4 pb-4 space-y-3 border-t border-gray-200 pt-3">
                  <p className="text-xs text-gray-500">
                    Provide a reference repository with BDD patterns, step definitions, and Maven dependencies.
                    The system will learn from it and use the patterns when generating tests.
                  </p>
                  <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
                    <div className="lg:col-span-2">
                      <label className="block text-xs font-medium text-gray-600 mb-1">Reference Repo URL</label>
                      <input
                        type="text"
                        value={refRepoUrl}
                        onChange={(e) => setRefRepoUrl(e.target.value)}
                        placeholder="https://github.com/example/security-bdd-tests.git"
                        className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-600 mb-1">Branch</label>
                      <input
                        type="text"
                        value={refRepoBranch}
                        onChange={(e) => setRefRepoBranch(e.target.value)}
                        placeholder="main"
                        className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
                      />
                    </div>
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-600 mb-1">
                      Additional Maven Dependencies <span className="text-gray-400">(comma-separated)</span>
                    </label>
                    <input
                      type="text"
                      value={refMavenDeps}
                      onChange={(e) => setRefMavenDeps(e.target.value)}
                      placeholder="com.example:security-bdd:1.0, org.owasp:zap-client:2.0"
                      className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
                    />
                  </div>
                  <div className="flex items-center gap-3">
                    <button
                      type="button"
                      onClick={async () => {
                        const projectId = newTestRun.project_id;
                        if (!projectId || !refRepoUrl) return;
                        setLearningRef(true);
                        setRefLearnResult(null);
                        try {
                          const result = await testing.learnReference(projectId, {
                            reference_repo_url: refRepoUrl,
                            reference_branch: refRepoBranch || 'main',
                            maven_deps: refMavenDeps ? refMavenDeps.split(',').map((s) => s.trim()).filter(Boolean) : [],
                          });
                          setRefLearnResult(result);
                        } catch (err) {
                          console.error('Reference repo learning failed:', err);
                        } finally {
                          setLearningRef(false);
                        }
                      }}
                      disabled={!newTestRun.project_id || !refRepoUrl || learningRef}
                      className="px-4 py-2 bg-emerald-600 text-white rounded-md text-sm font-medium hover:bg-emerald-700 disabled:opacity-50"
                    >
                      {learningRef ? 'Learning...' : 'Learn Patterns'}
                    </button>
                    {!newTestRun.project_id && refRepoUrl && (
                      <span className="text-xs text-amber-600">Select a project first</span>
                    )}
                  </div>

                  {/* Learn results */}
                  {refLearnResult && (
                    <div className="bg-green-50 border border-green-200 rounded-lg p-3">
                      <p className="text-sm font-medium text-green-800 mb-2">Patterns Learned Successfully</p>
                      <div className="grid grid-cols-3 gap-3 text-center">
                        <div>
                          <p className="text-2xl font-bold text-green-700">{refLearnResult.steps_learned}</p>
                          <p className="text-xs text-green-600">Step Definitions</p>
                        </div>
                        <div>
                          <p className="text-2xl font-bold text-green-700">{refLearnResult.features_learned}</p>
                          <p className="text-xs text-green-600">Feature Files</p>
                        </div>
                        <div>
                          <p className="text-2xl font-bold text-green-700">{refLearnResult.maven_deps_found}</p>
                          <p className="text-xs text-green-600">Maven Dependencies</p>
                        </div>
                      </div>
                      {refLearnResult.patterns.step_definitions.length > 0 && (
                        <div className="mt-3">
                          <p className="text-xs font-medium text-green-700 mb-1">Sample Steps:</p>
                          <div className="text-xs text-green-600 space-y-0.5 max-h-24 overflow-y-auto">
                            {refLearnResult.patterns.step_definitions.slice(0, 5).map((s, i) => (
                              <div key={i}>@{s.step_type}(&quot;{s.pattern}&quot;)</div>
                            ))}
                            {refLearnResult.patterns.step_definitions.length > 5 && (
                              <div className="text-green-500">...and {refLearnResult.patterns.step_definitions.length - 5} more</div>
                            )}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => setShowNewRun(false)} className="px-3 py-1.5 text-sm border border-gray-300 rounded hover:bg-gray-50">
              Cancel
            </button>
            <button type="submit" className={`px-3 py-1.5 text-sm text-white rounded ${
              newRunKind === 'jira' ? 'bg-purple-600 hover:bg-purple-700'
                : newRunKind === 'workflow' ? 'bg-teal-600 hover:bg-teal-700'
                : 'bg-indigo-600 hover:bg-indigo-700'
            }`}>
              {newRunKind === 'workflow' ? 'Start Workflow' : `Start ${newRunKind === 'jira' ? 'JIRA' : 'Test'} Run`}
            </button>
          </div>
        </form>
      )}

      {/* Filter tabs */}
      <div className="flex gap-1 bg-gray-100 rounded-lg p-1 w-fit">
        {(['all', 'test', 'jira', 'workflow'] as RunFilter[]).map((f) => (
          <button
            key={f}
            onClick={() => setRunFilter(f)}
            className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
              runFilter === f
                ? 'bg-white text-gray-900 shadow-sm'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            {f === 'all' ? 'All Runs' : f === 'test' ? 'Test Runs' : f === 'jira' ? 'JIRA Runs' : 'Workflows'}
            <span className="ml-1 text-gray-400">
              ({runs.filter((r) => f === 'all' || r.kind === f).length})
            </span>
          </button>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Runs list */}
        <div className="lg:col-span-2 space-y-3">
          {filteredRuns.length === 0 ? (
            <div className="bg-white rounded-lg border border-gray-200 p-8 text-center text-gray-500">
              No runs yet. Create one to get started.
            </div>
          ) : (
            filteredRuns.map((run) => {
              const label = run.kind === 'test'
                ? (projects.find((p) => p.id === run.project_id)?.name || run.project_id || 'Test')
                : run.kind === 'workflow'
                ? (run.goal?.slice(0, 60) || 'Workflow')
                : (run.jira_project || 'JIRA');
              return (
                <div
                  key={`${run.kind}-${run.id}`}
                  onClick={() => handleSelectRun(run)}
                  className={`bg-white rounded-lg border p-4 cursor-pointer transition-shadow hover:shadow-sm ${
                    selectedRun?.id === run.id && selectedRun?.kind === run.kind
                      ? 'border-indigo-400 ring-1 ring-indigo-200' : 'border-gray-200'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      {/* Kind badge */}
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                        run.kind === 'jira' ? 'bg-purple-100 text-purple-700'
                          : run.kind === 'workflow' ? 'bg-teal-100 text-teal-700'
                          : 'bg-gray-100 text-gray-600'
                      }`}>
                        {run.kind === 'jira' ? 'JIRA' : run.kind === 'workflow' ? 'WORKFLOW' : 'TEST'}
                      </span>
                      {/* Status badge */}
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${statusColor[run.status] || 'bg-gray-100'}`}>
                        {run.status}
                      </span>
                      <span className="text-sm font-medium text-gray-900">{label}</span>
                      {run.kind === 'test' && (
                        <span className="text-xs text-gray-400">{run.run_type} / {run.strategy}</span>
                      )}
                    </div>
                    <div className="flex items-center gap-3">
                      {(run.status === 'running' || (run.kind === 'workflow' && run.status === 'paused')) && (
                        <button
                          onClick={(e) => { e.stopPropagation(); handleCancel(run); }}
                          className="text-xs text-red-600 hover:text-red-800"
                        >Cancel</button>
                      )}
                      {run.kind === 'workflow' && run.status === 'paused' && (
                        <button
                          onClick={(e) => { e.stopPropagation(); handleResumeWorkflow(run); }}
                          className="text-xs text-teal-600 hover:text-teal-800 font-medium"
                        >Resume</button>
                      )}
                      {['queued', 'failed', 'error'].includes(run.status) && run.kind !== 'workflow' && (
                        <button
                          onClick={(e) => { e.stopPropagation(); handleRetry(run); }}
                          className="text-xs text-indigo-600 hover:text-indigo-800 font-medium"
                        >Retry</button>
                      )}
                      <span className="text-xs text-gray-400">
                        {run.created_at ? new Date(run.created_at).toLocaleString() : ''}
                      </span>
                    </div>
                  </div>

                  {/* Progress bar */}
                  {run.status === 'running' && (
                    <div className="mt-3">
                      <div className="flex justify-between text-xs text-gray-500 mb-1">
                        <span>Progress</span>
                        <span>{Math.round(run.progress_pct)}%</span>
                      </div>
                      <div className="w-full bg-gray-200 rounded-full h-2">
                        <div
                          className={`h-2 rounded-full transition-all ${
                            run.kind === 'jira' ? 'bg-purple-600' : run.kind === 'workflow' ? 'bg-teal-600' : 'bg-indigo-600'
                          }`}
                          style={{ width: `${run.progress_pct}%` }}
                        />
                      </div>
                    </div>
                  )}

                  {/* Test counts */}
                  {run.kind === 'test' && (run.total_tests || 0) > 0 && (
                    <div className="mt-2 flex gap-4 text-xs">
                      <span className="text-green-600">{run.passed_tests} passed</span>
                      <span className="text-red-600">{run.failed_tests} failed</span>
                      <span className="text-gray-400">{run.skipped_tests} skipped</span>
                      <span className="text-gray-500">{run.total_tests} total</span>
                    </div>
                  )}

                  {/* Story counts */}
                  {run.kind === 'jira' && (run.total_stories || 0) > 0 && (
                    <div className="mt-2 flex gap-4 text-xs">
                      <span className="text-green-600">{run.succeeded_stories} succeeded</span>
                      <span className="text-red-600">{run.failed_stories} failed</span>
                      <span className="text-gray-500">{run.total_stories} total stories</span>
                    </div>
                  )}

                  {/* Workflow subtask steps */}
                  {run.kind === 'workflow' && run.subtasks && run.subtasks.length > 0 && (
                    <div className="mt-2">
                      <div className="flex items-center gap-2 text-xs text-gray-500 mb-1">
                        <span>Step {(run.current_step || 0) + 1}/{run.subtasks.length}: {run.subtasks[run.current_step || 0]?.title}</span>
                        {(run.total_tokens_used || 0) > 0 && (
                          <span className="text-gray-400 font-mono">
                            {run.total_tokens_used?.toLocaleString()} tokens
                            {(run.token_budget || 0) > 0 && ` / ${run.token_budget?.toLocaleString()}`}
                          </span>
                        )}
                      </div>
                      <div className="flex gap-1 flex-wrap">
                        {run.subtasks.map((st, idx) => (
                          <span key={idx} className={`text-xs ${subtaskStatusColor(st.status)}`} title={st.title}>
                            {subtaskStatusIcon(st.status)}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {run.result_summary && (
                    <p className="mt-2 text-xs text-gray-500 truncate">{run.result_summary}</p>
                  )}
                </div>
              );
            })
          )}
        </div>

        {/* Detail panel */}
        <div className="space-y-4">
          {selectedRun ? (
            <>
              {/* Run Details card */}
              <div className="bg-white rounded-lg border border-gray-200 p-4">
                <h3 className="font-medium text-gray-900 mb-3">Run Details</h3>
                <dl className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <dt className="text-gray-500">ID</dt>
                    <dd className="text-gray-900 font-mono text-xs">{selectedRun.id}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-gray-500">Kind</dt>
                    <dd className={`font-medium ${
                      selectedRun.kind === 'jira' ? 'text-purple-700'
                        : selectedRun.kind === 'workflow' ? 'text-teal-700'
                        : 'text-gray-900'
                    }`}>
                      {selectedRun.kind === 'jira' ? 'JIRA-to-PR'
                        : selectedRun.kind === 'workflow' ? 'Workflow'
                        : 'Test Generation'}
                    </dd>
                  </div>
                  {selectedRun.kind === 'workflow' && (
                    <>
                      <div className="flex justify-between">
                        <dt className="text-gray-500">Mode</dt>
                        <dd className="text-gray-900 capitalize">{selectedRun.mode}</dd>
                      </div>
                      {selectedRun.goal && (
                        <div>
                          <dt className="text-gray-500 mb-1">Goal</dt>
                          <dd className="text-gray-900 text-xs">{selectedRun.goal}</dd>
                        </div>
                      )}
                      {(selectedRun.total_tokens_used || 0) > 0 && (
                        <div className="flex justify-between">
                          <dt className="text-gray-500">Tokens</dt>
                          <dd className="text-gray-900 text-xs font-mono">
                            {selectedRun.total_tokens_used?.toLocaleString()}
                            {(selectedRun.token_budget || 0) > 0 && (
                              <span className="text-gray-400"> / {selectedRun.token_budget?.toLocaleString()}</span>
                            )}
                          </dd>
                        </div>
                      )}
                    </>
                  )}
                  {selectedRun.kind === 'test' && (
                    <>
                      <div className="flex justify-between">
                        <dt className="text-gray-500">Type</dt>
                        <dd className="text-gray-900">{selectedRun.run_type}</dd>
                      </div>
                      <div className="flex justify-between">
                        <dt className="text-gray-500">Strategy</dt>
                        <dd className="text-gray-900">{selectedRun.strategy}</dd>
                      </div>
                      {selectedRun.target_scope && (
                        <div className="flex justify-between">
                          <dt className="text-gray-500">Scope</dt>
                          <dd className="text-gray-900">{selectedRun.target_scope}</dd>
                        </div>
                      )}
                    </>
                  )}
                  {selectedRun.kind === 'jira' && (
                    <>
                      {selectedRun.jira_project && (
                        <div className="flex justify-between">
                          <dt className="text-gray-500">JIRA Project</dt>
                          <dd className="text-gray-900">{selectedRun.jira_project}</dd>
                        </div>
                      )}
                      <div className="flex justify-between">
                        <dt className="text-gray-500">Stories</dt>
                        <dd className="text-gray-900">
                          {selectedRun.succeeded_stories}/{selectedRun.total_stories} succeeded
                        </dd>
                      </div>
                    </>
                  )}
                  <div className="flex justify-between">
                    <dt className="text-gray-500">Agent</dt>
                    <dd className="text-gray-900">{selectedRun.agent_id || 'N/A'}</dd>
                  </div>
                </dl>
              </div>

              {/* Tabbed panel */}
              <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
                <div className="flex border-b border-gray-200">
                  <button
                    onClick={() => setActiveTab('activity')}
                    className={`flex-1 px-4 py-2.5 text-xs font-medium transition-colors ${
                      activeTab === 'activity'
                        ? 'text-indigo-600 border-b-2 border-indigo-600 bg-indigo-50/50'
                        : 'text-gray-500 hover:text-gray-700'
                    }`}
                  >
                    Activity
                    {isRunning && (
                      <span className="ml-1.5 inline-block w-1.5 h-1.5 rounded-full bg-green-500 terminal-cursor" />
                    )}
                  </button>
                  {selectedRun.kind === 'test' && (
                    <button
                      onClick={() => setActiveTab('evidence')}
                      className={`flex-1 px-4 py-2.5 text-xs font-medium transition-colors ${
                        activeTab === 'evidence'
                          ? 'text-indigo-600 border-b-2 border-indigo-600 bg-indigo-50/50'
                          : 'text-gray-500 hover:text-gray-700'
                      }`}
                    >
                      Evidence ({evidences.length})
                    </button>
                  )}
                  <button
                    onClick={() => setActiveTab('artifacts')}
                    className={`flex-1 px-4 py-2.5 text-xs font-medium transition-colors ${
                      activeTab === 'artifacts'
                        ? 'text-indigo-600 border-b-2 border-indigo-600 bg-indigo-50/50'
                        : 'text-gray-500 hover:text-gray-700'
                    }`}
                  >
                    {selectedRun.kind === 'jira' ? 'Stories' : 'Artifacts'}
                  </button>
                </div>

                {/* Workflow Subtask Stepper + Checkpoint Banner */}
                {selectedRun.kind === 'workflow' && activeTab === 'activity' && selectedRun.subtasks && selectedRun.subtasks.length > 0 && (
                  <div className="border-b border-gray-200">
                    {/* Subtask stepper */}
                    <div className="px-4 py-3 space-y-1.5">
                      {selectedRun.subtasks.map((st, idx) => (
                        <div key={idx} className="flex items-center gap-2">
                          <span className={`text-sm font-medium w-5 text-center ${subtaskStatusColor(st.status)}`}>
                            {subtaskStatusIcon(st.status)}
                          </span>
                          <span className={`text-xs ${
                            st.status === 'running' ? 'text-blue-700 font-medium'
                              : st.status === 'completed' ? 'text-gray-700'
                              : st.status === 'failed' ? 'text-red-700'
                              : 'text-gray-400'
                          }`}>
                            {st.title}
                          </span>
                          {st.checkpoint && st.status !== 'completed' && (
                            <span className="text-xs bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded">checkpoint</span>
                          )}
                          {st.model_used && (
                            <span className="text-xs bg-gray-100 text-gray-500 px-1 py-0.5 rounded font-mono">{st.model_used}</span>
                          )}
                          {(st.attempts || 1) > 1 && (
                            <span className="text-xs bg-orange-100 text-orange-700 px-1 py-0.5 rounded">attempt {st.attempts}</span>
                          )}
                          {st.result_summary && st.status === 'completed' && (
                            <span className="text-xs text-gray-400 truncate max-w-[200px]">{st.result_summary}</span>
                          )}
                        </div>
                      ))}
                    </div>

                    {/* Checkpoint banner when paused */}
                    {selectedRun.status === 'paused' && (
                      <div className="mx-4 mb-3 bg-amber-50 border border-amber-200 rounded-lg p-3">
                        <div className="flex items-center gap-2 mb-2">
                          <span className="text-amber-600 font-medium text-sm">Paused at checkpoint</span>
                        </div>
                        {(() => {
                          const lastCompleted = selectedRun.subtasks?.filter(s => s.status === 'completed').slice(-1)[0];
                          return lastCompleted ? (
                            <div className="text-xs text-amber-800 mb-2">
                              <p className="font-medium">After: {lastCompleted.title}</p>
                              {lastCompleted.result_summary && (
                                <p className="mt-1 text-amber-700">{lastCompleted.result_summary}</p>
                              )}
                              {lastCompleted.files_changed.length > 0 && (
                                <p className="mt-1 text-amber-600">
                                  Files: {lastCompleted.files_changed.slice(0, 5).join(', ')}
                                  {lastCompleted.files_changed.length > 5 && ` +${lastCompleted.files_changed.length - 5} more`}
                                </p>
                              )}
                            </div>
                          ) : null;
                        })()}
                        <div className="flex gap-2">
                          <button
                            onClick={() => handleResumeWorkflow(selectedRun)}
                            className="px-3 py-1.5 bg-teal-600 text-white rounded text-xs font-medium hover:bg-teal-700"
                          >
                            Resume Workflow
                          </button>
                          <button
                            onClick={() => handleCancel(selectedRun)}
                            className="px-3 py-1.5 border border-gray-300 text-gray-700 rounded text-xs hover:bg-gray-50"
                          >
                            Cancel
                          </button>
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* Activity Terminal */}
                {activeTab === 'activity' && (
                  <div className="bg-gray-900 rounded-b-lg">
                    <div className="flex items-center justify-between px-4 py-2 border-b border-gray-700">
                      <span className="text-xs text-gray-400 font-mono">Activity</span>
                      {isRunning && (
                        <span className="flex items-center gap-1.5 text-xs text-green-400">
                          <span className="w-1.5 h-1.5 rounded-full bg-green-400 terminal-cursor" />
                          Live
                        </span>
                      )}
                      {!isRunning && selectedRun.status !== 'queued' && (
                        <span className={`text-xs ${selectedRun.status === 'paused' ? 'text-amber-400' : 'text-gray-500'}`}>
                          {selectedRun.status === 'passed' || selectedRun.status === 'completed' ? 'Completed' :
                           selectedRun.status === 'failed' ? 'Failed' :
                           selectedRun.status === 'error' ? 'Error' :
                           selectedRun.status === 'cancelled' ? 'Cancelled' :
                           selectedRun.status === 'paused' ? 'Paused' : ''}
                        </span>
                      )}
                    </div>
                    <div
                      ref={terminalRef}
                      className="p-4 font-mono text-xs leading-relaxed max-h-96 overflow-y-auto"
                    >
                      {logEntries.length === 0 ? (
                        <div className="text-gray-500">
                          {selectedRun.status === 'queued'
                            ? 'Waiting for agent to start...'
                            : 'No activity recorded.'}
                        </div>
                      ) : (
                        logEntries.map((entry, i) => (
                          <div key={i} className="mb-1">
                            {isStageHeader(entry.stage) ? (
                              <div className={`${stageColor(entry.stage)}`}>
                                <span className="text-gray-600">[{formatTime(entry.timestamp)}]</span>
                                {' '}{stageIcon(entry.stage)} {entry.detail}
                              </div>
                            ) : (
                              <div className={`pl-4 ${stageColor(entry.stage)}`}>
                                {stageIcon(entry.stage) !== '$' && (
                                  <span>{stageIcon(entry.stage)} </span>
                                )}
                                {entry.detail}
                              </div>
                            )}
                          </div>
                        ))
                      )}
                      {isRunning && (
                        <span className="inline-block w-2 h-4 bg-gray-400 terminal-cursor mt-1" />
                      )}
                    </div>
                  </div>
                )}

                {/* Evidence tab (test runs only) */}
                {activeTab === 'evidence' && selectedRun.kind === 'test' && (
                  <div className="p-4">
                    {evidences.length === 0 ? (
                      <p className="text-sm text-gray-500">No evidence collected yet.</p>
                    ) : (
                      <div className="space-y-2 max-h-96 overflow-y-auto">
                        {evidences.map((ev) => (
                          <div key={ev.id} className={`border rounded p-3 ${
                            ev.title === 'Error Classification' ? 'border-orange-200 bg-orange-50' : 'border-gray-100'
                          }`}>
                            <div className="flex items-center gap-2 mb-1">
                              <span className={`text-xs px-2 py-0.5 rounded ${
                                ev.title === 'Error Classification' ? 'bg-orange-100 text-orange-700' : 'bg-gray-100 text-gray-600'
                              }`}>{ev.evidence_type}</span>
                              <span className="text-xs font-medium text-gray-700">{ev.title}</span>
                            </div>
                            {ev.content && (() => {
                              // Try to parse error classification JSON for structured display
                              if (ev.title === 'Error Classification') {
                                try {
                                  const classifications = JSON.parse(ev.content);
                                  if (Array.isArray(classifications)) {
                                    return (
                                      <div className="space-y-1.5 mt-1">
                                        {classifications.map((ec: any, i: number) => (
                                          <div key={i} className="flex items-start gap-2 text-xs">
                                            <span className="px-1.5 py-0.5 rounded bg-orange-100 text-orange-700 font-medium flex-shrink-0">
                                              {ec.type}/{ec.subtype}
                                            </span>
                                            <span className="text-gray-700">{ec.message}</span>
                                            {ec.suggestion && (
                                              <span className="text-amber-600 text-[11px] ml-auto flex-shrink-0">{ec.suggestion}</span>
                                            )}
                                          </div>
                                        ))}
                                      </div>
                                    );
                                  }
                                } catch { /* fall through to raw display */ }
                              }
                              return (
                                <pre className="text-xs text-gray-600 whitespace-pre-wrap mt-1 max-h-32 overflow-y-auto bg-gray-50 p-2 rounded">
                                  {ev.content}
                                </pre>
                              );
                            })()}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* Artifacts / Stories tab */}
                {activeTab === 'artifacts' && (
                  <div className="p-4">
                    {selectedRun.kind === 'jira' && selectedRun.artifacts?.stories ? (
                      <div className="space-y-2 max-h-96 overflow-y-auto">
                        {(selectedRun.artifacts.stories as any[]).map((s: any, i: number) => (
                          <div key={i} className="border border-gray-100 rounded p-3">
                            <div className="flex items-center justify-between">
                              <div className="flex items-center gap-2">
                                <span className={`px-2 py-0.5 rounded text-xs font-medium ${
                                  s.status === 'success' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
                                }`}>{s.status}</span>
                                <span className="text-sm font-medium text-gray-900">{s.key}</span>
                              </div>
                              <span className="text-xs text-gray-500">{s.files_changed || 0} files</span>
                            </div>
                            <p className="text-xs text-gray-600 mt-1 truncate">{s.summary}</p>
                            {s.pr_url && (
                              <a href={s.pr_url} target="_blank" rel="noopener noreferrer"
                                className="text-xs text-blue-600 hover:underline mt-1 inline-block"
                              >View PR</a>
                            )}
                          </div>
                        ))}
                      </div>
                    ) : selectedRun.artifacts && Object.keys(selectedRun.artifacts).length > 0 ? (
                      <div className="space-y-2 text-sm max-h-96 overflow-y-auto">
                        {Object.entries(selectedRun.artifacts).map(([key, val]) => {
                          // Structured rendering for error_classifications array
                          if (key === 'error_classifications' && Array.isArray(val) && val.length > 0) {
                            return (
                              <div key={key} className="border border-orange-200 rounded p-3 bg-orange-50">
                                <div className="text-xs font-medium text-orange-700 mb-2">Error Classifications ({val.length})</div>
                                <div className="space-y-1.5">
                                  {(val as any[]).map((ec: any, i: number) => (
                                    <div key={i} className="flex items-start gap-2 text-xs">
                                      <span className="px-1.5 py-0.5 rounded bg-orange-100 text-orange-700 font-medium flex-shrink-0">
                                        {ec.type}/{ec.subtype}
                                      </span>
                                      <span className="text-gray-700 truncate">{ec.message}</span>
                                      {ec.suggestion && (
                                        <span className="text-amber-600 flex-shrink-0 ml-auto">{ec.suggestion}</span>
                                      )}
                                    </div>
                                  ))}
                                </div>
                              </div>
                            );
                          }
                          // Render arrays/objects as formatted JSON
                          if (typeof val === 'object' && val !== null) {
                            return (
                              <div key={key} className="border border-gray-100 rounded p-3">
                                <div className="text-xs font-medium text-gray-700 mb-1">{key}</div>
                                <pre className="text-xs text-gray-600 whitespace-pre-wrap bg-gray-50 p-2 rounded max-h-32 overflow-y-auto">
                                  {JSON.stringify(val, null, 2)}
                                </pre>
                              </div>
                            );
                          }
                          return (
                            <div key={key} className="flex justify-between text-gray-600">
                              <span>{key}</span>
                              <span className="font-mono text-xs">{String(val)}</span>
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <p className="text-sm text-gray-500">
                        {selectedRun.kind === 'jira' ? 'No story results yet.' : 'No artifacts yet.'}
                      </p>
                    )}
                  </div>
                )}
              </div>
            </>
          ) : (
            <div className="bg-white rounded-lg border border-gray-200 p-8 text-center text-gray-400 text-sm">
              Select a run to view details
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
