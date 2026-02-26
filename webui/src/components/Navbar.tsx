'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useTour, type TourStep } from './TourProvider';

const NAV_ITEMS = [
  { href: '/', label: 'Dashboard' },
  { href: '/testing', label: 'Testing' },
  { href: '/testing/agents', label: 'Agents' },
  { href: '/testing/coverage', label: 'Coverage' },
  { href: '/testing/chat', label: 'Chat' },
  { href: '/sessions', label: 'Sessions' },
  { href: '/config', label: 'Config' },
];

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

export default function Navbar() {
  const pathname = usePathname();
  const { startTour } = useTour();
  const isTestingPage = pathname.startsWith('/testing');

  return (
    <nav className="bg-white border-b border-gray-200">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          <Link href="/" className="text-xl font-bold text-indigo-600">
            Code Autonomy
          </Link>
          <div className="flex items-center space-x-1">
            {NAV_ITEMS.map(({ href, label }) => {
              const active =
                href === '/' ? pathname === '/' : pathname.startsWith(href);
              return (
                <Link
                  key={href}
                  href={href}
                  className={`px-3 py-2 rounded-md text-sm font-medium transition-colors ${
                    active
                      ? 'bg-indigo-100 text-indigo-700'
                      : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
                  }`}
                >
                  {label}
                </Link>
              );
            })}
            {isTestingPage && (
              <button
                data-tour="help"
                onClick={() => startTour(TOUR_STEPS)}
                className="ml-2 w-8 h-8 flex items-center justify-center rounded-full border border-indigo-300 text-indigo-600 hover:bg-indigo-50 text-sm font-bold transition-colors"
                title="Take a tour"
              >
                ?
              </button>
            )}
          </div>
        </div>
      </div>
    </nav>
  );
}
