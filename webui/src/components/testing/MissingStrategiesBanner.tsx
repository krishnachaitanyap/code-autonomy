'use client';

const STRATEGY_LABELS: Record<string, string> = {
  unit: 'Unit Tests',
  integration: 'Integration Tests',
  bdd: 'BDD / Cucumber',
  contract: 'Contract Tests',
  e2e: 'End-to-End Tests',
  soap: 'SOAP Tests',
  jisi_bdd: 'JISI BDD',
  security_bdd: 'Security BDD',
};

export default function MissingStrategiesBanner({
  missing,
}: {
  missing: string[];
}) {
  if (missing.length === 0) return null;

  return (
    <div className="rounded-lg border border-amber-300 bg-amber-50 px-5 py-4">
      <div className="flex items-start gap-3">
        <svg className="w-5 h-5 text-amber-500 mt-0.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        <div>
          <p className="text-sm font-medium text-amber-800">Missing Test Strategies</p>
          <p className="text-sm text-amber-700 mt-1">
            No test runs found for:{' '}
            {missing.map((s, i) => (
              <span key={s}>
                {i > 0 && ', '}
                <span className="font-medium">{STRATEGY_LABELS[s] || s}</span>
              </span>
            ))}
            . Consider adding these to improve coverage confidence.
          </p>
        </div>
      </div>
    </div>
  );
}
