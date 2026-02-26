'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { repos, sessions, traces, type Repo, type Session, type UsageStats } from '@/lib/api';

export default function Dashboard() {
  const [repoList, setRepoList] = useState<Repo[]>([]);
  const [recentSessions, setRecentSessions] = useState<Session[]>([]);
  const [stats, setStats] = useState<UsageStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const [r, s, st] = await Promise.all([
          repos.list(),
          sessions.list({ limit: 5 }),
          traces.stats(),
        ]);
        setRepoList(r);
        setRecentSessions(s.sessions);
        setStats(st);
      } catch (err) {
        console.error('Failed to load dashboard data:', err);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  if (loading) {
    return <p className="text-gray-500">Loading dashboard...</p>;
  }

  const statCards = stats
    ? [
        { label: 'Total Sessions', value: stats.total_sessions },
        { label: 'Success Rate', value: `${(stats.success_rate * 100).toFixed(1)}%` },
        { label: 'Total Tokens', value: stats.total_tokens.toLocaleString() },
        { label: 'Total Cost', value: `$${stats.total_cost.toFixed(2)}` },
      ]
    : [];

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>

      {/* Stats grid */}
      {statCards.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {statCards.map((card) => (
            <div
              key={card.label}
              className="bg-white rounded-lg border border-gray-200 p-5"
            >
              <p className="text-sm text-gray-500">{card.label}</p>
              <p className="mt-1 text-2xl font-semibold text-gray-900">
                {card.value}
              </p>
            </div>
          ))}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* Repos summary */}
        <div>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold text-gray-900">
              Repos ({repoList.length})
            </h2>
            <Link
              href="/repos"
              className="text-sm text-indigo-600 hover:text-indigo-800"
            >
              View all
            </Link>
          </div>
          <div className="space-y-2">
            {repoList.slice(0, 5).map((repo) => (
              <div
                key={repo.id}
                className="bg-white rounded border border-gray-200 px-4 py-3 flex items-center justify-between"
              >
                <span className="text-sm font-medium text-gray-700 truncate">
                  {repo.url || repo.local_path}
                </span>
                <span className="text-xs text-gray-400">{repo.platform}</span>
              </div>
            ))}
            {repoList.length === 0 && (
              <p className="text-sm text-gray-500">
                No repos registered.{' '}
                <Link href="/repos" className="text-indigo-600">
                  Add one
                </Link>
              </p>
            )}
          </div>
        </div>

        {/* Recent sessions */}
        <div>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold text-gray-900">
              Recent Sessions
            </h2>
            <Link
              href="/sessions"
              className="text-sm text-indigo-600 hover:text-indigo-800"
            >
              View all
            </Link>
          </div>
          <div className="space-y-2">
            {recentSessions.map((session) => {
              const statusColor: Record<string, string> = {
                completed: 'bg-green-100 text-green-700',
                running: 'bg-blue-100 text-blue-700',
                failed: 'bg-red-100 text-red-700',
                paused: 'bg-yellow-100 text-yellow-700',
              };
              return (
                <Link
                  key={session.id}
                  href={`/sessions/${session.id}`}
                  className="block bg-white rounded border border-gray-200 px-4 py-3 hover:shadow-sm transition-shadow"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium text-gray-700">
                      {session.mode}
                    </span>
                    <span
                      className={`px-2 py-0.5 rounded text-xs font-medium ${
                        statusColor[session.status] || 'bg-gray-100 text-gray-600'
                      }`}
                    >
                      {session.status}
                    </span>
                  </div>
                  <p className="text-xs text-gray-500 mt-1 truncate">
                    {session.requirements}
                  </p>
                </Link>
              );
            })}
            {recentSessions.length === 0 && (
              <p className="text-sm text-gray-500">No sessions yet.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
