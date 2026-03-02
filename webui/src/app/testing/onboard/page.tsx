'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { repos, testing, type Repo } from '@/lib/api';

export default function OnboardPage() {
  const router = useRouter();
  const [existingRepos, setExistingRepos] = useState<Repo[]>([]);
  const [selectedRepoId, setSelectedRepoId] = useState('');
  const [form, setForm] = useState({
    name: '',
    repo_id: '',
    repo_url: '',
    local_path: '',
    language: 'auto',
    framework: 'auto',
    testing_framework: 'auto',
    branch: 'main',
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    repos.list().then(setExistingRepos).catch(() => {});
  }, []);

  const handleRepoSelect = (repoId: string) => {
    setSelectedRepoId(repoId);
    if (repoId === '' || repoId === '__new__') {
      setForm({ ...form, repo_id: '', repo_url: '', local_path: '' });
      return;
    }
    const repo = existingRepos.find((r) => r.id === repoId);
    if (repo) {
      setForm({
        ...form,
        repo_id: repo.id,
        repo_url: repo.url || '',
        local_path: repo.local_path || '',
      });
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.name) {
      setError('Project name is required');
      return;
    }
    if (!form.repo_id && !form.repo_url && !form.local_path) {
      setError('Either select an existing repository or provide a URL / local path');
      return;
    }

    setSubmitting(true);
    setError('');
    try {
      const project = await testing.createProject(form);
      // Trigger discovery
      await testing.discoverProject(project.id);
      router.push('/testing');
    } catch (err: any) {
      setError(err.message || 'Failed to onboard repository');
    } finally {
      setSubmitting(false);
    }
  };

  const isExistingRepo = selectedRepoId !== '' && selectedRepoId !== '__new__';

  return (
    <div className="max-w-2xl mx-auto">
      <h1 className="text-2xl font-bold text-gray-900 mb-6">Onboard Repository</h1>

      <form onSubmit={handleSubmit} className="space-y-6 bg-white rounded-lg border border-gray-200 p-6">
        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded text-sm">
            {error}
          </div>
        )}

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Repository
          </label>
          <select
            value={selectedRepoId}
            onChange={(e) => handleRepoSelect(e.target.value)}
            className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            <option value="">-- Select Repository --</option>
            {existingRepos.map((r) => (
              <option key={r.id} value={r.id}>
                {r.url || r.local_path || r.id}
              </option>
            ))}
            <option value="__new__">+ New Repository</option>
          </select>
          <p className="text-xs text-gray-400 mt-1">
            Select an existing repo or add a new one
          </p>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Project Name *
          </label>
          <input
            type="text"
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="My Service"
            className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </div>

        {!isExistingRepo && (
          <>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Repository URL
              </label>
              <input
                type="text"
                value={form.repo_url}
                onChange={(e) => setForm({ ...form, repo_url: e.target.value })}
                placeholder="https://github.com/org/repo.git"
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
              <p className="text-xs text-gray-400 mt-1">GitHub, Bitbucket, or any Git URL</p>
            </div>

            <div className="relative">
              <div className="absolute inset-0 flex items-center">
                <div className="w-full border-t border-gray-200" />
              </div>
              <div className="relative flex justify-center text-xs uppercase">
                <span className="bg-white px-2 text-gray-500">or</span>
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Local Path
              </label>
              <input
                type="text"
                value={form.local_path}
                onChange={(e) => setForm({ ...form, local_path: e.target.value })}
                placeholder="/path/to/project"
                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
          </>
        )}

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Language</label>
            <select
              value={form.language}
              onChange={(e) => setForm({ ...form, language: e.target.value })}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              <option value="auto">Auto-detect</option>
              <option value="java">Java</option>
              <option value="python">Python</option>
              <option value="javascript">JavaScript</option>
              <option value="typescript">TypeScript</option>
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Framework</label>
            <select
              value={form.framework}
              onChange={(e) => setForm({ ...form, framework: e.target.value })}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              <option value="auto">Auto-detect</option>
              <option value="spring">Spring / Spring Boot</option>
              <option value="django">Django</option>
              <option value="flask">Flask</option>
              <option value="fastapi">FastAPI</option>
              <option value="express">Express.js</option>
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Testing Framework</label>
            <select
              value={form.testing_framework}
              onChange={(e) => setForm({ ...form, testing_framework: e.target.value })}
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              <option value="auto">Auto-detect</option>
              <option value="junit">JUnit</option>
              <option value="pytest">pytest</option>
              <option value="cucumber">Cucumber / BDD</option>
              <option value="jest">Jest</option>
              <option value="mocha">Mocha</option>
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Branch</label>
            <input
              type="text"
              value={form.branch}
              onChange={(e) => setForm({ ...form, branch: e.target.value })}
              placeholder="main"
              className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>
        </div>

        <div className="flex justify-end gap-3 pt-4 border-t border-gray-200">
          <button
            type="button"
            onClick={() => router.push('/testing')}
            className="px-4 py-2 text-sm border border-gray-300 rounded-md hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={submitting}
            className="px-4 py-2 text-sm bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:opacity-50"
          >
            {submitting ? 'Onboarding...' : 'Onboard & Discover'}
          </button>
        </div>
      </form>
    </div>
  );
}
