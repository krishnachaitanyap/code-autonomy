'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import Link from 'next/link';
import { repos, sessions, traces, testing, jira, workflows as workflowsApi, type Repo, type Session, type UsageStats, type TestingStats, type TestRun, type JiraRun, type Workflow } from '@/lib/api';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function timeAgo(dateStr: string): string {
  if (!dateStr) return '';
  const seconds = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000);
  if (seconds < 60) return 'just now';
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

const MODE_COLORS: Record<string, string> = {
  ask:   'bg-blue-100 text-blue-700',
  plan:  'bg-amber-100 text-amber-700',
  agent: 'bg-green-100 text-green-700',
};

const STATUS_COLORS: Record<string, string> = {
  completed: 'bg-green-100 text-green-700',
  running:   'bg-blue-100 text-blue-700',
  failed:    'bg-red-100 text-red-700',
  paused:    'bg-yellow-100 text-yellow-700',
  passed:    'bg-green-100 text-green-700',
  queued:    'bg-gray-100 text-gray-600',
  error:     'bg-red-100 text-red-700',
  planning:  'bg-gray-100 text-gray-600',
  cancelled: 'bg-yellow-100 text-yellow-700',
};

const TOOL_ICONS: Record<string, { icon: string; color: string }> = {
  read_file:      { icon: '\u{1F4D6}', color: 'text-blue-400' },
  grep:           { icon: '\u{1F50D}', color: 'text-purple-400' },
  find_files:     { icon: '\u{1F50D}', color: 'text-purple-400' },
  list_dir:       { icon: '\u{1F4C2}', color: 'text-blue-300' },
  edit_file:      { icon: '\u270F\uFE0F', color: 'text-yellow-400' },
  write_file:     { icon: '\u270F\uFE0F', color: 'text-yellow-400' },
  run_command:    { icon: '\u26A1', color: 'text-orange-400' },
  propose_change: { icon: '\u{1F4DD}', color: 'text-green-400' },
};

// ---------------------------------------------------------------------------
// Quick Action Cards data
// ---------------------------------------------------------------------------

const QUICK_ACTIONS = [
  {
    href: '/testing/chat',
    label: 'Chat',
    desc: 'Ask, Plan, or Agent \u2014 any codebase',
    icon: '\u{1F4AC}',
    iconBg: 'bg-blue-100',
    iconColor: 'text-blue-600',
  },
  {
    href: '/testing/agents',
    label: 'Agents',
    desc: 'Monitor running agents & results',
    icon: '\u{1F916}',
    iconBg: 'bg-green-100',
    iconColor: 'text-green-600',
  },
  {
    href: '/testing/agents',
    label: 'JIRA',
    desc: 'Story-to-PR automation',
    icon: '\u{1F4CB}',
    iconBg: 'bg-amber-100',
    iconColor: 'text-amber-600',
  },
  {
    href: '/testing',
    label: 'Testing',
    desc: 'Projects, runs & test strategy',
    icon: '\u{1F9EA}',
    iconBg: 'bg-purple-100',
    iconColor: 'text-purple-600',
  },
  {
    href: '/testing/coverage',
    label: 'Coverage',
    desc: 'Gap analysis & suggestions',
    icon: '\u{1F4CA}',
    iconBg: 'bg-cyan-100',
    iconColor: 'text-cyan-600',
  },
  {
    href: '/config',
    label: 'Config',
    desc: 'LLM keys, agent settings',
    icon: '\u2699\uFE0F',
    iconBg: 'bg-gray-100',
    iconColor: 'text-gray-600',
  },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function Dashboard() {
  const [repoList, setRepoList] = useState<Repo[]>([]);
  const [recentSessions, setRecentSessions] = useState<Session[]>([]);
  const [traceStats, setTraceStats] = useState<UsageStats | null>(null);
  const [testingStats, setTestingStats] = useState<TestingStats | null>(null);
  const [runningSessions, setRunningSessions] = useState<Session[]>([]);
  const [runningTestRuns, setRunningTestRuns] = useState<TestRun[]>([]);
  const [runningJiraRuns, setRunningJiraRuns] = useState<JiraRun[]>([]);
  const [runningWorkflows, setRunningWorkflows] = useState<Workflow[]>([]);
  const [loading, setLoading] = useState(true);
  const refreshRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Initial load
  useEffect(() => {
    loadAll().finally(() => setLoading(false));
  }, []);

  // Auto-refresh live activity every 10s
  useEffect(() => {
    refreshRef.current = setInterval(refreshLiveActivity, 10000);
    return () => { if (refreshRef.current) clearInterval(refreshRef.current); };
  }, []);

  async function loadAll() {
    try {
      const [r, s, ts, testS, rs, rtr, rjr, rwf] = await Promise.all([
        repos.list().catch(() => []),
        sessions.list({ limit: 8 }).catch(() => ({ sessions: [] })),
        traces.stats().catch(() => null),
        testing.stats().catch(() => null),
        sessions.list({ status: 'running', limit: 5 }).catch(() => ({ sessions: [] })),
        testing.listRuns({ status: 'running', limit: 5 }).catch(() => ({ runs: [] })),
        jira.listRuns({ status: 'running', limit: 5 }).catch(() => ({ runs: [] })),
        workflowsApi.list({ status: 'running', limit: 5 }).catch(() => ({ workflows: [] })),
      ]);
      setRepoList(Array.isArray(r) ? r : []);
      setRecentSessions(s.sessions || []);
      setTraceStats(ts);
      setTestingStats(testS);
      setRunningSessions(rs.sessions || []);
      setRunningTestRuns(rtr.runs || []);
      setRunningJiraRuns(rjr.runs || []);
      setRunningWorkflows(rwf.workflows || []);
    } catch (err) {
      console.error('Dashboard load error:', err);
    }
  }

  async function refreshLiveActivity() {
    try {
      const [rs, rtr, rjr, rwf] = await Promise.all([
        sessions.list({ status: 'running', limit: 5 }).catch(() => ({ sessions: [] })),
        testing.listRuns({ status: 'running', limit: 5 }).catch(() => ({ runs: [] })),
        jira.listRuns({ status: 'running', limit: 5 }).catch(() => ({ runs: [] })),
        workflowsApi.list({ status: 'running', limit: 5 }).catch(() => ({ workflows: [] })),
      ]);
      setRunningSessions(rs.sessions || []);
      setRunningTestRuns(rtr.runs || []);
      setRunningJiraRuns(rjr.runs || []);
      setRunningWorkflows(rwf.workflows || []);
    } catch { /* ignore refresh errors */ }
  }

  const liveCount = runningSessions.length + runningTestRuns.length + runningJiraRuns.length + runningWorkflows.length;

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="flex items-center gap-3 text-gray-500">
          <svg className="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          Loading dashboard...
        </div>
      </div>
    );
  }

  // Build stat cards
  const statCards = [
    {
      label: 'Sessions',
      value: traceStats?.total_sessions ?? 0,
      color: 'text-indigo-600',
      sub: traceStats ? `${traceStats.successful_sessions} successful` : undefined,
    },
    {
      label: 'Success Rate',
      value: traceStats ? `${(traceStats.success_rate * 100).toFixed(1)}%` : '---',
      color: traceStats && traceStats.success_rate >= 0.8 ? 'text-green-600' : 'text-amber-600',
    },
    {
      label: 'Repos',
      value: repoList.length,
      color: 'text-blue-600',
    },
    {
      label: 'Test Runs',
      value: testingStats?.total_runs ?? 0,
      color: 'text-purple-600',
      badge: testingStats?.running_runs ? `${testingStats.running_runs} running` : undefined,
    },
    {
      label: 'Tokens Used',
      value: traceStats ? traceStats.total_tokens.toLocaleString() : '0',
      color: 'text-gray-700',
      sub: traceStats ? `$${traceStats.total_cost.toFixed(2)}` : undefined,
    },
  ];

  return (
    <div className="space-y-6">
      {/* ---- Header ---- */}
      <div className="flex items-center justify-between" data-tour="welcome">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
          <p className="text-sm text-gray-500 mt-0.5">AI-powered code generation & analysis</p>
        </div>
        <Link
          href="/repos"
          className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 transition-colors"
        >
          + Add Repo
        </Link>
      </div>

      {/* ---- Stat Cards ---- */}
      <div data-tour="stats" className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        {statCards.map((card) => (
          <div
            key={card.label}
            className="bg-white rounded-lg border border-gray-200 p-4 hover:shadow-sm transition-shadow"
          >
            <p className="text-xs text-gray-500 uppercase tracking-wide">{card.label}</p>
            <div className="flex items-baseline gap-2 mt-1">
              <p className={`text-2xl font-bold ${card.color}`}>{card.value}</p>
              {card.badge && (
                <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-blue-100 text-blue-700">
                  <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
                  {card.badge}
                </span>
              )}
            </div>
            {card.sub && (
              <p className="text-[11px] text-gray-400 mt-0.5">{card.sub}</p>
            )}
          </div>
        ))}
      </div>

      {/* ---- Quick Actions + Live Activity ---- */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
        {/* Quick Actions (3 cols) */}
        <div className="lg:col-span-3">
          <h2 className="text-sm font-semibold text-gray-700 mb-3">Quick Actions</h2>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            {QUICK_ACTIONS.map((action) => (
              <Link
                key={action.label}
                href={action.href}
                data-tour={action.label.toLowerCase()}
                className="bg-white rounded-lg border border-gray-200 p-4 hover:shadow-md transition-shadow group"
              >
                <div className={`w-10 h-10 rounded-lg ${action.iconBg} flex items-center justify-center text-lg mb-2.5 group-hover:scale-110 transition-transform`}>
                  {action.icon}
                </div>
                <p className="font-medium text-gray-900 text-sm">{action.label}</p>
                <p className="text-xs text-gray-500 mt-0.5">{action.desc}</p>
              </Link>
            ))}
          </div>
        </div>

        {/* Live Activity (2 cols) */}
        <div className="lg:col-span-2">
          <div className="flex items-center gap-2 mb-3">
            <h2 className="text-sm font-semibold text-gray-700">Live Activity</h2>
            {liveCount > 0 && (
              <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
            )}
          </div>
          <div className="bg-gray-900 rounded-lg p-4 min-h-[280px] flex flex-col">
            {liveCount === 0 ? (
              <div className="flex-1 flex flex-col items-center justify-center text-gray-500">
                <div className="text-3xl mb-3 opacity-50">{'\u2615'}</div>
                <p className="text-sm">All quiet</p>
                <p className="text-xs mt-1">Start a session from <Link href="/testing/chat" className="text-indigo-400 hover:text-indigo-300">Chat</Link></p>
              </div>
            ) : (
              <div className="space-y-3 font-mono text-xs overflow-y-auto flex-1">
                {/* Running Sessions */}
                {runningSessions.map((s) => (
                  <Link key={s.id} href={`/sessions/${s.id}`} className="block hover:bg-gray-800 rounded p-2 -m-1 transition-colors">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-blue-400 animate-pulse">{'\u27F3'}</span>
                      <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${MODE_COLORS[s.mode] || 'bg-gray-700 text-gray-300'}`}>
                        {s.mode}
                      </span>
                      <span className="text-gray-400 truncate flex-1">{s.requirements?.slice(0, 40)}{s.requirements && s.requirements.length > 40 ? '...' : ''}</span>
                      <span className="text-gray-600 flex-shrink-0">T{s.turns_used}</span>
                    </div>
                    {/* Show last log entries */}
                    {s.log && s.log.length > 0 && (
                      <div className="ml-5 space-y-0.5">
                        {s.log.slice(-3).map((entry: any, i: number) => {
                          const meta = TOOL_ICONS[entry.tool] || { icon: '\u25B8', color: 'text-gray-500' };
                          return (
                            <div key={i} className={`flex items-center gap-1.5 ${meta.color}`}>
                              <span className="flex-shrink-0 text-[10px]">{meta.icon}</span>
                              <span className="text-gray-500 truncate">{entry.tool} {entry.detail || ''}</span>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </Link>
                ))}

                {/* Running Test Runs */}
                {runningTestRuns.map((r) => (
                  <Link key={r.id} href="/testing/agents" className="block hover:bg-gray-800 rounded p-2 -m-1 transition-colors">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-purple-400 animate-pulse">{'\u27F3'}</span>
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-purple-900 text-purple-300">
                        test:{r.run_type}
                      </span>
                      <span className="text-gray-400 truncate flex-1">{r.target_scope || r.strategy}</span>
                    </div>
                    <div className="ml-5 flex items-center gap-2">
                      {/* Progress bar */}
                      <div className="flex-1 h-1.5 bg-gray-700 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-purple-500 rounded-full transition-all"
                          style={{ width: `${r.progress_pct}%` }}
                        />
                      </div>
                      <span className="text-gray-500 text-[10px] flex-shrink-0">
                        <span className="text-green-400">{r.passed_tests}</span>/<span className="text-red-400">{r.failed_tests}</span>/{r.total_tests}
                      </span>
                    </div>
                  </Link>
                ))}

                {/* Running JIRA Runs */}
                {runningJiraRuns.map((r) => (
                  <Link key={r.id} href="/testing/agents" className="block hover:bg-gray-800 rounded p-2 -m-1 transition-colors">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-amber-400 animate-pulse">{'\u27F3'}</span>
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-900 text-amber-300">
                        jira
                      </span>
                      <span className="text-gray-400 truncate flex-1">{r.jira_project || 'JIRA Run'}</span>
                    </div>
                    <div className="ml-5 flex items-center gap-2">
                      <div className="flex-1 h-1.5 bg-gray-700 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-amber-500 rounded-full transition-all"
                          style={{ width: `${r.total_stories > 0 ? (r.completed_stories / r.total_stories) * 100 : 0}%` }}
                        />
                      </div>
                      <span className="text-gray-500 text-[10px] flex-shrink-0">
                        {r.completed_stories}/{r.total_stories} stories
                      </span>
                    </div>
                  </Link>
                ))}

                {/* Running Workflows */}
                {runningWorkflows.map((w) => (
                  <Link key={w.id} href="/testing/agents" className="block hover:bg-gray-800 rounded p-2 -m-1 transition-colors">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-teal-400 animate-pulse">{'\u27F3'}</span>
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-teal-900 text-teal-300">
                        workflow
                      </span>
                      <span className="text-gray-400 truncate flex-1">{w.goal?.slice(0, 40)}{w.goal && w.goal.length > 40 ? '...' : ''}</span>
                    </div>
                    <div className="ml-5 flex items-center gap-2">
                      <div className="flex-1 h-1.5 bg-gray-700 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-teal-500 rounded-full transition-all"
                          style={{ width: `${w.progress_pct}%` }}
                        />
                      </div>
                      <span className="text-gray-500 text-[10px] flex-shrink-0">
                        Step {w.current_step + 1}/{w.subtasks.length}
                      </span>
                      {w.total_tokens_used > 0 && (
                        <span className="text-gray-600 text-[10px] flex-shrink-0 font-mono">
                          {w.total_tokens_used.toLocaleString()} tok
                        </span>
                      )}
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ---- Recent Sessions ---- */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-gray-700">Recent Sessions</h2>
          <Link href="/sessions" className="text-xs text-indigo-600 hover:text-indigo-800">
            View all
          </Link>
        </div>
        {recentSessions.length === 0 ? (
          <div className="bg-white rounded-lg border border-gray-200 p-6 text-center text-sm text-gray-500">
            No sessions yet. <Link href="/testing/chat" className="text-indigo-600">Start a conversation</Link>
          </div>
        ) : (
          <div className="bg-white rounded-lg border border-gray-200 divide-y divide-gray-100">
            {recentSessions.map((session) => (
              <Link
                key={session.id}
                href={`/sessions/${session.id}`}
                className="flex items-center gap-3 px-4 py-3 hover:bg-gray-50 transition-colors"
              >
                <span className={`px-2 py-0.5 rounded text-[10px] font-medium flex-shrink-0 ${MODE_COLORS[session.mode] || 'bg-gray-100 text-gray-600'}`}>
                  {session.mode}
                </span>
                <span className={`px-2 py-0.5 rounded text-[10px] font-medium flex-shrink-0 ${STATUS_COLORS[session.status] || 'bg-gray-100 text-gray-600'}`}>
                  {session.status === 'running' && <span className="inline-block w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse mr-1 align-middle" />}
                  {session.status}
                </span>
                <span className="text-sm text-gray-700 truncate flex-1 min-w-0">
                  {session.requirements || '(no description)'}
                </span>
                {session.turns_used > 0 && (
                  <span className="text-xs text-gray-400 flex-shrink-0">{session.turns_used} turns</span>
                )}
                <span className="text-xs text-gray-400 flex-shrink-0 w-16 text-right">
                  {timeAgo(session.created_at)}
                </span>
              </Link>
            ))}
          </div>
        )}
      </div>

      {/* ---- Repositories ---- */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-gray-700">Repositories ({repoList.length})</h2>
          <Link href="/repos" className="text-xs text-indigo-600 hover:text-indigo-800">
            Manage
          </Link>
        </div>
        {repoList.length === 0 ? (
          <div className="bg-white rounded-lg border border-gray-200 p-6 text-center text-sm text-gray-500">
            No repos registered.{' '}
            <Link href="/repos" className="text-indigo-600">Add one</Link>
          </div>
        ) : (
          <div className="bg-white rounded-lg border border-gray-200 divide-y divide-gray-100">
            {repoList.map((repo) => (
              <div
                key={repo.id}
                className="flex items-center gap-3 px-4 py-3 hover:bg-gray-50 transition-colors"
              >
                <span className={`px-2 py-0.5 rounded text-[10px] font-medium flex-shrink-0 ${
                  repo.platform === 'github' ? 'bg-gray-900 text-white' :
                  repo.platform === 'bitbucket' ? 'bg-blue-700 text-white' :
                  'bg-gray-200 text-gray-700'
                }`}>
                  {repo.platform}
                </span>
                <span className="text-sm text-gray-700 truncate flex-1 min-w-0">
                  {repo.url || repo.local_path}
                </span>
                <div className="flex gap-1.5 flex-shrink-0">
                  <Link
                    href="/testing/chat"
                    className="px-2.5 py-1 text-[11px] font-medium bg-indigo-50 text-indigo-700 rounded hover:bg-indigo-100 transition-colors"
                  >
                    Chat
                  </Link>
                  <Link
                    href="/testing/agents"
                    className="px-2.5 py-1 text-[11px] font-medium bg-gray-100 text-gray-600 rounded hover:bg-gray-200 transition-colors"
                  >
                    Runs
                  </Link>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
