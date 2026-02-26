'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { testing, type TestProject, type TestingStats } from '@/lib/api';
import { useTour, type TourStep } from '@/components/TourProvider';

const TOUR_STEPS: TourStep[] = [
  {
    target: '[data-tour="welcome"]',
    title: 'Welcome to Code Autonomy',
    content:
      'This is your enterprise testing platform. Let us walk you through the key features and how to get started.',
    placement: 'bottom',
  },
  {
    target: '[data-tour="onboard"]',
    title: 'Onboard Repository',
    content:
      'Start here \u2014 add your repository by URL or local path. The system auto-detects language, framework, and existing test setup.',
    placement: 'bottom',
  },
  {
    target: '[data-tour="agents"]',
    title: 'Agent Monitor',
    content:
      'View running test agents, their progress, results, and collected evidence. Start new functional, security, or regression test runs.',
    placement: 'bottom',
  },
  {
    target: '[data-tour="coverage"]',
    title: 'Coverage Analysis',
    content:
      'Analyze test coverage, identify uncovered endpoints and services, and get actionable suggestions to improve your test coverage.',
    placement: 'bottom',
  },
  {
    target: '[data-tour="chat"]',
    title: 'Chat Assistant',
    content:
      'Ask questions in natural language \u2014 "What endpoints are untested?", "Run security scan", "Generate test data for Users".',
    placement: 'bottom',
  },
  {
    target: '[data-tour="stats"]',
    title: 'Dashboard Stats',
    content:
      'Track key metrics at a glance: total projects, test runs, pass/fail rates, and average coverage across all projects.',
    placement: 'bottom',
  },
  {
    target: '[data-tour="projects"]',
    title: 'Your Projects',
    content:
      'All onboarded projects appear here with quick links to coverage analysis, test runs, and the chat assistant for each project.',
    placement: 'top',
  },
  {
    target: '[data-tour="help"]',
    title: 'Need Help?',
    content:
      'Click this button anytime to replay this tour. You can also use the Chat page to ask any testing question in natural language.',
    placement: 'bottom',
  },
];

export default function TestingDashboard() {
  const [projects, setProjects] = useState<TestProject[]>([]);
  const [stats, setStats] = useState<TestingStats | null>(null);
  const [loading, setLoading] = useState(true);
  const { startTour, hasSeenTour } = useTour();

  useEffect(() => {
    async function load() {
      try {
        const [p, s] = await Promise.all([
          testing.listProjects({ limit: 10 }),
          testing.stats(),
        ]);
        setProjects(p.projects);
        setStats(s);
      } catch (err) {
        console.error('Failed to load testing dashboard:', err);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  // Auto-start tour on first visit
  useEffect(() => {
    if (!loading && !hasSeenTour) {
      // Small delay to let the page render
      const timer = setTimeout(() => startTour(TOUR_STEPS), 500);
      return () => clearTimeout(timer);
    }
  }, [loading, hasSeenTour, startTour]);

  if (loading) {
    return <p className="text-gray-500">Loading testing dashboard...</p>;
  }

  const statCards = stats
    ? [
        { label: 'Projects', value: stats.total_projects, color: 'text-indigo-600' },
        { label: 'Total Runs', value: stats.total_runs, color: 'text-blue-600' },
        { label: 'Passed', value: stats.passed_runs, color: 'text-green-600' },
        { label: 'Failed', value: stats.failed_runs, color: 'text-red-600' },
        { label: 'Running', value: stats.running_runs, color: 'text-yellow-600' },
        { label: 'Success Rate', value: `${stats.success_rate}%`, color: 'text-emerald-600' },
        { label: 'Avg Coverage', value: `${stats.avg_coverage}%`, color: 'text-purple-600' },
      ]
    : [];

  const statusColor: Record<string, string> = {
    ready: 'bg-green-100 text-green-700',
    pending: 'bg-yellow-100 text-yellow-700',
    indexing: 'bg-blue-100 text-blue-700',
    error: 'bg-red-100 text-red-700',
  };

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between" data-tour="welcome">
        <h1 className="text-2xl font-bold text-gray-900">Testing Platform</h1>
        <Link
          href="/testing/onboard"
          className="px-4 py-2 bg-indigo-600 text-white rounded-md text-sm font-medium hover:bg-indigo-700"
        >
          + Onboard Repository
        </Link>
      </div>

      {/* Stats grid */}
      <div data-tour="stats" className={statCards.length > 0 ? '' : 'hidden'}>
        {statCards.length > 0 && (
          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-7 gap-3">
            {statCards.map((card) => (
              <div
                key={card.label}
                className="bg-white rounded-lg border border-gray-200 p-4 text-center"
              >
                <p className="text-xs text-gray-500 uppercase tracking-wide">{card.label}</p>
                <p className={`mt-1 text-xl font-bold ${card.color}`}>{card.value}</p>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Quick actions */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { href: '/testing/onboard', label: 'Onboard Repo', desc: 'Add a new repository for testing', icon: '+', tourKey: 'onboard' },
          { href: '/testing/agents', label: 'Agent Monitor', desc: 'View running agents and results', icon: 'A', tourKey: 'agents' },
          { href: '/testing/coverage', label: 'Coverage', desc: 'Analyze test coverage gaps', icon: 'C', tourKey: 'coverage' },
          { href: '/testing/chat', label: 'Chat', desc: 'Natural language testing assistant', icon: 'Q', tourKey: 'chat' },
        ].map((action) => (
          <Link
            key={action.href}
            href={action.href}
            data-tour={action.tourKey}
            className="block bg-white rounded-lg border border-gray-200 p-5 hover:shadow-md transition-shadow"
          >
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-full bg-indigo-100 flex items-center justify-center text-indigo-600 font-bold text-lg">
                {action.icon}
              </div>
              <div>
                <p className="font-medium text-gray-900">{action.label}</p>
                <p className="text-xs text-gray-500">{action.desc}</p>
              </div>
            </div>
          </Link>
        ))}
      </div>

      {/* Projects list */}
      <div data-tour="projects">
        <h2 className="text-lg font-semibold text-gray-900 mb-4">
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
          <div className="space-y-3">
            {projects.map((project) => (
              <div
                key={project.id}
                className="bg-white rounded-lg border border-gray-200 p-4 flex items-center justify-between hover:shadow-sm transition-shadow"
              >
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-3">
                    <h3 className="font-medium text-gray-900">{project.name}</h3>
                    <span
                      className={`px-2 py-0.5 rounded text-xs font-medium ${
                        statusColor[project.status] || 'bg-gray-100 text-gray-600'
                      }`}
                    >
                      {project.status}
                    </span>
                  </div>
                  <p className="text-sm text-gray-500 truncate mt-1">
                    {project.repo_url || project.local_path}
                  </p>
                  <div className="flex gap-4 mt-1 text-xs text-gray-400">
                    <span>Lang: {project.language}</span>
                    <span>Framework: {project.framework}</span>
                    <span>Tests: {project.testing_framework}</span>
                  </div>
                </div>
                <div className="flex gap-2 ml-4">
                  <Link
                    href={`/testing/coverage?project=${project.id}`}
                    className="px-3 py-1.5 text-xs border border-gray-300 rounded hover:bg-gray-50"
                  >
                    Coverage
                  </Link>
                  <Link
                    href={`/testing/agents?project=${project.id}`}
                    className="px-3 py-1.5 text-xs border border-gray-300 rounded hover:bg-gray-50"
                  >
                    Runs
                  </Link>
                  <Link
                    href={`/testing/chat?project=${project.id}`}
                    className="px-3 py-1.5 text-xs bg-indigo-600 text-white rounded hover:bg-indigo-700"
                  >
                    Chat
                  </Link>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
