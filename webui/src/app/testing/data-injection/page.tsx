'use client';

import { useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import { testing, type TestProject, type DataInjectionConfig } from '@/lib/api';

export default function DataInjectionPage() {
  const searchParams = useSearchParams();
  const projectFilter = searchParams.get('project') || '';

  const [projects, setProjects] = useState<TestProject[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState(projectFilter);
  const [configs, setConfigs] = useState<DataInjectionConfig[]>([]);
  const [loading, setLoading] = useState(true);
  const [showNew, setShowNew] = useState(false);
  const [newConfig, setNewConfig] = useState({
    name: '',
    strategy: 'synthetic',
    target_entity: '',
    schema_text: '',
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
    if (selectedProjectId) loadConfigs();
  }, [selectedProjectId]);

  async function loadConfigs() {
    try {
      const c = await testing.listDataInjection(selectedProjectId);
      setConfigs(c);
    } catch {
      setConfigs([]);
    }
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    let schema: Record<string, any> = {};
    try {
      schema = newConfig.schema_text ? JSON.parse(newConfig.schema_text) : {};
    } catch {
      alert('Invalid JSON in schema definition');
      return;
    }
    try {
      await testing.createDataInjection({
        project_id: selectedProjectId,
        name: newConfig.name,
        strategy: newConfig.strategy,
        target_entity: newConfig.target_entity,
        schema_definition: schema,
      });
      setShowNew(false);
      setNewConfig({ name: '', strategy: 'synthetic', target_entity: '', schema_text: '' });
      loadConfigs();
    } catch (err) {
      console.error(err);
    }
  }

  async function handleGenerateSample(configId: string) {
    try {
      await testing.generateSampleData(configId, 5);
      loadConfigs();
    } catch (err) {
      console.error(err);
    }
  }

  async function handleDelete(configId: string) {
    try {
      await testing.deleteDataInjection(configId);
      loadConfigs();
    } catch (err) {
      console.error(err);
    }
  }

  if (loading) {
    return <p className="text-gray-500">Loading data injection configs...</p>;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-gray-900">Data Injection</h1>
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
            onClick={() => setShowNew(!showNew)}
            disabled={!selectedProjectId}
            className="px-4 py-2 bg-indigo-600 text-white rounded-md text-sm font-medium hover:bg-indigo-700 disabled:opacity-50"
          >
            + New Config
          </button>
        </div>
      </div>

      {/* New config form */}
      {showNew && (
        <form onSubmit={handleCreate} className="bg-white rounded-lg border border-gray-200 p-5 space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Name</label>
              <input
                type="text"
                value={newConfig.name}
                onChange={(e) => setNewConfig({ ...newConfig, name: e.target.value })}
                placeholder="User Data Factory"
                className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
                required
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Strategy</label>
              <select
                value={newConfig.strategy}
                onChange={(e) => setNewConfig({ ...newConfig, strategy: e.target.value })}
                className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
              >
                <option value="synthetic">Synthetic</option>
                <option value="factory">Factory</option>
                <option value="pool">Data Pool</option>
                <option value="masked">Masked Production</option>
                <option value="environment">Environment-Aware</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Target Entity</label>
              <input
                type="text"
                value={newConfig.target_entity}
                onChange={(e) => setNewConfig({ ...newConfig, target_entity: e.target.value })}
                placeholder="User, Account, Order..."
                className="w-full px-3 py-2 border border-gray-300 rounded text-sm"
              />
            </div>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              Schema Definition (JSON)
            </label>
            <textarea
              value={newConfig.schema_text}
              onChange={(e) => setNewConfig({ ...newConfig, schema_text: e.target.value })}
              placeholder={'{\n  "firstName": {"type": "string"},\n  "email": {"type": "string"},\n  "accountId": {"type": "integer"}\n}'}
              rows={5}
              className="w-full px-3 py-2 border border-gray-300 rounded text-sm font-mono"
            />
          </div>
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => setShowNew(false)} className="px-3 py-1.5 text-sm border border-gray-300 rounded hover:bg-gray-50">
              Cancel
            </button>
            <button type="submit" className="px-3 py-1.5 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700">
              Create Config
            </button>
          </div>
        </form>
      )}

      {/* Configs list */}
      {!selectedProjectId ? (
        <div className="bg-white rounded-lg border border-gray-200 p-8 text-center text-gray-500">
          Select a project to manage data injection configs
        </div>
      ) : configs.length === 0 ? (
        <div className="bg-white rounded-lg border border-gray-200 p-8 text-center text-gray-500">
          No data injection configs yet. Create one to generate test data.
        </div>
      ) : (
        <div className="space-y-4">
          {configs.map((config) => (
            <div key={config.id} className="bg-white rounded-lg border border-gray-200 p-5">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-3">
                  <h3 className="font-medium text-gray-900">{config.name}</h3>
                  <span className="text-xs bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded">
                    {config.strategy}
                  </span>
                  {config.target_entity && (
                    <span className="text-xs text-gray-400">{config.target_entity}</span>
                  )}
                </div>
                <div className="flex gap-2">
                  <button
                    onClick={() => handleGenerateSample(config.id)}
                    className="px-3 py-1 text-xs bg-green-600 text-white rounded hover:bg-green-700"
                  >
                    Generate Sample
                  </button>
                  <button
                    onClick={() => handleDelete(config.id)}
                    className="px-3 py-1 text-xs border border-red-300 text-red-600 rounded hover:bg-red-50"
                  >
                    Delete
                  </button>
                </div>
              </div>

              {/* Schema */}
              {config.schema_definition && Object.keys(config.schema_definition).length > 0 && (
                <div className="mb-3">
                  <p className="text-xs font-medium text-gray-500 mb-1">Schema</p>
                  <div className="bg-gray-50 rounded p-3 overflow-x-auto">
                    <pre className="text-xs text-gray-600">
                      {JSON.stringify(config.schema_definition, null, 2)}
                    </pre>
                  </div>
                </div>
              )}

              {/* Sample Data */}
              {config.sample_data && config.sample_data.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-gray-500 mb-1">
                    Sample Data ({config.sample_data.length} records)
                  </p>
                  <div className="overflow-x-auto">
                    <table className="min-w-full text-xs">
                      <thead>
                        <tr className="border-b border-gray-200">
                          {Object.keys(config.sample_data[0]).map((key) => (
                            <th key={key} className="text-left py-2 px-3 font-medium text-gray-600">
                              {key}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {config.sample_data.map((row, idx) => (
                          <tr key={idx} className="border-b border-gray-100">
                            {Object.values(row).map((val, cidx) => (
                              <td key={cidx} className="py-2 px-3 text-gray-700">
                                {String(val)}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Environment rules */}
              {config.environment_rules && Object.keys(config.environment_rules).length > 0 && (
                <div className="mt-3">
                  <p className="text-xs font-medium text-gray-500 mb-1">Environment Rules</p>
                  <pre className="text-xs text-gray-600 bg-gray-50 rounded p-3">
                    {JSON.stringify(config.environment_rules, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
