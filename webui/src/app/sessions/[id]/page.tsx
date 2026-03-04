'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import { sessions, type Session } from '@/lib/api';
import { useSessionStream } from '@/lib/websocket';
import SessionLog from '@/components/SessionLog';

export default function SessionDetailPage() {
  const params = useParams();
  const sessionId = params.id as string;
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const { messages, connected, reconnecting, disconnect } = useSessionStream(
    session?.status === 'running' ? sessionId : null,
  );

  useEffect(() => {
    async function load() {
      try {
        const data = await sessions.get(sessionId);
        setSession(data);
      } catch (err: any) {
        setError(err.message || 'Failed to load session');
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [sessionId]);

  // Poll session status while running
  useEffect(() => {
    if (session?.status !== 'running') return;
    const interval = setInterval(async () => {
      try {
        const updated = await sessions.get(sessionId);
        setSession(updated);
        if (updated.status !== 'running') {
          disconnect();
        }
      } catch {
        // ignore polling errors
      }
    }, 5000);
    return () => clearInterval(interval);
  }, [session?.status, sessionId, disconnect]);

  async function handleCancel() {
    try {
      await sessions.cancel(sessionId);
      const updated = await sessions.get(sessionId);
      setSession(updated);
    } catch (err: any) {
      setError(err.message);
    }
  }

  async function handleResume() {
    try {
      const resumed = await sessions.resume(sessionId);
      setSession(resumed);
    } catch (err: any) {
      setError(err.message);
    }
  }

  if (loading) return <p className="text-gray-500">Loading session...</p>;
  if (error) return <p className="text-red-600">{error}</p>;
  if (!session) return <p className="text-gray-500">Session not found.</p>;

  const statusColor: Record<string, string> = {
    completed: 'bg-green-100 text-green-700',
    running: 'bg-blue-100 text-blue-700',
    failed: 'bg-red-100 text-red-700',
    paused: 'bg-yellow-100 text-yellow-700',
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">
            Session: {session.mode}
          </h1>
          <p className="text-sm text-gray-500 mt-1">ID: {session.id}</p>
        </div>
        <div className="flex items-center gap-3">
          <span
            className={`px-3 py-1 rounded-full text-sm font-medium ${
              statusColor[session.status] || 'bg-gray-100 text-gray-600'
            }`}
          >
            {session.status}
          </span>
          {session.status === 'running' && (
            <button
              onClick={handleCancel}
              className="px-3 py-1 bg-red-600 text-white rounded-md text-sm hover:bg-red-700"
            >
              Cancel
            </button>
          )}
          {session.status === 'paused' && (
            <button
              onClick={handleResume}
              className="px-3 py-1 bg-indigo-600 text-white rounded-md text-sm hover:bg-indigo-700"
            >
              Resume
            </button>
          )}
        </div>
      </div>

      {/* Session info */}
      <div className="bg-white rounded-lg border border-gray-200 p-6 space-y-4">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div>
            <p className="text-xs text-gray-500 uppercase">Mode</p>
            <p className="text-sm font-medium">{session.mode}</p>
          </div>
          <div>
            <p className="text-xs text-gray-500 uppercase">Turns Used</p>
            <p className="text-sm font-medium">{session.turns_used}</p>
          </div>
          <div>
            <p className="text-xs text-gray-500 uppercase">Created</p>
            <p className="text-sm font-medium">
              {new Date(session.created_at).toLocaleString()}
            </p>
          </div>
          <div>
            <p className="text-xs text-gray-500 uppercase">Completed</p>
            <p className="text-sm font-medium">
              {session.completed_at
                ? new Date(session.completed_at).toLocaleString()
                : '-'}
            </p>
          </div>
        </div>

        <div>
          <p className="text-xs text-gray-500 uppercase mb-1">Requirements</p>
          <p className="text-sm text-gray-800 whitespace-pre-wrap bg-gray-50 rounded p-3">
            {session.requirements}
          </p>
        </div>

        {session.result_summary && (
          <div>
            <p className="text-xs text-gray-500 uppercase mb-1">Result Summary</p>
            <p className="text-sm text-gray-800 whitespace-pre-wrap bg-gray-50 rounded p-3">
              {session.result_summary}
            </p>
          </div>
        )}
      </div>

      {/* Live log (only when running) */}
      {session.status === 'running' && (
        <SessionLog messages={messages} connected={connected} reconnecting={reconnecting} />
      )}
    </div>
  );
}
