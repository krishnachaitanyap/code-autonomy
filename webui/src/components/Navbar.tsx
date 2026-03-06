'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useTour, type TourStep } from './TourProvider';

// ---------------------------------------------------------------------------
// Nav structure: groups with separators
// ---------------------------------------------------------------------------

interface NavItem {
  href: string;
  label: string;
  icon: React.ReactNode;
}

interface NavGroup {
  items: NavItem[];
}

const IconDashboard = () => (
  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 5a1 1 0 011-1h4a1 1 0 011 1v5a1 1 0 01-1 1H5a1 1 0 01-1-1V5zm10 0a1 1 0 011-1h4a1 1 0 011 1v3a1 1 0 01-1 1h-4a1 1 0 01-1-1V5zm0 8a1 1 0 011-1h4a1 1 0 011 1v3a1 1 0 01-1 1h-4a1 1 0 01-1-1v-3zM4 13a1 1 0 011-1h4a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6z" />
  </svg>
);

const IconChat = () => (
  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
  </svg>
);

const IconAgents = () => (
  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
  </svg>
);

const IconTesting = () => (
  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19.428 15.428a2 2 0 00-1.022-.547l-2.387-.477a6 6 0 00-3.86.517l-.318.158a6 6 0 01-3.86.517L6.05 15.21a2 2 0 00-1.806.547M8 4h8l-1 1v5.172a2 2 0 00.586 1.414l5 5c1.26 1.26.367 3.414-1.415 3.414H4.828c-1.782 0-2.674-2.154-1.414-3.414l5-5A2 2 0 009 10.172V5L8 4z" />
  </svg>
);

const IconCoverage = () => (
  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
  </svg>
);

const IconSessions = () => (
  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
  </svg>
);

const IconConfig = () => (
  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
  </svg>
);

const IconRepos = () => (
  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
  </svg>
);

const NAV_GROUPS: NavGroup[] = [
  {
    items: [
      { href: '/', label: 'Dashboard', icon: <IconDashboard /> },
      { href: '/testing/chat', label: 'Chat', icon: <IconChat /> },
      { href: '/testing/agents', label: 'Agents', icon: <IconAgents /> },
    ],
  },
  {
    items: [
      { href: '/testing', label: 'Testing', icon: <IconTesting /> },
      { href: '/testing/coverage', label: 'Coverage', icon: <IconCoverage /> },
    ],
  },
  {
    items: [
      { href: '/repos', label: 'Repos', icon: <IconRepos /> },
      { href: '/sessions', label: 'Sessions', icon: <IconSessions /> },
      { href: '/config', label: 'Config', icon: <IconConfig /> },
    ],
  },
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
    title: 'Chat \u2014 Ask / Plan / Agent',
    content:
      'Interact with any codebase through Ask, Plan, or Agent modes. Ask questions, generate plans, or run autonomous coding \u2014 all from a conversational interface.',
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

  return (
    <nav className="bg-white border-b border-gray-200">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-14">
          <Link href="/" className="text-lg font-bold text-indigo-600 flex items-center gap-2">
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
            Code Autonomy
          </Link>
          <div className="flex items-center">
            {NAV_GROUPS.map((group, gi) => (
              <div key={gi} className="flex items-center">
                {gi > 0 && (
                  <div className="h-5 w-px bg-gray-200 mx-1" />
                )}
                {group.items.map(({ href, label, icon }) => {
                  const active =
                    href === '/' ? pathname === '/' : pathname === href || (href !== '/' && pathname.startsWith(href + '/'));
                  return (
                    <Link
                      key={href}
                      href={href}
                      className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-sm font-medium transition-colors ${
                        active
                          ? 'bg-indigo-50 text-indigo-700'
                          : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
                      }`}
                    >
                      {icon}
                      <span className="hidden sm:inline">{label}</span>
                    </Link>
                  );
                })}
              </div>
            ))}
            <div className="h-5 w-px bg-gray-200 mx-1" />
            <button
              data-tour="help"
              onClick={() => startTour(TOUR_STEPS)}
              className="w-7 h-7 flex items-center justify-center rounded-full border border-gray-300 text-gray-500 hover:bg-gray-50 text-xs font-bold transition-colors"
              title="Take a tour"
            >
              ?
            </button>
          </div>
        </div>
      </div>
    </nav>
  );
}
