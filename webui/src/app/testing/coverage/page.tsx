'use client';

import { Suspense, useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { testing, repos, type TestProject, type CoverageReport, type StrategyBreakdown, type TestRunSummary } from '@/lib/api';
import StrategyCard from '@/components/testing/StrategyCard';
import StrategySummaryBar from '@/components/testing/StrategySummaryBar';
import MissingStrategiesBanner from '@/components/testing/MissingStrategiesBanner';

export default function CoveragePageWrapper() {
  return (
    <Suspense fallback={<div className="flex items-center justify-center min-h-[60vh]"><div className="w-6 h-6 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin" /></div>}>
      <CoveragePage />
    </Suspense>
  );
}

function CoveragePage() {
  const searchParams = useSearchParams();
  const projectFilter = searchParams.get('project') || '';

  const [projects, setProjects] = useState<TestProject[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState(projectFilter);
  const [reports, setReports] = useState<CoverageReport[]>([]);
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [runningTests, setRunningTests] = useState(false);

  // Branch selector state
  const [branch, setBranch] = useState('main');
  const [branchList, setBranchList] = useState<string[]>([]);
  const [loadingBranches, setLoadingBranches] = useState(false);

  // SonarQube project key
  const [sonarProjectKey, setSonarProjectKey] = useState('');

  useEffect(() => {
    async function load() {
      try {
        const p = await testing.listProjects({ limit: 100 });
        setProjects(p.projects);
        if (!selectedProjectId && p.projects.length > 0) {
          setSelectedProjectId(p.projects[0].id);
        }
      } catch (err) {
        console.error('Failed to load projects:', err);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  // Load branches when project selection changes
  useEffect(() => {
    if (!selectedProjectId) {
      setBranchList([]);
      setBranch('main');
      return;
    }
    const proj = projects.find((p) => p.id === selectedProjectId);
    const repoId = proj?.repo_id || selectedProjectId;
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
  }, [selectedProjectId, projects]);

  useEffect(() => {
    if (selectedProjectId) {
      loadReports();
    }
  }, [selectedProjectId]);

  async function loadReports() {
    try {
      const r = await testing.listCoverage(selectedProjectId);
      setReports(r);
    } catch {
      setReports([]);
    }
  }

  async function handleRunExistingTests() {
    if (!selectedProjectId) return;
    setRunningTests(true);
    try {
      await testing.createRun({
        project_id: selectedProjectId,
        run_type: 'functional',
        strategy: 'existing',
        branch: branch,
      });
      alert('Test run started! Check the Agent Monitor page for progress. Re-analyze coverage after completion.');
    } catch (err) {
      console.error('Failed to start test run:', err);
    } finally {
      setRunningTests(false);
    }
  }

  async function handleAnalyze() {
    setAnalyzing(true);
    try {
      await testing.analyzeCoverage(selectedProjectId, branch || undefined, sonarProjectKey || undefined);
      await loadReports();
    } catch (err) {
      console.error('Coverage analysis failed:', err);
    } finally {
      setAnalyzing(false);
    }
  }

  if (loading) {
    return <p className="text-gray-500">Loading coverage data...</p>;
  }

  const latestReport = reports[0] || null;
  const strategyBreakdown: Record<string, StrategyBreakdown> | undefined =
    latestReport?.details?.strategy_breakdown;
  const testRunSummary: TestRunSummary | undefined =
    latestReport?.details?.test_run_summary;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Coverage Analysis</h1>
        <div className="flex items-center gap-3">
          <select
            value={selectedProjectId}
            onChange={(e) => setSelectedProjectId(e.target.value)}
            className="px-3 py-2 border border-gray-300 rounded-md text-sm"
          >
            <option value="">Select project...</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
          <select
            value={branch}
            onChange={(e) => setBranch(e.target.value)}
            className="px-3 py-2 border border-gray-300 rounded-md text-sm"
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
          <input
            type="text"
            placeholder="SonarQube project key (optional)"
            value={sonarProjectKey}
            onChange={(e) => setSonarProjectKey(e.target.value)}
            className="px-3 py-2 border border-gray-300 rounded-md text-sm w-56"
          />
          <button
            onClick={handleRunExistingTests}
            disabled={!selectedProjectId || runningTests}
            className="px-4 py-2 bg-emerald-600 text-white rounded-md text-sm font-medium hover:bg-emerald-700 disabled:opacity-50"
          >
            {runningTests ? 'Starting...' : 'Run Existing Tests'}
          </button>
          <button
            onClick={handleAnalyze}
            disabled={!selectedProjectId || analyzing}
            className="px-4 py-2 bg-indigo-600 text-white rounded-md text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
          >
            {analyzing ? 'Analyzing...' : 'Analyze Coverage'}
          </button>
        </div>
      </div>

      {!selectedProjectId ? (
        <div className="bg-white rounded-lg border border-gray-200 p-8 text-center text-gray-500">
          Select a project to view coverage analysis
        </div>
      ) : latestReport ? (
        <>
          {/* Overall metrics row — 4 existing + pass rate from test run summary */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
            {[
              { label: 'Overall Coverage', value: latestReport.overall_pct, color: getCoverageColor(latestReport.overall_pct) },
              { label: 'Function Coverage', value: latestReport.function_coverage, color: getCoverageColor(latestReport.function_coverage) },
              { label: 'Line Coverage', value: latestReport.line_coverage, color: getCoverageColor(latestReport.line_coverage) },
              { label: 'Branch Coverage', value: latestReport.branch_coverage, color: getCoverageColor(latestReport.branch_coverage) },
              ...(testRunSummary ? [{
                label: 'Pass Rate',
                value: testRunSummary.overall_pass_rate,
                color: getCoverageColor(testRunSummary.overall_pass_rate),
              }] : []),
            ].map((item) => (
              <div key={item.label} className="bg-white rounded-lg border border-gray-200 p-5">
                <p className="text-sm text-gray-500">{item.label}</p>
                <div className="mt-2 flex items-end gap-2">
                  <span className={`text-3xl font-bold ${item.color}`}>{item.value}%</span>
                </div>
                <div className="mt-2 w-full bg-gray-200 rounded-full h-2">
                  <div
                    className={`h-2 rounded-full ${item.color === 'text-green-600' ? 'bg-green-500' : item.color === 'text-yellow-600' ? 'bg-yellow-500' : 'bg-red-500'}`}
                    style={{ width: `${Math.min(item.value, 100)}%` }}
                  />
                </div>
              </div>
            ))}
          </div>

          {/* Strategy Summary Bar */}
          {strategyBreakdown && Object.keys(strategyBreakdown).length > 0 && (
            <StrategySummaryBar breakdown={strategyBreakdown} />
          )}

          {/* Missing Strategies Banner */}
          {testRunSummary && testRunSummary.strategies_missing.length > 0 && (
            <MissingStrategiesBanner missing={testRunSummary.strategies_missing} />
          )}

          {/* Per-Strategy Grid */}
          {strategyBreakdown && Object.keys(strategyBreakdown).length > 0 && (
            <div>
              <h3 className="font-medium text-gray-900 mb-3">Per-Strategy Breakdown</h3>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {Object.values(strategyBreakdown).map((sb) => (
                  <StrategyCard key={sb.strategy} data={sb} />
                ))}
              </div>
            </div>
          )}

          {/* Uncovered areas + Gap suggestions */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Uncovered areas */}
            <div className="bg-white rounded-lg border border-gray-200 p-5">
              <h3 className="font-medium text-gray-900 mb-3">
                Uncovered Areas ({latestReport.uncovered_areas.length})
              </h3>
              {latestReport.uncovered_areas.length === 0 ? (
                <p className="text-sm text-green-600">All areas are covered!</p>
              ) : (
                <div className="space-y-2 max-h-80 overflow-y-auto">
                  {latestReport.uncovered_areas.map((area, idx) => (
                    <div key={idx} className="flex items-center justify-between border border-gray-100 rounded p-3">
                      <div>
                        <p className="text-sm font-medium text-gray-700">{area.file}</p>
                        <p className="text-xs text-gray-400">{area.type} - {area.endpoint_type || area.type}</p>
                      </div>
                      <div className="flex items-center gap-2">
                        {area.suggested_strategy && (
                          <span className="text-xs px-2 py-0.5 rounded bg-indigo-100 text-indigo-700">
                            {area.suggested_strategy}
                          </span>
                        )}
                        <span className={`text-xs px-2 py-0.5 rounded ${
                          area.priority === 'high' ? 'bg-red-100 text-red-700' : 'bg-yellow-100 text-yellow-700'
                        }`}>
                          {area.priority}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Gap suggestions */}
            <div className="bg-white rounded-lg border border-gray-200 p-5">
              <h3 className="font-medium text-gray-900 mb-3">
                Improvement Suggestions ({latestReport.gaps.length})
              </h3>
              {latestReport.gaps.length === 0 ? (
                <p className="text-sm text-green-600">No gaps identified.</p>
              ) : (
                <div className="space-y-2 max-h-80 overflow-y-auto">
                  {latestReport.gaps.map((gap, idx) => (
                    <div key={idx} className="border border-gray-100 rounded p-3">
                      <div className="flex items-center gap-2 mb-1">
                        <span className={`text-xs px-2 py-0.5 rounded ${
                          gap.priority === 'high' ? 'bg-red-100 text-red-700' : 'bg-yellow-100 text-yellow-700'
                        }`}>
                          {gap.priority}
                        </span>
                        <span className="text-xs text-gray-500">{gap.gap_type}</span>
                        {gap.suggested_strategy && (
                          <span className="text-xs px-2 py-0.5 rounded bg-indigo-100 text-indigo-700">
                            {gap.suggested_strategy}
                          </span>
                        )}
                      </div>
                      <p className="text-sm text-gray-700">{gap.suggestion}</p>
                      <p className="text-xs text-gray-400 mt-1">{gap.area}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Report details / Summary */}
          {latestReport.details && Object.keys(latestReport.details).length > 0 && (
            <div className="bg-white rounded-lg border border-gray-200 p-5">
              <h3 className="font-medium text-gray-900 mb-3">Summary</h3>
              <dl className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
                {Object.entries(latestReport.details)
                  .filter(([key]) => !['sonarqube', 'strategy_breakdown', 'test_run_summary'].includes(key))
                  .map(([key, val]) => (
                  <div key={key}>
                    <dt className="text-gray-500">{key.replace(/_/g, ' ')}</dt>
                    <dd className="font-medium text-gray-900">
                      {Array.isArray(val) ? val.join(', ') : String(val)}
                    </dd>
                  </div>
                ))}
              </dl>
            </div>
          )}

          {/* SonarQube section */}
          {latestReport.details?.sonarqube && (
            <div className="bg-white rounded-lg border border-gray-200 p-5">
              <div className="flex items-center justify-between mb-3">
                <h3 className="font-medium text-gray-900">SonarQube</h3>
                <span className="text-xs text-gray-400">
                  {latestReport.details.sonarqube.project_key}
                </span>
              </div>

              {/* Quality gate badge */}
              {latestReport.details.sonarqube.quality_gate?.status && (
                <div className="mb-4">
                  <span className={`inline-flex items-center px-3 py-1 rounded-full text-sm font-medium ${
                    latestReport.details.sonarqube.quality_gate.status === 'OK'
                      ? 'bg-green-100 text-green-800'
                      : latestReport.details.sonarqube.quality_gate.status === 'WARN'
                        ? 'bg-yellow-100 text-yellow-800'
                        : 'bg-red-100 text-red-800'
                  }`}>
                    Quality Gate: {latestReport.details.sonarqube.quality_gate.status}
                  </span>
                </div>
              )}

              {/* Metrics grid */}
              {latestReport.details.sonarqube.measures && (
                <dl className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-4 text-sm">
                  {[
                    { key: 'bugs', label: 'Bugs' },
                    { key: 'vulnerabilities', label: 'Vulnerabilities' },
                    { key: 'code_smells', label: 'Code Smells' },
                    { key: 'duplicated_lines_density', label: 'Duplication %' },
                    { key: 'ncloc', label: 'Lines of Code' },
                    { key: 'coverage', label: 'Coverage' },
                  ]
                    .filter(({ key }) => latestReport.details.sonarqube.measures[key] !== undefined)
                    .map(({ key, label }) => (
                      <div key={key}>
                        <dt className="text-gray-500">{label}</dt>
                        <dd className="font-medium text-gray-900">
                          {latestReport.details.sonarqube.measures[key]}
                          {key.includes('density') || key === 'coverage' ? '%' : ''}
                        </dd>
                      </div>
                    ))}
                </dl>
              )}
            </div>
          )}

          {/* Historical reports */}
          {reports.length > 1 && (
            <div className="bg-white rounded-lg border border-gray-200 p-5">
              <h3 className="font-medium text-gray-900 mb-3">Report History</h3>
              <div className="space-y-2">
                {reports.map((r, idx) => (
                  <div key={r.id} className={`flex items-center justify-between p-3 rounded ${idx === 0 ? 'bg-indigo-50' : 'bg-gray-50'}`}>
                    <div className="flex items-center gap-3">
                      <span className="text-sm text-gray-600">{r.report_type}</span>
                      <span className="text-xs text-gray-400">
                        {r.created_at ? new Date(r.created_at).toLocaleString() : ''}
                      </span>
                    </div>
                    <span className={`font-medium ${getCoverageColor(r.overall_pct)}`}>
                      {r.overall_pct}%
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      ) : (
        <div className="bg-white rounded-lg border border-gray-200 p-8 text-center">
          <p className="text-gray-500 mb-4">No coverage reports yet for this project.</p>
          <button
            onClick={handleAnalyze}
            disabled={analyzing}
            className="px-4 py-2 bg-indigo-600 text-white rounded-md text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
          >
            {analyzing ? 'Analyzing...' : 'Run First Analysis'}
          </button>
        </div>
      )}
    </div>
  );
}

function getCoverageColor(pct: number): string {
  if (pct >= 80) return 'text-green-600';
  if (pct >= 50) return 'text-yellow-600';
  return 'text-red-600';
}
