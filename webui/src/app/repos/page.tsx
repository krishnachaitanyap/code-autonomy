'use client';

import { useEffect, useState } from 'react';
import { repos, type Repo } from '@/lib/api';
import RepoCard from '@/components/RepoCard';

export default function ReposPage() {
  const [repoList, setRepoList] = useState<Repo[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [url, setUrl] = useState('');
  const [localPath, setLocalPath] = useState('');
  const [platform, setPlatform] = useState('github');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  async function loadRepos() {
    try {
      const data = await repos.list();
      setRepoList(data);
    } catch (err) {
      console.error('Failed to load repos:', err);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadRepos();
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setSubmitting(true);
    try {
      await repos.create({
        url: url || undefined,
        local_path: localPath || undefined,
        platform,
      });
      setUrl('');
      setLocalPath('');
      setShowForm(false);
      await loadRepos();
    } catch (err: any) {
      setError(err.message || 'Failed to add repo');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Repositories</h1>
        <button
          onClick={() => setShowForm(!showForm)}
          className="px-4 py-2 bg-indigo-600 text-white rounded-md text-sm font-medium hover:bg-indigo-700 transition-colors"
        >
          {showForm ? 'Cancel' : 'Add Repo'}
        </button>
      </div>

      {showForm && (
        <form
          onSubmit={handleSubmit}
          className="bg-white rounded-lg border border-gray-200 p-6 space-y-4"
        >
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Git URL
            </label>
            <input
              type="text"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://github.com/org/repo.git"
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-indigo-500 focus:border-indigo-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Local Path (alternative)
            </label>
            <input
              type="text"
              value={localPath}
              onChange={(e) => setLocalPath(e.target.value)}
              placeholder="/path/to/local/repo"
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-indigo-500 focus:border-indigo-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Platform
            </label>
            <select
              value={platform}
              onChange={(e) => setPlatform(e.target.value)}
              className="border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-indigo-500 focus:border-indigo-500"
            >
              <option value="github">GitHub</option>
              <option value="bitbucket">Bitbucket</option>
              <option value="local">Local</option>
            </select>
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <button
            type="submit"
            disabled={submitting}
            className="px-4 py-2 bg-indigo-600 text-white rounded-md text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors"
          >
            {submitting ? 'Adding...' : 'Add Repository'}
          </button>
        </form>
      )}

      {loading ? (
        <p className="text-gray-500">Loading repos...</p>
      ) : repoList.length === 0 ? (
        <p className="text-gray-500">No repos registered yet.</p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {repoList.map((repo) => (
            <RepoCard key={repo.id} repo={repo} />
          ))}
        </div>
      )}
    </div>
  );
}
