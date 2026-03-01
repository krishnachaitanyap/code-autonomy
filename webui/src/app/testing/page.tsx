'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { testing, workflows as workflowsApi, type TestProject, type TestingStats, type TestRun, type Workflow } from '@/lib/api';

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

const STATUS_COLORS: Record<string, string> = {
  ready:     'bg-green-100 text-green-700',
  pending:   'bg-yellow-100 text-yellow-700',
  indexing:  'bg-blue-100 text-blue-700',
  error:     'bg-red-100 text-red-700',
  passed:    'bg-green-100 text-green-700',
  running:   'bg-blue-100 text-blue-700',
  failed:    'bg-red-100 text-red-700',
  queued:    'bg-gray-100 text-gray-600',
  completed: 'bg-green-100 text-green-700',
  paused:    'bg-amber-100 text-amber-700',
  planning:  'bg-gray-100 text-gray-600',
  cancelled: 'bg-yellow-100 text-yellow-700',
};

const RUN_TYPE_COLORS: Record<string, string> = {
  functional: 'bg-blue-50 text-blue-700',
  security:   'bg-red-50 text-red-700',
  regression: 'bg-amber-50 text-amber-700',
  smoke:      'bg-gray-100 text-gray-700',
};

// ---------------------------------------------------------------------------
// Quick nav links
// ---------------------------------------------------------------------------

const QUICK_LINKS = [
  { href: '/testing/agents', label: 'Agents', icon: '\u{1F916}' },
  { href: '/testing/coverage', label: 'Coverage', icon: '\u{1F4CA}' },
  { href: '/testing/chat', label: 'Chat', icon: '\u{1F4AC}' },
  { href: '/testing/data-injection', label: 'Data Injection', icon: '\u{1F4BE}' },
  { href: '/testing/custom-steps', label: 'Custom Steps', icon: '\u{1F527}' },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function TestingDashboard() {
  const [projects, setProjects] = useState<TestProject[]>([]);
  const [stats, setStats] = useState<TestingStats | null>(null);
  const [recentRuns, setRecentRuns] = useState<TestRun[]>([]);
  const [recentWorkflows, setRecentWorkflows] = useState<Workflow[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const [p, s, r, w] = await Promise.all([
          testing.listProjects({ limit: 20 }),
          testing.stats(),
          testing.listRuns({ limit: 5 }),
          workflowsApi.list({ limit: 5 }).catch(() => ({ workflows: [] })),
        ]);
        setProjects(p.projects);
        setStats(s);
        setRecentRuns(r.runs);
        setRecentWorkflows(w.workflows || []);
      } catch (err) {
        console.error('Failed to load testing dashboard:', err);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="flex items-center gap-3 text-gray-500">
          <svg className="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          Loading testing platform...
        </div>
      </div>
    );
  }

  const readyCount = projects.filter((p) => p.status === 'ready').length;

  return (
    <div className="space-y-6">
      {/* ---- Header ---- */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Testing Platform</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {projects.length} project{projects.length !== 1 ? 's' : ''}
            {readyCount > 0 && <> &middot; {readyCount} ready</>}
            {stats && stats.success_rate > 0 && <> &middot; {stats.success_rate}% success rate</>}
            {stats && stats.avg_coverage > 0 && <> &middot; {stats.avg_coverage}% avg coverage</>}
          </p>
        </div>
        <Link
          href="/testing/onboard"
          data-tour="onboard"
          className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 transition-colors"
        >
          + Onboard Repository
        </Link>
      </div>

      {/* ---- Quick Links ---- */}
      <div className="flex gap-2 flex-wrap">
        {QUICK_LINKS.map((link) => (
          <Link
            key={link.href}
            href={link.href}
            data-tour={link.label.toLowerCase().replace(/\s+/g, '')}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-white border border-gray-200 rounded-lg text-sm text-gray-700 hover:bg-gray-50 hover:shadow-sm transition-all"
          >
            <span>{link.icon}</span>
            <span>{link.label}</span>
          </Link>
        ))}
      </div>

      {/* ---- Onboarded Projects ---- */}
      <div data-tour="projects">
        <h2 className="text-sm font-semibold text-gray-700 mb-3">
          Onboarded Projects ({projects.length})
        </h2>
        {projects.length === 0 ? (
          <div className="bg-white rounded-lg border border-gray-200 p-8 text-center">
            <p className="text-gray-500 mb-4">No projects onboarded yet.</p>
            <Link
              href="/testing/onboard"
              className="px-4 py-2 bg-indigo-600 text-white rounded-md text-sm font-medium hover:bg-indigo-700"
            >
              Onboard Your First Repository
            </Link>
          </div>
        ) : (
          <div className="bg-white rounded-lg border border-gray-200 divide-y divide-gray-100">
            {projects.map((project) => (
              <div
                key={project.id}
                className="flex items-center gap-3 px-4 py-3 hover:bg-gray-50 transition-colors"
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <h3 className="font-medium text-gray-900 text-sm">{project.name}</h3>
                    <span className={`px-2 py-0.5 rounded text-[10px] font-medium ${STATUS_COLORS[project.status] || 'bg-gray-100 text-gray-600'}`}>
                      {project.status}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 mt-0.5">
                    <span className="text-xs text-gray-400 truncate">{project.repo_url || project.local_path}</span>
                  </div>
                  <div className="flex gap-3 mt-1 text-[11px] text-gray-400">
                    <span>{project.language}</span>
                    <span>{project.framework}</span>
                    <span>{project.testing_framework}</span>
                  </div>
                </div>
                <div className="flex gap-1.5 flex-shrink-0">
                  <Link
                    href={`/testing/coverage?project=${project.id}`}
                    className="px-2.5 py-1 text-[11px] font-medium bg-gray-100 text-gray-600 rounded hover:bg-gray-200 transition-colors"
                  >
                    Coverage
                  </Link>
                  <Link
                    href={`/testing/agents?project=${project.id}`}
                    className="px-2.5 py-1 text-[11px] font-medium bg-gray-100 text-gray-600 rounded hover:bg-gray-200 transition-colors"
                  >
                    Runs
                  </Link>
                  <Link
                    href={`/testing/chat?project=${project.id}`}
                    className="px-2.5 py-1 text-[11px] font-medium bg-indigo-50 text-indigo-700 rounded hover:bg-indigo-100 transition-colors"
                  >
                    Chat
                  </Link>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ---- Recent Test Runs ---- */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-gray-700">Recent Test Runs</h2>
          <Link href="/testing/agents" className="text-xs text-indigo-600 hover:text-indigo-800">
            View all
          </Link>
        </div>
        {recentRuns.length === 0 ? (
          <div className="bg-white rounded-lg border border-gray-200 p-6 text-center text-sm text-gray-500">
            No test runs yet. <Link href="/testing/agents" className="text-indigo-600">Create one</Link>
          </div>
        ) : (
          <div className="bg-white rounded-lg border border-gray-200 divide-y divide-gray-100">
            {recentRuns.map((run) => (
              <Link
                key={run.id}
                href="/testing/agents"
                className="flex items-center gap-3 px-4 py-3 hover:bg-gray-50 transition-colors"
              >
                <span className={`px-2 py-0.5 rounded text-[10px] font-medium flex-shrink-0 ${RUN_TYPE_COLORS[run.run_type] || 'bg-gray-100 text-gray-700'}`}>
                  {run.run_type}
                </span>
                <span className={`px-2 py-0.5 rounded text-[10px] font-medium flex-shrink-0 ${STATUS_COLORS[run.status] || 'bg-gray-100 text-gray-600'}`}>
                  {run.status === 'running' && <span className="inline-block w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse mr-1 align-middle" />}
                  {run.status}
                </span>
                <span className="text-sm text-gray-700 truncate flex-1 min-w-0">
                  {run.target_scope || run.strategy}
                </span>
                {run.total_tests > 0 && (
                  <span className="text-xs text-gray-400 flex-shrink-0">
                    <span className="text-green-600">{run.passed_tests}</span>
                    /
                    <span className="text-red-600">{run.failed_tests}</span>
                    /
                    {run.total_tests}
                  </span>
                )}
                {run.status === 'running' && run.progress_pct > 0 && (
                  <div className="w-16 h-1.5 bg-gray-200 rounded-full overflow-hidden flex-shrink-0">
                    <div className="h-full bg-blue-500 rounded-full" style={{ width: `${run.progress_pct}%` }} />
                  </div>
                )}
                <span className="text-xs text-gray-400 flex-shrink-0 w-14 text-right">
                  {timeAgo(run.created_at)}
                </span>
              </Link>
            ))}
          </div>
        )}
      </div>
      {/* ---- Recent Workflows ---- */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-gray-700">Recent Workflows</h2>
          <Link href="/testing/agents" className="text-xs text-indigo-600 hover:text-indigo-800">
            View all
          </Link>
        </div>
        {recentWorkflows.length === 0 ? (
          <div className="bg-white rounded-lg border border-gray-200 p-6 text-center text-sm text-gray-500">
            No workflows yet. <Link href="/testing/agents" className="text-indigo-600">Create one</Link>
          </div>
        ) : (
          <div className="bg-white rounded-lg border border-gray-200 divide-y divide-gray-100">
            {recentWorkflows.map((wf) => (
              <Link
                key={wf.id}
                href="/testing/agents"
                className="flex items-center gap-3 px-4 py-3 hover:bg-gray-50 transition-colors"
              >
                <span className="px-2 py-0.5 rounded text-[10px] font-medium flex-shrink-0 bg-teal-100 text-teal-700">
                  {wf.mode}
                </span>
                <span className={`px-2 py-0.5 rounded text-[10px] font-medium flex-shrink-0 ${STATUS_COLORS[wf.status] || 'bg-gray-100 text-gray-600'}`}>
                  {wf.status === 'running' && <span className="inline-block w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse mr-1 align-middle" />}
                  {wf.status}
                </span>
                <span className="text-sm text-gray-700 truncate flex-1 min-w-0">
                  {wf.goal?.slice(0, 60)}{wf.goal && wf.goal.length > 60 ? '...' : ''}
                </span>
                {wf.subtasks.length > 0 && (
                  <span className="text-xs text-gray-400 flex-shrink-0">
                    {wf.subtasks.filter(s => s.status === 'completed').length}/{wf.subtasks.length} steps
                  </span>
                )}
                {wf.total_tokens_used > 0 && (
                  <span className="text-xs text-gray-400 flex-shrink-0 font-mono">
                    {wf.total_tokens_used.toLocaleString()} tok
                  </span>
                )}
                {wf.status === 'running' && wf.progress_pct > 0 && (
                  <div className="w-16 h-1.5 bg-gray-200 rounded-full overflow-hidden flex-shrink-0">
                    <div className="h-full bg-teal-500 rounded-full" style={{ width: `${wf.progress_pct}%` }} />
                  </div>
                )}
                <span className="text-xs text-gray-400 flex-shrink-0 w-14 text-right">
                  {timeAgo(wf.created_at)}
                </span>
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
