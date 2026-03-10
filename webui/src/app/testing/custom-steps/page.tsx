'use client';

import { Suspense, useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { testing, type TestProject, type CustomStep } from '@/lib/api';

export default function CustomStepsPageWrapper() {
  return (
    <Suspense fallback={<div className="flex items-center justify-center min-h-[60vh]"><div className="w-6 h-6 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin" /></div>}>
      <CustomStepsPage />
    </Suspense>
  );
}

function CustomStepsPage() {
  const searchParams = useSearchParams();
  const projectFilter = searchParams.get('project') || '';

  const [projects, setProjects] = useState<TestProject[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState(projectFilter);
  const [steps, setSteps] = useState<CustomStep[]>([]);
  const [loading, setLoading] = useState(true);
  const [discovering, setDiscovering] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [newStep, setNewStep] = useState({
    name: '',
    step_type: 'given',
    pattern: '',
    implementation: '',
    language: 'java',
    tags: '',
  });

  useEffect(() => {
    async function load() {
      try {
        const p = await testing.listProjects({ limit: 100 });
        setProjects(p.projects);
        if (!selectedProjectId && p.projects.length > 0) {
          setSelectedProjectId(p.projects[0].id);
        }
      } catch (err) {
        console.error(err);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  useEffect(() => {
    if (selectedProjectId) loadSteps();
  }, [selectedProjectId]);

  async function loadSteps() {
    try {
      const s = await testing.listCustomSteps(selectedProjectId);
      setSteps(s);
    } catch {
      setSteps([]);
    }
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    try {
      await testing.createCustomStep({
        project_id: selectedProjectId,
        name: newStep.name,
        step_type: newStep.step_type,
        pattern: newStep.pattern,
        implementation: newStep.implementation,
        language: newStep.language,
        tags: newStep.tags ? newStep.tags.split(',').map((t) => t.trim()) : [],
      });
      setShowNew(false);
      setNewStep({ name: '', step_type: 'given', pattern: '', implementation: '', language: 'java', tags: '' });
      loadSteps();
    } catch (err) {
      console.error(err);
    }
  }

  async function handleDiscover() {
    setDiscovering(true);
    try {
      await testing.discoverCustomSteps(selectedProjectId);
      loadSteps();
    } catch (err) {
      console.error(err);
    } finally {
      setDiscovering(false);
    }
  }

  async function handleDelete(stepId: string) {
    try {
      await testing.deleteCustomStep(stepId);
      loadSteps();
    } catch (err) {
      console.error(err);
    }
  }

  const stepTypeColor: Record<string, string> = {
    given: 'bg-blue-100 text-blue-700',
    when: 'bg-yellow-100 text-yellow-700',
    then: 'bg-green-100 text-green-700',
    and: 'bg-gray-100 text-gray-700',
  };

  if (loading) {
    return <p className="text-gray-500">Loading custom steps...</p>;
  }

  // Group steps by source
  const userSteps = steps.filter((s) => s.source === 'user');
  const discoveredSteps = steps.filter((s) => s.source === 'discovered');
  const generatedSteps = steps.filter((s) => s.source === 'generated');

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Custom Steps</h1>
        <div className="flex items-center gap-3">
          <select
            value={selectedProjectId}
            onChange={(e) => setSelectedProjectId(e.target.value)}
            className="px-3 py-2 border border-gray-300 rounded-md text-sm"
          >
            <option value="">Select project...</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
          <button
            onClick={handleDiscover}
            disabled={!selectedProjectId || discovering}
            className="px-4 py-2 border border-indigo-300 text-indigo-600 rounded-md text-sm font-medium hover:bg-indigo-50 disabled:opacity-50"
          >
            {discovering ? 'Discovering...' : 'Auto-Discover'}
          </button>
          <button
            onClick={() => setShowNew(!showNew)}
            disabled={!selectedProjectId}
            className="px-4 py-2 bg-indigo-600 text-white rounded-md text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
          >
            + New Step
          </button>
        </div>
      </div>

      {/* New step form */}
      {showNew && (
        <form onSubmit={handleCreate} className="bg-white rounded-lg border border-gray-200 p-5 space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Name</label>
              <input
                type="text"
                value={newStep.name}
                onChange={(e) => setNewStep({ ...newStep, name: e.target.value })}
                placeholder="User is authenticated"
                className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
                required
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Type</label>
              <select
                value={newStep.step_type}
                onChange={(e) => setNewStep({ ...newStep, step_type: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
              >
                <option value="given">Given</option>
                <option value="when">When</option>
                <option value="then">Then</option>
                <option value="and">And</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Language</label>
              <select
                value={newStep.language}
                onChange={(e) => setNewStep({ ...newStep, language: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
              >
                <option value="java">Java</option>
                <option value="python">Python</option>
              </select>
            </div>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Gherkin Pattern</label>
            <input
              type="text"
              value={newStep.pattern}
              onChange={(e) => setNewStep({ ...newStep, pattern: e.target.value })}
              placeholder="the user {string} is authenticated with role {string}"
              className="w-full px-3 py-2 border border-gray-300 rounded text-sm font-mono"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Implementation</label>
            <textarea
              value={newStep.implementation}
              onChange={(e) => setNewStep({ ...newStep, implementation: e.target.value })}
              placeholder="@Given(&quot;the user {string} is authenticated with role {string}&quot;)&#10;public void userIsAuthenticated(String user, String role) {&#10;  // implementation&#10;}"
              rows={5}
              className="w-full px-3 py-2 border border-gray-300 rounded text-sm font-mono"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Tags (comma-separated)</label>
            <input
              type="text"
              value={newStep.tags}
              onChange={(e) => setNewStep({ ...newStep, tags: e.target.value })}
              placeholder="auth, common"
              className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
            />
          </div>
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => setShowNew(false)} className="px-3 py-1.5 text-sm border border-gray-300 rounded hover:bg-gray-50">
              Cancel
            </button>
            <button type="submit" className="px-3 py-1.5 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700">
              Create Step
            </button>
          </div>
        </form>
      )}

      {/* Steps list */}
      {!selectedProjectId ? (
        <div className="bg-white rounded-lg border border-gray-200 p-8 text-center text-gray-500">
          Select a project to manage custom steps
        </div>
      ) : steps.length === 0 ? (
        <div className="bg-white rounded-lg border border-gray-200 p-8 text-center text-gray-500">
          <p className="mb-4">No custom steps defined yet.</p>
          <p className="text-xs">Click &quot;Auto-Discover&quot; to find step definitions in your codebase, or create new ones manually.</p>
        </div>
      ) : (
        <div className="space-y-6">
          {[
            { label: 'User-Defined Steps', items: userSteps, color: 'border-indigo-200' },
            { label: 'Auto-Discovered Steps', items: discoveredSteps, color: 'border-green-200' },
            { label: 'Generated Steps', items: generatedSteps, color: 'border-purple-200' },
          ]
            .filter((group) => group.items.length > 0)
            .map((group) => (
              <div key={group.label}>
                <h3 className="text-sm font-medium text-gray-700 mb-2">
                  {group.label} ({group.items.length})
                </h3>
                <div className="space-y-2">
                  {group.items.map((step) => (
                    <div
                      key={step.id}
                      className={`bg-white rounded-lg border ${group.color} p-4`}
                    >
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                          <span className={`text-xs px-2 py-0.5 rounded font-medium ${stepTypeColor[step.step_type] || 'bg-gray-100'}`}>
                            {step.step_type.toUpperCase()}
                          </span>
                          <span className="text-sm font-medium text-gray-900">{step.name}</span>
                          <span className="text-xs text-gray-400">{step.language}</span>
                        </div>
                        <button
                          onClick={() => handleDelete(step.id)}
                          className="text-xs text-red-600 hover:text-red-800"
                        >
                          Delete
                        </button>
                      </div>
                      {step.pattern && (
                        <p className="text-xs font-mono text-indigo-600 bg-indigo-50 px-3 py-1.5 rounded mb-2">
                          {step.pattern}
                        </p>
                      )}
                      {step.implementation && (
                        <pre className="text-xs text-gray-600 bg-gray-50 px-3 py-2 rounded overflow-x-auto max-h-32">
                          {step.implementation}
                        </pre>
                      )}
                      {step.tags && step.tags.length > 0 && (
                        <div className="flex gap-1 mt-2">
                          {step.tags.map((tag) => (
                            <span key={tag} className="text-xs bg-gray-100 text-gray-500 px-2 py-0.5 rounded">
                              {tag}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ))}
        </div>
      )}
    </div>
  );
}
