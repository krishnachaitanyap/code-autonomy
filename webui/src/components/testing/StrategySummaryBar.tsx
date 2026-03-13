'use client';

import type { StrategyBreakdown } from '@/lib/api';

const STRATEGY_BAR_COLORS: Record<string, string> = {
  unit: 'bg-blue-500',
  integration: 'bg-purple-500',
  bdd: 'bg-green-500',
  contract: 'bg-orange-500',
  e2e: 'bg-cyan-500',
  soap: 'bg-amber-500',
  jisi_bdd: 'bg-teal-500',
  security_bdd: 'bg-red-500',
  messaging: 'bg-indigo-500',
  unknown: 'bg-gray-400',
};

const STRATEGY_DOT_COLORS: Record<string, string> = {
  unit: 'bg-blue-500',
  integration: 'bg-purple-500',
  bdd: 'bg-green-500',
  contract: 'bg-orange-500',
  e2e: 'bg-cyan-500',
  soap: 'bg-amber-500',
  jisi_bdd: 'bg-teal-500',
  security_bdd: 'bg-red-500',
  messaging: 'bg-indigo-500',
  unknown: 'bg-gray-400',
};

export default function StrategySummaryBar({
  breakdown,
}: {
  breakdown: Record<string, StrategyBreakdown>;
}) {
  const entries = Object.values(breakdown).filter((b) => b.coverage_pct > 0);
  const totalCoverage = entries.reduce((sum, b) => sum + b.coverage_pct, 0);
  const uncoveredPct = Math.max(0, 100 - totalCoverage);

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-5">
      <h3 className="font-medium text-gray-900 mb-3">Strategy Coverage Breakdown</h3>

      {/* Stacked bar */}
      <div className="w-full bg-gray-200 rounded-full h-4 flex overflow-hidden">
        {entries.map((b) => (
          <div
            key={b.strategy}
            className={`h-4 ${STRATEGY_BAR_COLORS[b.strategy] || 'bg-gray-400'}`}
            style={{ width: `${Math.max(b.coverage_pct, 0.5)}%` }}
            title={`${b.display_name}: ${b.coverage_pct}%`}
          />
        ))}
        {uncoveredPct > 0 && (
          <div
            className="h-4 bg-gray-200"
            style={{ width: `${uncoveredPct}%` }}
            title={`Uncovered: ${uncoveredPct.toFixed(1)}%`}
          />
        )}
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-4 mt-3">
        {entries.map((b) => (
          <div key={b.strategy} className="flex items-center gap-1.5 text-xs text-gray-600">
            <span className={`w-2.5 h-2.5 rounded-full ${STRATEGY_DOT_COLORS[b.strategy] || 'bg-gray-400'}`} />
            {b.display_name} ({b.coverage_pct}%)
          </div>
        ))}
        {uncoveredPct > 0 && (
          <div className="flex items-center gap-1.5 text-xs text-gray-400">
            <span className="w-2.5 h-2.5 rounded-full bg-gray-200 border border-gray-300" />
            Uncovered ({uncoveredPct.toFixed(1)}%)
          </div>
        )}
      </div>
    </div>
  );
}
