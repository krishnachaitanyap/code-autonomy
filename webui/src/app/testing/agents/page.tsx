'use client';

import { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { testing, type TestRun, type TestProject, type TestEvidence } from '@/lib/api';

type LogEntry = {
  timestamp: string;
  stage: string;
  detail: string;
  progress: number;
};

type DetailTab = 'activity' | 'evidence' | 'artifacts';

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch {
    return '';
  }
}

function stageIcon(stage: string): string {
  if (stage === 'tool_call') return '\u25b8';
  if (stage === 'error') return '\u2717';
  if (stage === 'complete' || stage === 'result' || stage.startsWith('discovery_result')) return '\u2713';
  return '$';
}

function stageColor(stage: string): string {
  if (stage === 'tool_call') return 'text-yellow-400';
  if (stage === 'error') return 'text-red-400';
  if (stage === 'complete' || stage === 'result') return 'text-green-400';
  if (stage.startsWith('discovery_result')) return 'text-green-400';
  if (stage === 'test_output') return 'text-gray-300';
  // Stage headers: initializing, resolving_repo, discovery, building_requirements, etc.
  return 'text-cyan-400';
}

function isStageHeader(stage: string): boolean {
  return [
    'initializing', 'resolving_repo', 'discovery', 'building_requirements',
    'generating_tests', 'executing_tests', 'parsing_results',
    'recording_evidence', 'complete', 'error',
  ].includes(stage);
}

export default function AgentsPage() {
  const searchParams = useSearchParams();
  const projectFilter = searchParams.get('project') || '';

  const [runs, setRuns] = useState<TestRun[]>([]);
  const [projects, setProjects] = useState<TestProject[]>([]);
  const [selectedRun, setSelectedRun] = useState<TestRun | null>(null);
  const [evidences, setEvidences] = useState<TestEvidence[]>([]);
  const [loading, setLoading] = useState(true);
  const [showNewRun, setShowNewRun] = useState(false);
  const [activeTab, setActiveTab] = useState<DetailTab>('activity');
  const [newRun, setNewRun] = useState({
    project_id: projectFilter,
    run_type: 'functional',
    strategy: 'auto',
    target_scope: '',
  });

  const terminalRef = useRef<HTMLDivElement>(null);

  // Load initial data
  useEffect(() => {
    loadData();
  }, [projectFilter]);

  // Polling: refresh selected run every 2s while running
  useEffect(() => {
    if (!selectedRun || selectedRun.status !== 'running') return;

    const interval = setInterval(async () => {
      try {
        const fresh = await testing.getRun(selectedRun.id);
        setSelectedRun(fresh);

        // Also refresh the runs list to update progress bar
        const r = await testing.listRuns({ project_id: projectFilter || undefined, limit: 50 });
        setRuns(r.runs);

        // If run is now complete, load evidences
        if (fresh.status !== 'running') {
          const ev = await testing.listEvidences(fresh.id);
          setEvidences(ev);
        }
      } catch {
        // Ignore polling errors
      }
    }, 2000);

    return () => clearInterval(interval);
  }, [selectedRun?.id, selectedRun?.status, projectFilter]);

  // Auto-scroll terminal to bottom on new log entries
  useEffect(() => {
    if (terminalRef.current && activeTab === 'activity') {
      terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
    }
  }, [selectedRun?.log, activeTab]);

  async function loadData() {
    setLoading(true);
    try {
      const [r, p] = await Promise.all([
        testing.listRuns({ project_id: projectFilter || undefined, limit: 50 }),
        testing.listProjects({ limit: 100 }),
      ]);
      setRuns(r.runs);
      setProjects(p.projects);
    } catch (err) {
      console.error('Failed to load runs:', err);
    } finally {
      setLoading(false);
    }
  }

  async function handleSelectRun(run: TestRun) {
    setSelectedRun(run);
    setActiveTab(run.status === 'running' ? 'activity' : 'activity');
    try {
      const ev = await testing.listEvidences(run.id);
      setEvidences(ev);
    } catch {
      setEvidences([]);
    }
  }

  async function handleCreateRun(e: React.FormEvent) {
    e.preventDefault();
    try {
      const created = await testing.createRun(newRun);
      setShowNewRun(false);
      await loadData();
      // Auto-select the new run
      setSelectedRun(created);
      setActiveTab('activity');
    } catch (err) {
      console.error('Failed to create run:', err);
    }
  }

  async function handleCancel(runId: string) {
    try {
      await testing.cancelRun(runId);
      loadData();
    } catch (err) {
      console.error('Failed to cancel run:', err);
    }
  }

  async function handleRetry(runId: string) {
    try {
      await testing.retryRun(runId);
      loadData();
    } catch (err) {
      console.error('Failed to retry run:', err);
    }
  }

  const statusColor: Record<string, string> = {
    queued: 'bg-gray-100 text-gray-700',
    running: 'bg-blue-100 text-blue-700',
    passed: 'bg-green-100 text-green-700',
    failed: 'bg-red-100 text-red-700',
    error: 'bg-red-100 text-red-700',
    cancelled: 'bg-yellow-100 text-yellow-700',
  };

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
          + New Test Run
        </button>
      </div>

      {/* New run form */}
      {showNewRun && (
        <form onSubmit={handleCreateRun} className="bg-white rounded-lg border border-gray-200 p-4 space-y-4">
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Project</label>
              <select
                value={newRun.project_id}
                onChange={(e) => setNewRun({ ...newRun, project_id: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
                required
              >
                <option value="">Select project...</option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Type</label>
              <select
                value={newRun.run_type}
                onChange={(e) => setNewRun({ ...newRun, run_type: e.target.value })}
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
                value={newRun.strategy}
                onChange={(e) => setNewRun({ ...newRun, strategy: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
              >
                <option value="auto">Auto</option>
                <option value="bdd">BDD / Cucumber</option>
                <option value="unit">Unit</option>
                <option value="integration">Integration</option>
                <option value="e2e">End-to-End</option>
                <option value="penetration">Penetration</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Scope</label>
              <input
                type="text"
                value={newRun.target_scope}
                onChange={(e) => setNewRun({ ...newRun, target_scope: e.target.value })}
                placeholder="All endpoints"
                className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
              />
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => setShowNewRun(false)} className="px-3 py-1.5 text-sm border border-gray-300 rounded hover:bg-gray-50">
              Cancel
            </button>
            <button type="submit" className="px-3 py-1.5 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700">
              Start Run
            </button>
          </div>
        </form>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Runs list */}
        <div className="lg:col-span-2 space-y-3">
          {runs.length === 0 ? (
            <div className="bg-white rounded-lg border border-gray-200 p-8 text-center text-gray-500">
              No test runs yet. Create one to get started.
            </div>
          ) : (
            runs.map((run) => {
              const projectName = projects.find((p) => p.id === run.project_id)?.name || run.project_id;
              return (
                <div
                  key={run.id}
                  onClick={() => handleSelectRun(run)}
                  className={`bg-white rounded-lg border p-4 cursor-pointer transition-shadow hover:shadow-sm ${
                    selectedRun?.id === run.id ? 'border-indigo-400 ring-1 ring-indigo-200' : 'border-gray-200'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <span className={`px-2 py-0.5 rounded text-xs font-medium ${statusColor[run.status] || 'bg-gray-100'}`}>
                        {run.status}
                      </span>
                      <span className="text-sm font-medium text-gray-900">{projectName}</span>
                      <span className="text-xs text-gray-400">{run.run_type} / {run.strategy}</span>
                    </div>
                    <div className="flex items-center gap-3">
                      {run.status === 'running' && (
                        <button
                          onClick={(e) => { e.stopPropagation(); handleCancel(run.id); }}
                          className="text-xs text-red-600 hover:text-red-800"
                        >
                          Cancel
                        </button>
                      )}
                      {(run.status === 'queued' || run.status === 'failed' || run.status === 'error') && (
                        <button
                          onClick={(e) => { e.stopPropagation(); handleRetry(run.id); }}
                          className="text-xs text-indigo-600 hover:text-indigo-800 font-medium"
                        >
                          Retry
                        </button>
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
                        <span>{run.progress_pct}%</span>
                      </div>
                      <div className="w-full bg-gray-200 rounded-full h-2">
                        <div
                          className="bg-indigo-600 h-2 rounded-full transition-all"
                          style={{ width: `${run.progress_pct}%` }}
                        />
                      </div>
                    </div>
                  )}

                  {/* Test counts */}
                  {run.total_tests > 0 && (
                    <div className="mt-2 flex gap-4 text-xs">
                      <span className="text-green-600">{run.passed_tests} passed</span>
                      <span className="text-red-600">{run.failed_tests} failed</span>
                      <span className="text-gray-400">{run.skipped_tests} skipped</span>
                      <span className="text-gray-500">{run.total_tests} total</span>
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
                    <dt className="text-gray-500">Type</dt>
                    <dd className="text-gray-900">{selectedRun.run_type}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-gray-500">Strategy</dt>
                    <dd className="text-gray-900">{selectedRun.strategy}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-gray-500">Agent</dt>
                    <dd className="text-gray-900">{selectedRun.agent_id || 'N/A'}</dd>
                  </div>
                  {selectedRun.target_scope && (
                    <div className="flex justify-between">
                      <dt className="text-gray-500">Scope</dt>
                      <dd className="text-gray-900">{selectedRun.target_scope}</dd>
                    </div>
                  )}
                </dl>
              </div>

              {/* Tabbed panel: Activity / Evidence / Artifacts */}
              <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
                {/* Tab bar */}
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
                  <button
                    onClick={() => setActiveTab('artifacts')}
                    className={`flex-1 px-4 py-2.5 text-xs font-medium transition-colors ${
                      activeTab === 'artifacts'
                        ? 'text-indigo-600 border-b-2 border-indigo-600 bg-indigo-50/50'
                        : 'text-gray-500 hover:text-gray-700'
                    }`}
                  >
                    Artifacts
                  </button>
                </div>

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
                        <span className="text-xs text-gray-500">
                          {selectedRun.status === 'passed' ? 'Completed' :
                           selectedRun.status === 'failed' ? 'Failed' :
                           selectedRun.status === 'error' ? 'Error' :
                           selectedRun.status === 'cancelled' ? 'Cancelled' : ''}
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
                      {/* Blinking cursor */}
                      {isRunning && (
                        <span className="inline-block w-2 h-4 bg-gray-400 terminal-cursor mt-1" />
                      )}
                    </div>
                  </div>
                )}

                {/* Evidence tab */}
                {activeTab === 'evidence' && (
                  <div className="p-4">
                    {evidences.length === 0 ? (
                      <p className="text-sm text-gray-500">No evidence collected yet.</p>
                    ) : (
                      <div className="space-y-2 max-h-96 overflow-y-auto">
                        {evidences.map((ev) => (
                          <div key={ev.id} className="border border-gray-100 rounded p-3">
                            <div className="flex items-center gap-2 mb-1">
                              <span className="text-xs bg-gray-100 px-2 py-0.5 rounded">
                                {ev.evidence_type}
                              </span>
                              <span className="text-xs font-medium text-gray-700">{ev.title}</span>
                            </div>
                            {ev.content && (
                              <pre className="text-xs text-gray-600 whitespace-pre-wrap mt-1 max-h-32 overflow-y-auto bg-gray-50 p-2 rounded">
                                {ev.content}
                              </pre>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}

                {/* Artifacts tab */}
                {activeTab === 'artifacts' && (
                  <div className="p-4">
                    {selectedRun.artifacts && Object.keys(selectedRun.artifacts).length > 0 ? (
                      <ul className="space-y-1 text-sm">
                        {Object.entries(selectedRun.artifacts).map(([key, val]) => (
                          <li key={key} className="flex justify-between text-gray-600">
                            <span>{key}</span>
                            <span className="font-mono text-xs">{String(val)}</span>
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="text-sm text-gray-500">No artifacts yet.</p>
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
