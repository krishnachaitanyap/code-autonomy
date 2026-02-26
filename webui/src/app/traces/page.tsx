'use client';

import { useEffect, useState } from 'react';
import { traces, repos, type Trace, type Repo, type UsageStats } from '@/lib/api';
import TraceTimeline from '@/components/TraceTimeline';

export default function TracesPage() {
  const [traceList, setTraceList] = useState<Trace[]>([]);
  const [repoList, setRepoList] = useState<Repo[]>([]);
  const [stats, setStats] = useState<UsageStats | null>(null);
  const [filterRepo, setFilterRepo] = useState('');
  const [loading, setLoading] = useState(true);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const [t, r, s] = await Promise.all([
          traces.list({ repo_id: filterRepo || undefined, limit: 50 }),
          repos.list(),
          traces.stats(filterRepo || undefined),
        ]);
        setTraceList(t.traces);
        setRepoList(r);
        setStats(s);
      } catch (err) {
        console.error('Failed to load traces:', err);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [filterRepo]);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">Traces</h1>

      {/* Usage stats */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { label: 'Sessions', value: stats.total_sessions },
            { label: 'Success Rate', value: `${(stats.success_rate * 100).toFixed(1)}%` },
            { label: 'Total Tokens', value: stats.total_tokens.toLocaleString() },
            { label: 'Avg Duration', value: `${(stats.total_duration_s / Math.max(stats.total_sessions, 1)).toFixed(1)}s` },
          ].map((card) => (
            <div
              key={card.label}
              className="bg-white rounded-lg border border-gray-200 p-4"
            >
              <p className="text-xs text-gray-500">{card.label}</p>
              <p className="text-xl font-semibold text-gray-900">{card.value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Filter */}
      <select
        value={filterRepo}
        onChange={(e) => setFilterRepo(e.target.value)}
        className="border border-gray-300 rounded-md px-3 py-2 text-sm"
      >
        <option value="">All Repos</option>
        {repoList.map((r) => (
          <option key={r.id} value={r.id}>
            {r.url || r.local_path}
          </option>
        ))}
      </select>

      {/* Trace list */}
      {loading ? (
        <p className="text-gray-500">Loading traces...</p>
      ) : traceList.length === 0 ? (
        <p className="text-gray-500">No traces found.</p>
      ) : (
        <div className="space-y-3">
          {traceList.map((trace) => (
            <div
              key={trace.id}
              className="bg-white rounded-lg border border-gray-200 overflow-hidden"
            >
              <button
                onClick={() =>
                  setExpandedId(expandedId === trace.id ? null : trace.id)
                }
                className="w-full px-5 py-4 flex items-center justify-between text-left hover:bg-gray-50"
              >
                <div className="flex items-center gap-4">
                  <span
                    className={`w-2 h-2 rounded-full ${
                      trace.success ? 'bg-green-500' : 'bg-red-500'
                    }`}
                  />
                  <div>
                    <p className="text-sm font-medium text-gray-900">
                      {trace.summary || trace.id.slice(0, 12)}
                    </p>
                    <p className="text-xs text-gray-500">
                      {trace.model} &middot; {trace.turns_used} turns &middot;{' '}
                      {trace.duration_s.toFixed(1)}s
                    </p>
                  </div>
                </div>
                <div className="text-right text-xs text-gray-400">
                  <p>{trace.total_tokens.toLocaleString()} tokens</p>
                  <p>{new Date(trace.created_at).toLocaleDateString()}</p>
                </div>
              </button>
              {expandedId === trace.id && trace.spans && (
                <div className="border-t border-gray-200 px-5 py-4">
                  <TraceTimeline
                    spans={trace.spans}
                    totalDuration={trace.duration_s}
                  />
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
