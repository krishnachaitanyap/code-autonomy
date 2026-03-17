'use client';

import Link from 'next/link';
import type { Repo } from '@/lib/api';

interface RepoCardProps {
  repo: Repo;
  branchCount?: number;
  onDelete?: (id: string) => void;
}

export default function RepoCard({ repo, branchCount, onDelete }: RepoCardProps) {
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
            {repo.nickname || repo.url || repo.local_path}
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
        <div className="flex items-center gap-3">
          <span>ID: {repo.id.slice(0, 8)}...</span>
          {branchCount !== undefined && (
            <span className="inline-flex items-center gap-1 text-gray-500">
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 3v12m0 0a3 3 0 103 3m-3-3a3 3 0 11-3 3m12-6a3 3 0 100-6 3 3 0 000 6zm0 0l-6 6" />
              </svg>
              {branchCount} {branchCount === 1 ? 'branch' : 'branches'}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          {onDelete && (
            <button
              onClick={(e) => { e.preventDefault(); onDelete(repo.id); }}
              className="text-red-600 hover:text-red-800 font-medium"
            >
              Delete
            </button>
          )}
          <Link
            href={`/repos/${repo.id}`}
            className="text-indigo-600 hover:text-indigo-800 font-medium"
          >
            View Details
          </Link>
        </div>
      </div>
    </div>
  );
}
