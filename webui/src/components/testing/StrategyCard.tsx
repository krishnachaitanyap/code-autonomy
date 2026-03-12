'use client';

import { useState } from 'react';
import type { StrategyBreakdown } from '@/lib/api';

const STRATEGY_COLORS: Record<string, { bg: string; text: string; bar: string }> = {
  unit: { bg: 'bg-blue-100', text: 'text-blue-700', bar: 'bg-blue-500' },
  integration: { bg: 'bg-purple-100', text: 'text-purple-700', bar: 'bg-purple-500' },
  bdd: { bg: 'bg-green-100', text: 'text-green-700', bar: 'bg-green-500' },
  contract: { bg: 'bg-orange-100', text: 'text-orange-700', bar: 'bg-orange-500' },
  e2e: { bg: 'bg-cyan-100', text: 'text-cyan-700', bar: 'bg-cyan-500' },
  soap: { bg: 'bg-amber-100', text: 'text-amber-700', bar: 'bg-amber-500' },
  jisi_bdd: { bg: 'bg-teal-100', text: 'text-teal-700', bar: 'bg-teal-500' },
  security_bdd: { bg: 'bg-red-100', text: 'text-red-700', bar: 'bg-red-500' },
  unknown: { bg: 'bg-gray-100', text: 'text-gray-700', bar: 'bg-gray-400' },
};

function getStatusPill(status: string | null) {
  if (!status) return null;
  const cls = status === 'passed'
    ? 'bg-green-100 text-green-700'
    : 'bg-red-100 text-red-700';
  return <span className={`text-xs px-2 py-0.5 rounded-full ${cls}`}>{status}</span>;
}

export default function StrategyCard({ data }: { data: StrategyBreakdown }) {
  const [expanded, setExpanded] = useState(false);
  const colors = STRATEGY_COLORS[data.strategy] || STRATEGY_COLORS.unknown;

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-5">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className={`text-xs font-medium px-2 py-0.5 rounded ${colors.bg} ${colors.text}`}>
            {data.display_name}
          </span>
          {getStatusPill(data.latest_run_status)}
        </div>
        <span className="text-sm text-gray-400">
          {data.run_count} run{data.run_count !== 1 ? 's' : ''}
        </span>
      </div>

      <div className="grid grid-cols-3 gap-3 text-center mb-3">
        <div>
          <p className="text-xs text-gray-500">Pass Rate</p>
          <p className="text-lg font-bold text-gray-900">{data.pass_rate}%</p>
        </div>
        <div>
          <p className="text-xs text-gray-500">Test Files</p>
          <p className="text-lg font-bold text-gray-900">{data.test_file_count}</p>
        </div>
        <div>
          <p className="text-xs text-gray-500">Tests Run</p>
          <p className="text-lg font-bold text-gray-900">{data.total_tests}</p>
        </div>
      </div>

      {/* Mini coverage bar */}
      <div className="mb-2">
        <div className="flex items-center justify-between text-xs text-gray-500 mb-1">
          <span>Coverage</span>
          <span>{data.coverage_pct}%</span>
        </div>
        <div className="w-full bg-gray-200 rounded-full h-2">
          <div
            className={`h-2 rounded-full ${colors.bar}`}
            style={{ width: `${Math.min(data.coverage_pct, 100)}%` }}
          />
        </div>
      </div>

      {/* Pass / Fail / Skip row */}
      <div className="flex items-center gap-3 text-xs text-gray-500 mb-2">
        <span className="text-green-600">{data.passed} passed</span>
        <span className="text-red-600">{data.failed} failed</span>
        <span>{data.skipped} skipped</span>
      </div>

      {data.latest_run_at && (
        <p className="text-xs text-gray-400 mb-2">
          Last run: {new Date(data.latest_run_at).toLocaleString()}
        </p>
      )}

      {/* Collapsible file list */}
      {data.test_files.length > 0 && (
        <div>
          <button
            onClick={() => setExpanded(!expanded)}
            className="text-xs text-indigo-600 hover:text-indigo-800"
          >
            {expanded ? 'Hide' : 'Show'} {data.test_files.length} file{data.test_files.length !== 1 ? 's' : ''}
          </button>
          {expanded && (
            <ul className="mt-2 space-y-1 max-h-40 overflow-y-auto">
              {data.test_files.map((f) => (
                <li key={f} className="text-xs text-gray-600 truncate">{f}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
