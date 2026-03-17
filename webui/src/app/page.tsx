'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import {
  repos, testing, migrations, models,
  type Repo, type TestingStats, type MigrationStats, type ModelConfig,
} from '@/lib/api';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const PROVIDER_DOT: Record<string, string> = {
  openai: 'bg-green-500', anthropic: 'bg-orange-500', gemini: 'bg-blue-500',
  google: 'bg-blue-500', azure: 'bg-cyan-500', bedrock: 'bg-purple-500', cdao: 'bg-purple-500',
};

const PLATFORM_STYLE: Record<string, string> = {
  github: 'bg-gray-900 text-white',
  bitbucket: 'bg-blue-700 text-white',
  local: 'bg-gray-200 text-gray-700',
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function Dashboard() {
  const [repoList, setRepoList] = useState<Repo[]>([]);
  const [testingStats, setTestingStats] = useState<TestingStats | null>(null);
  const [migrationStats, setMigrationStats] = useState<MigrationStats | null>(null);
  const [activeModel, setActiveModel] = useState<ModelConfig | null>(null);
  const [modelCount, setModelCount] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadAll().finally(() => setLoading(false));
  }, []);

  async function loadAll() {
    try {
      const [r, testS, migS, mdls] = await Promise.all([
        repos.list().catch(() => []),
        testing.stats().catch(() => null),
        migrations.stats().catch(() => null),
        models.list().catch(() => ({ models: [], total: 0 })),
      ]);
      setRepoList(Array.isArray(r) ? r : []);
      setTestingStats(testS);
      setMigrationStats(migS);
      const modelList = mdls.models || [];
      setModelCount(modelList.length);
      setActiveModel(modelList.find((m: ModelConfig) => m.is_default) || modelList[0] || null);
    } catch (err) {
      console.error('Dashboard load error:', err);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="flex items-center gap-3 text-gray-500">
          <svg className="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          Loading...
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* ---- Header ---- */}
      <div className="flex items-center justify-between" data-tour="welcome">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
          <p className="text-sm text-gray-500 mt-0.5">AI-powered code generation & analysis</p>
        </div>
        <div className="flex items-center gap-3">
          {activeModel && (
            <Link href="/config" className="flex items-center gap-2 px-3 py-1.5 bg-white border border-gray-200 rounded-lg hover:bg-gray-50 transition-colors">
              <span className={`w-2 h-2 rounded-full ${PROVIDER_DOT[activeModel.provider] || 'bg-gray-400'}`} />
              <span className="text-xs text-gray-600">{activeModel.label}</span>
              {modelCount > 1 && <span className="text-[10px] text-gray-400">+{modelCount - 1}</span>}
            </Link>
          )}
          <Link
            href="/repos"
            className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 transition-colors"
          >
            + Add Repo
          </Link>
        </div>
      </div>

      {/* ---- Primary Actions — Chat & Agents (hero row) ---- */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <Link
          href="/testing/chat"
          data-tour="chat"
          className="relative overflow-hidden bg-gradient-to-br from-blue-50 to-indigo-50 rounded-xl border border-blue-200 p-6 hover:shadow-lg transition-all group"
        >
          <div className="flex items-start gap-4">
            <div className="w-12 h-12 rounded-xl bg-blue-100 flex items-center justify-center text-2xl group-hover:scale-110 transition-transform">
              {'\u{1F4AC}'}
            </div>
            <div>
              <h3 className="text-lg font-semibold text-gray-900">Chat</h3>
              <p className="text-sm text-gray-600 mt-1">Ask questions, generate plans, or run autonomous coding agents on any codebase</p>
              <div className="flex gap-2 mt-3">
                <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-blue-100 text-blue-700">Ask</span>
                <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-amber-100 text-amber-700">Plan</span>
                <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-green-100 text-green-700">Agent</span>
              </div>
            </div>
          </div>
        </Link>

        <Link
          href="/testing/agents"
          data-tour="agents"
          className="relative overflow-hidden bg-gradient-to-br from-green-50 to-emerald-50 rounded-xl border border-green-200 p-6 hover:shadow-lg transition-all group"
        >
          <div className="flex items-start gap-4">
            <div className="w-12 h-12 rounded-xl bg-green-100 flex items-center justify-center text-2xl group-hover:scale-110 transition-transform">
              {'\u{1F916}'}
            </div>
            <div>
              <h3 className="text-lg font-semibold text-gray-900">Agents</h3>
              <p className="text-sm text-gray-600 mt-1">Monitor running agents, view results, and launch new test, JIRA, or workflow runs</p>
              {(testingStats?.running_runs ?? 0) > 0 && (
                <div className="mt-3">
                  <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-medium bg-green-100 text-green-700">
                    <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />
                    {testingStats!.running_runs} running
                  </span>
                </div>
              )}
            </div>
          </div>
        </Link>
      </div>

      {/* ---- Two-column: Features + Repos ---- */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">

        {/* Left: Feature cards (3 cols) */}
        <div className="lg:col-span-3 space-y-4">
          {/* Testing & Migration stats row */}
          <div className="grid grid-cols-2 gap-3" data-tour="stats">
            <div className="bg-white rounded-lg border border-gray-200 p-4">
              <div className="flex items-center justify-between">
                <p className="text-xs text-gray-500 uppercase tracking-wide">Test Runs</p>
                <Link href="/testing" className="text-[10px] text-indigo-600 hover:text-indigo-800">View all</Link>
              </div>
              <p className="text-2xl font-bold text-purple-600 mt-1">{testingStats?.total_runs ?? 0}</p>
              {testingStats && (
                <div className="flex items-center gap-2 mt-1">
                  <p className="text-[11px] text-gray-400">{Math.round(testingStats.success_rate * 100)}% pass rate</p>
                  {testingStats.running_runs > 0 && (
                    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-blue-100 text-blue-700">
                      <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
                      {testingStats.running_runs} running
                    </span>
                  )}
                </div>
              )}
            </div>
            <div className="bg-white rounded-lg border border-gray-200 p-4">
              <div className="flex items-center justify-between">
                <p className="text-xs text-gray-500 uppercase tracking-wide">Migrations</p>
                <Link href="/migration" className="text-[10px] text-indigo-600 hover:text-indigo-800">View all</Link>
              </div>
              <p className="text-2xl font-bold text-indigo-600 mt-1">{migrationStats?.total_projects ?? 0}</p>
              {migrationStats && (
                <div className="flex items-center gap-2 mt-1">
                  <p className="text-[11px] text-gray-400">{migrationStats.completed_runs} completed</p>
                  {migrationStats.running_runs > 0 && (
                    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-medium bg-blue-100 text-blue-700">
                      <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
                      {migrationStats.running_runs} running
                    </span>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Feature grid — 2x2 */}
          <div className="grid grid-cols-2 gap-3">
            <Link
              href="/testing"
              data-tour="testing"
              className="bg-white rounded-lg border border-gray-200 p-4 hover:shadow-md transition-shadow group"
            >
              <div className="w-9 h-9 rounded-lg bg-purple-100 flex items-center justify-center text-base mb-2 group-hover:scale-110 transition-transform">
                {'\u{1F9EA}'}
              </div>
              <p className="font-medium text-gray-900 text-sm">Testing</p>
              <p className="text-xs text-gray-500 mt-0.5">Projects, runs & test strategy</p>
            </Link>
            <Link
              href="/testing/coverage"
              data-tour="coverage"
              className="bg-white rounded-lg border border-gray-200 p-4 hover:shadow-md transition-shadow group"
            >
              <div className="w-9 h-9 rounded-lg bg-cyan-100 flex items-center justify-center text-base mb-2 group-hover:scale-110 transition-transform">
                {'\u{1F4CA}'}
              </div>
              <p className="font-medium text-gray-900 text-sm">Coverage</p>
              <p className="text-xs text-gray-500 mt-0.5">Gap analysis & suggestions</p>
            </Link>
            <Link
              href="/migration"
              data-tour="recipes"
              className="bg-white rounded-lg border border-gray-200 p-4 hover:shadow-md transition-shadow group"
            >
              <div className="w-9 h-9 rounded-lg bg-rose-100 flex items-center justify-center text-base mb-2 group-hover:scale-110 transition-transform">
                {'\u{1F4D1}'}
              </div>
              <p className="font-medium text-gray-900 text-sm">Recipes</p>
              <p className="text-xs text-gray-500 mt-0.5">Migration recipes & roadmaps</p>
            </Link>
            <Link
              href="/tools"
              data-tour="tools"
              className="bg-white rounded-lg border border-gray-200 p-4 hover:shadow-md transition-shadow group"
            >
              <div className="w-9 h-9 rounded-lg bg-amber-100 flex items-center justify-center text-base mb-2 group-hover:scale-110 transition-transform">
                {'\u{1F527}'}
              </div>
              <p className="font-medium text-gray-900 text-sm">Tools</p>
              <p className="text-xs text-gray-500 mt-0.5">Custom agent tools</p>
            </Link>
          </div>
        </div>

        {/* Right: Repositories (2 cols) */}
        <div className="lg:col-span-2">
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden h-full flex flex-col">
            <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100 bg-gray-50/50">
              <h2 className="text-sm font-semibold text-gray-700">Repositories</h2>
              <Link href="/repos" className="text-[10px] text-indigo-600 hover:text-indigo-800 font-medium">
                Manage
              </Link>
            </div>
            {repoList.length === 0 ? (
              <div className="flex-1 flex flex-col items-center justify-center p-6 text-center">
                <div className="w-12 h-12 rounded-full bg-gray-100 flex items-center justify-center text-xl mb-3">
                  {'\u{1F4C2}'}
                </div>
                <p className="text-sm text-gray-500">No repos registered</p>
                <Link href="/repos" className="text-xs text-indigo-600 mt-1 hover:text-indigo-800">
                  + Add your first repo
                </Link>
              </div>
            ) : (
              <div className="flex-1 overflow-y-auto divide-y divide-gray-100">
                {repoList.map((repo) => (
                  <div key={repo.id} className="px-4 py-3 hover:bg-gray-50/50 transition-colors">
                    <div className="flex items-center gap-2.5">
                      <span className={`px-1.5 py-0.5 rounded text-[9px] font-medium flex-shrink-0 ${PLATFORM_STYLE[repo.platform] || PLATFORM_STYLE.local}`}>
                        {repo.platform}
                      </span>
                      <span className="text-sm font-medium text-gray-800 truncate">
                        {repo.nickname || repo.url || repo.local_path}
                      </span>
                    </div>
                    {repo.nickname && (repo.url || repo.local_path) && (
                      <p className="text-[10px] text-gray-400 mt-0.5 ml-[calc(1.5rem+14px)] truncate">
                        {repo.url || repo.local_path}
                      </p>
                    )}
                    <div className="flex gap-1.5 mt-2 ml-[calc(1.5rem+14px)]">
                      <Link
                        href="/testing/chat"
                        className="px-2 py-0.5 text-[10px] font-medium bg-indigo-50 text-indigo-700 rounded hover:bg-indigo-100 transition-colors"
                      >
                        Chat
                      </Link>
                      <Link
                        href="/testing/agents"
                        className="px-2 py-0.5 text-[10px] font-medium bg-gray-100 text-gray-600 rounded hover:bg-gray-200 transition-colors"
                      >
                        Runs
                      </Link>
                      <Link
                        href={`/repos/${repo.id}`}
                        className="px-2 py-0.5 text-[10px] font-medium bg-gray-100 text-gray-600 rounded hover:bg-gray-200 transition-colors"
                      >
                        Details
                      </Link>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

      </div>
    </div>
  );
}
