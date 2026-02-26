'use client';

import Link from 'next/link';
import type { Repo } from '@/lib/api';

interface RepoCardProps {
  repo: Repo;
}

export default function RepoCard({ repo }: RepoCardProps) {
  const platformColor: Record<string, string> = {
    github: 'bg-gray-800 text-white',
    bitbucket: 'bg-blue-600 text-white',
    local: 'bg-green-600 text-white',
  };

  return (
    <div className="bg-white rounded-lg border border-gray-200 p-5 hover:shadow-md transition-shadow">
      <div className="flex items-start justify-between">
        <div className="min-w-0 flex-1">
          <h3 className="text-lg font-semibold text-gray-900 truncate">
            {repo.url || repo.local_path}
          </h3>
          <p className="text-sm text-gray-500 mt-1 truncate">{repo.local_path}</p>
        </div>
        <span
          className={`ml-3 px-2 py-1 rounded text-xs font-medium ${
            platformColor[repo.platform] || 'bg-gray-200 text-gray-700'
          }`}
        >
          {repo.platform}
        </span>
      </div>
      <div className="mt-4 flex items-center justify-between text-sm text-gray-500">
        <span>ID: {repo.id.slice(0, 8)}...</span>
        <Link
          href={`/repos/${repo.id}`}
          className="text-indigo-600 hover:text-indigo-800 font-medium"
        >
          View Details
        </Link>
      </div>
    </div>
  );
}
