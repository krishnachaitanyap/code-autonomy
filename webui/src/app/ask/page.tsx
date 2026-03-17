'use client';

import { useEffect, useState } from 'react';
import { repos, ask, type Repo } from '@/lib/api';

interface QA {
  question: string;
  answer: string;
  sources: string[];
  success: boolean;
}

export default function AskPage() {
  const [repoList, setRepoList] = useState<Repo[]>([]);
  const [selectedRepo, setSelectedRepo] = useState('');
  const [question, setQuestion] = useState('');
  const [loading, setLoading] = useState(false);
  const [history, setHistory] = useState<QA[]>([]);
  const [error, setError] = useState('');

  useEffect(() => {
    repos.list().then(setRepoList).catch(console.error);
  }, []);

  async function submitQuestion(q: string) {
    if (!selectedRepo || !q.trim()) return;

    setLoading(true);
    setError('');
    try {
      const result = await ask.question(selectedRepo, q);
      setHistory((prev) => [
        { question: q, answer: result.answer, sources: result.sources, success: result.success },
        ...prev,
      ]);
      setQuestion('');
    } catch (err: any) {
      setError(err.message || 'Failed to get answer');
    } finally {
      setLoading(false);
    }
  }

  async function handleAsk(e: React.FormEvent) {
    e.preventDefault();
    submitQuestion(question);
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-gray-900">Ask</h1>

      <form onSubmit={handleAsk} className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Repository
          </label>
          <select
            value={selectedRepo}
            onChange={(e) => setSelectedRepo(e.target.value)}
            required
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
          >
            <option value="">Select a repo...</option>
            {repoList.map((r) => (
              <option key={r.id} value={r.id}>
                {r.nickname || r.url || r.local_path}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Question
          </label>
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            required
            rows={3}
            placeholder="Ask a question about the codebase..."
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
          />
        </div>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button
          type="submit"
          disabled={loading}
          className="px-4 py-2 bg-indigo-600 text-white rounded-md text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
        >
          {loading ? 'Thinking...' : 'Ask'}
        </button>
      </form>

      {/* Q&A History */}
      <div className="space-y-4">
        {history.map((qa, i) => (
          <div
            key={i}
            className="bg-white rounded-lg border border-gray-200 p-5 space-y-3"
          >
            {!qa.success && qa.answer && (
              <div className="bg-amber-50 border border-amber-200 rounded-md px-3 py-2 flex items-center justify-between gap-3">
                <p className="text-sm text-amber-800">
                  This answer is partial — the agent ran out of exploration time.
                </p>
                <button
                  onClick={() => submitQuestion(qa.question)}
                  disabled={loading}
                  className="shrink-0 px-3 py-1.5 bg-amber-600 text-white rounded-md text-xs font-medium hover:bg-amber-700 disabled:opacity-50"
                >
                  {loading ? 'Exploring...' : 'Explore More'}
                </button>
              </div>
            )}
            <div>
              <p className="text-xs text-gray-500 uppercase mb-1">Question</p>
              <p className="text-sm font-medium text-gray-900">{qa.question}</p>
            </div>
            <div>
              <p className="text-xs text-gray-500 uppercase mb-1">Answer</p>
              <p className="text-sm text-gray-800 whitespace-pre-wrap">
                {qa.answer}
              </p>
            </div>
            {qa.sources.length > 0 && (
              <div>
                <p className="text-xs text-gray-500 uppercase mb-1">Sources</p>
                <ul className="text-sm text-gray-600 space-y-1">
                  {qa.sources.map((src, j) => (
                    <li key={j} className="font-mono text-xs bg-gray-50 rounded px-2 py-1">
                      {src}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
