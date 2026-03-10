'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { migrations, type MigrationProject, type MigrationStats } from '@/lib/api';
import MigrationStatusBadge from '@/components/migration/MigrationStatusBadge';

export default function MigrationDashboard() {
  const [projects, setProjects] = useState<MigrationProject[]>([]);
  const [stats, setStats] = useState<MigrationStats | null>(null);
  const [loading, setLoading] = useState(true);

  const loadData = async () => {
    try {
      const [projRes, statsRes] = await Promise.all([
        migrations.listProjects(),
        migrations.stats(),
      ]);
      setProjects(projRes.projects);
      setStats(statsRes);
    } catch (err) {
      console.error('Failed to load migration data:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 5000);
    return () => clearInterval(interval);
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="w-6 h-6 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Migration</h1>
          <p className="text-sm text-gray-500">Migrate repositories to golden template patterns</p>
        </div>
        <Link
          href="/migration/new"
          className="px-4 py-2 bg-indigo-600 text-white text-sm rounded-md hover:bg-indigo-700"
        >
          New Migration
        </Link>
      </div>

      {/* Stats bar */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3 mb-6">
          <div className="bg-white border border-gray-200 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-gray-900">{stats.total_projects}</div>
            <div className="text-xs text-gray-500">Projects</div>
          </div>
          <div className="bg-white border border-gray-200 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-green-600">{stats.analyzed_projects}</div>
            <div className="text-xs text-gray-500">Analyzed</div>
          </div>
          <div className="bg-white border border-gray-200 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-blue-600">{stats.total_runs}</div>
            <div className="text-xs text-gray-500">Runs</div>
          </div>
          <div className="bg-white border border-gray-200 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-green-600">{stats.completed_runs}</div>
            <div className="text-xs text-gray-500">Completed</div>
          </div>
          <div className="bg-white border border-gray-200 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-blue-600">{stats.running_runs}</div>
            <div className="text-xs text-gray-500">Running</div>
          </div>
          <div className="bg-white border border-gray-200 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-red-600">{stats.failed_runs}</div>
            <div className="text-xs text-gray-500">Failed</div>
          </div>
        </div>
      )}

      {/* Project cards */}
      {projects.length === 0 ? (
        <div className="text-center py-16 bg-white border border-gray-200 rounded-lg">
          <div className="text-4xl mb-3">&#x1F4E6;</div>
          <h2 className="text-lg font-semibold text-gray-900 mb-1">No migration projects yet</h2>
          <p className="text-sm text-gray-500 mb-4">
            Create your first migration to compare a source repo against a golden reference template.
          </p>
          <Link
            href="/migration/new"
            className="px-4 py-2 bg-indigo-600 text-white text-sm rounded-md hover:bg-indigo-700"
          >
            New Migration
          </Link>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {projects.map(project => (
            <Link
              key={project.id}
              href={`/migration/${project.id}`}
              className="bg-white border border-gray-200 rounded-lg p-4 hover:border-gray-300 hover:shadow-sm transition-all"
            >
              <div className="flex items-start justify-between gap-2 mb-2">
                <h3 className="text-sm font-semibold text-gray-900 truncate">{project.name}</h3>
                <MigrationStatusBadge status={project.status} />
              </div>

              <div className="space-y-1 text-xs text-gray-500">
                {project.source_repo_url && (
                  <div className="truncate">
                    <span className="text-gray-400">Source:</span> {project.source_repo_url}
                  </div>
                )}
                {project.source_local_path && !project.source_repo_url && (
                  <div className="truncate">
                    <span className="text-gray-400">Source:</span> {project.source_local_path}
                  </div>
                )}
                {project.reference_repo_url && (
                  <div className="truncate">
                    <span className="text-gray-400">Ref:</span> {project.reference_repo_url}
                  </div>
                )}
              </div>

              {/* Gap summary */}
              {project.gap_analysis?.summary && (
                <div className="mt-3 flex items-center gap-2">
                  <span className="text-xs text-gray-500">
                    {project.gap_analysis.summary.total_gaps || 0} gaps
                  </span>
                  <span className="text-xs text-gray-400">
                    in {project.gap_analysis.summary.categories_affected || 0} categories
                  </span>
                </div>
              )}

              <div className="mt-3 text-[10px] text-gray-400">
                Created {new Date(project.created_at).toLocaleDateString()}
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
