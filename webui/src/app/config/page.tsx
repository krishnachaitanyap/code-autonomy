'use client';

import { useEffect, useState } from 'react';
import { config } from '@/lib/api';

export default function ConfigPage() {
  const [configData, setConfigData] = useState<Record<string, any>>({});
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  useEffect(() => {
    async function load() {
      try {
        const data = await config.get();
        setConfigData(data.config);
      } catch (err) {
        console.error('Failed to load config:', err);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  function handleEdit() {
    setEditText(JSON.stringify(configData, null, 2));
    setEditing(true);
    setError('');
    setSuccess('');
  }

  async function handleSave() {
    setError('');
    setSaving(true);
    try {
      const parsed = JSON.parse(editText);
      const result = await config.update(parsed);
      setConfigData(result.config);
      setEditing(false);
      setSuccess('Config saved successfully.');
      setTimeout(() => setSuccess(''), 3000);
    } catch (err: any) {
      if (err instanceof SyntaxError) {
        setError('Invalid JSON');
      } else {
        setError(err.message || 'Failed to save config');
      }
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <p className="text-gray-500">Loading config...</p>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Configuration</h1>
        {!editing ? (
          <button
            onClick={handleEdit}
            className="px-4 py-2 bg-indigo-600 text-white rounded-md text-sm font-medium hover:bg-indigo-700"
          >
            Edit
          </button>
        ) : (
          <div className="flex gap-2">
            <button
              onClick={() => setEditing(false)}
              className="px-4 py-2 border border-gray-300 rounded-md text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="px-4 py-2 bg-indigo-600 text-white rounded-md text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
            >
              {saving ? 'Saving...' : 'Save'}
            </button>
          </div>
        )}
      </div>

      {success && (
        <p className="text-sm text-green-600 bg-green-50 rounded px-3 py-2">
          {success}
        </p>
      )}
      {error && (
        <p className="text-sm text-red-600 bg-red-50 rounded px-3 py-2">
          {error}
        </p>
      )}

      {editing ? (
        <textarea
          value={editText}
          onChange={(e) => setEditText(e.target.value)}
          rows={30}
          className="w-full font-mono text-sm border border-gray-300 rounded-lg p-4 focus:ring-indigo-500 focus:border-indigo-500"
        />
      ) : (
        <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
          {Object.entries(configData).map(([section, values]) => (
            <div key={section} className="border-b border-gray-200 last:border-b-0">
              <div className="bg-gray-50 px-4 py-2">
                <h3 className="text-sm font-semibold text-gray-700">{section}</h3>
              </div>
              <div className="px-4 py-3">
                {typeof values === 'object' && values !== null ? (
                  <dl className="space-y-2">
                    {Object.entries(values as Record<string, any>).map(
                      ([key, val]) => (
                        <div key={key} className="flex">
                          <dt className="text-sm text-gray-500 w-48 flex-shrink-0">
                            {key}
                          </dt>
                          <dd className="text-sm text-gray-900 font-mono">
                            {typeof val === 'object'
                              ? JSON.stringify(val)
                              : String(val)}
                          </dd>
                        </div>
                      ),
                    )}
                  </dl>
                ) : (
                  <p className="text-sm text-gray-900 font-mono">{String(values)}</p>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
