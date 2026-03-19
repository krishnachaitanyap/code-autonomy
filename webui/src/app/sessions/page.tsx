'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { sessions, repos, type Session, type Repo } from '@/lib/api';
import BranchSelect from '@/components/BranchSelect';

export default function SessionsPage() {
  const [sessionList, setSessionList] = useState<Session[]>([]);
  const [repoList, setRepoList] = useState<Repo[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterRepo, setFilterRepo] = useState('');
  const [filterStatus, setFilterStatus] = useState('');

  // New session form state
  const [showForm, setShowForm] = useState(false);
  const [newRepoId, setNewRepoId] = useState('');
  const [newMode, setNewMode] = useState('agent');
  const [newBranch, setNewBranch] = useState('main');
  const [newRequirements, setNewRequirements] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  async function loadData() {
    try {
      const [s, r] = await Promise.all([
        sessions.list({
          repo_id: filterRepo || undefined,
          status: filterStatus || undefined,
          limit: 50,
        }),
        repos.list(),
      ]);
      setSessionList(s.sessions);
      setRepoList(r);
    } catch (err) {
      console.error('Failed to load sessions:', err);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
  }, [filterRepo, filterStatus]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    setSubmitting(true);
    try {
      const session = await sessions.create({
        repo_id: newRepoId || null,
        mode: newMode,
        branch: newBranch,
        requirements: newRequirements,
      });
      setShowForm(false);
      setNewRequirements('');
      // Navigate to the new session
      window.location.href = `/sessions/${session.id}`;
    } catch (err: any) {
      setError(err.message || 'Failed to create session');
    } finally {
      setSubmitting(false);
    }
  }

  const statusColor: Record<string, string> = {
    completed: 'bg-green-100 text-green-700',
    running: 'bg-blue-100 text-blue-700',
    failed: 'bg-red-100 text-red-700',
    paused: 'bg-yellow-100 text-yellow-700',
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Sessions</h1>
        <button
          onClick={() => setShowForm(!showForm)}
          className="px-4 py-2 bg-indigo-600 text-white rounded-md text-sm font-medium hover:bg-indigo-700 transition-colors"
        >
          {showForm ? 'Cancel' : 'New Session'}
        </button>
      </div>

      {showForm && (
        <form
          onSubmit={handleCreate}
          className="bg-white rounded-lg border border-gray-200 p-6 space-y-4"
        >
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Repository
            </label>
            <select
              value={newRepoId}
              onChange={(e) => setNewRepoId(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
            >
              <option value="">No repository (tool-only)</option>
              {repoList.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.nickname || r.url || r.local_path}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Mode
            </label>
            <select
              value={newMode}
              onChange={(e) => setNewMode(e.target.value)}
              className="border border-gray-300 rounded-md px-3 py-2 text-sm"
            >
              <option value="agent">Agent</option>
              <option value="plan">Plan</option>
              <option value="ask">Ask</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Branch
            </label>
            <BranchSelect
              repoId={newRepoId}
              value={newBranch}
              onChange={setNewBranch}
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Requirements
            </label>
            <textarea
              value={newRequirements}
              onChange={(e) => setNewRequirements(e.target.value)}
              required
              rows={4}
              placeholder="Describe what you want the agent to do..."
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
            />
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <button
            type="submit"
            disabled={submitting}
            className="px-4 py-2 bg-indigo-600 text-white rounded-md text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
          >
            {submitting ? 'Starting...' : 'Start Session'}
          </button>
        </form>
      )}

      {/* Filters */}
      <div className="flex gap-4">
        <select
          value={filterRepo}
          onChange={(e) => setFilterRepo(e.target.value)}
          className="border border-gray-300 rounded-md px-3 py-2 text-sm"
        >
          <option value="">All Repos</option>
          {repoList.map((r) => (
            <option key={r.id} value={r.id}>
              {r.nickname || r.url || r.local_path}
            </option>
          ))}
        </select>
        <select
          value={filterStatus}
          onChange={(e) => setFilterStatus(e.target.value)}
          className="border border-gray-300 rounded-md px-3 py-2 text-sm"
        >
          <option value="">All Statuses</option>
          <option value="running">Running</option>
          <option value="completed">Completed</option>
          <option value="failed">Failed</option>
          <option value="paused">Paused</option>
        </select>
      </div>

      {/* Session list */}
      {loading ? (
        <p className="text-gray-500">Loading sessions...</p>
      ) : sessionList.length === 0 ? (
        <p className="text-gray-500">No sessions found.</p>
      ) : (
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Mode
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Status
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Requirements
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Turns
                </th>
                <th className="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase">
                  Created
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {sessionList.map((session) => (
                <tr key={session.id} className="hover:bg-gray-50">
                  <td className="px-4 py-3 text-sm font-medium text-gray-900">
                    <Link
                      href={`/sessions/${session.id}`}
                      className="text-indigo-600 hover:text-indigo-800"
                    >
                      {session.mode}
                    </Link>
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`px-2 py-0.5 rounded text-xs font-medium ${
                        statusColor[session.status] || 'bg-gray-100 text-gray-600'
                      }`}
                    >
                      {session.status}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-600 max-w-md truncate">
                    {session.requirements}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-500">
                    {session.turns_used}
                  </td>
                  <td className="px-4 py-3 text-sm text-gray-500">
                    {new Date(session.created_at).toLocaleDateString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
