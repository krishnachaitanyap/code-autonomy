'use client';

import { useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { testing, type TestProject, type CoverageReport } from '@/lib/api';

export default function CoveragePage() {
  const searchParams = useSearchParams();
  const projectFilter = searchParams.get('project') || '';

  const [projects, setProjects] = useState<TestProject[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState(projectFilter);
  const [reports, setReports] = useState<CoverageReport[]>([]);
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);

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

  async function handleAnalyze() {
    setAnalyzing(true);
    try {
      await testing.analyzeCoverage(selectedProjectId);
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
          {/* Coverage overview */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {[
              { label: 'Overall Coverage', value: latestReport.overall_pct, color: getCoverageColor(latestReport.overall_pct) },
              { label: 'Function Coverage', value: latestReport.function_coverage, color: getCoverageColor(latestReport.function_coverage) },
              { label: 'Line Coverage', value: latestReport.line_coverage, color: getCoverageColor(latestReport.line_coverage) },
              { label: 'Branch Coverage', value: latestReport.branch_coverage, color: getCoverageColor(latestReport.branch_coverage) },
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

          {/* Coverage details */}
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
                      <span className={`text-xs px-2 py-0.5 rounded ${
                        area.priority === 'high' ? 'bg-red-100 text-red-700' : 'bg-yellow-100 text-yellow-700'
                      }`}>
                        {area.priority}
                      </span>
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
                      </div>
                      <p className="text-sm text-gray-700">{gap.suggestion}</p>
                      <p className="text-xs text-gray-400 mt-1">{gap.area}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Report details */}
          {latestReport.details && Object.keys(latestReport.details).length > 0 && (
            <div className="bg-white rounded-lg border border-gray-200 p-5">
              <h3 className="font-medium text-gray-900 mb-3">Summary</h3>
              <dl className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
                {Object.entries(latestReport.details).map(([key, val]) => (
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
