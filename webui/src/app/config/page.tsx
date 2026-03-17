'use client';

import { useEffect, useState } from 'react';
import { config, models, type ModelConfig } from '@/lib/api';

export default function ConfigPage() {
  const [configData, setConfigData] = useState<Record<string, any>>({});
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [modelList, setModelList] = useState<ModelConfig[]>([]);
  const [loadingModels, setLoadingModels] = useState(true);
  const [showAddModel, setShowAddModel] = useState(false);
  const [editingModel, setEditingModel] = useState<ModelConfig | null>(null);
  const [modelForm, setModelForm] = useState({
    label: '', provider: 'openai', model: '', api_key: '', base_url: '',
    // Bedrock/CDAO fields
    aws_account_number: '', aws_region: 'us-east-1', workspace_id: '', is_execution_role: false,
    // Azure fields
    endpoint: '', deployment_name: '',
  });
  const [savingModel, setSavingModel] = useState(false);
  const [testingModelId, setTestingModelId] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, { status: string; response?: string; error?: string; latency_ms: number }>>({});
  const [testingInline, setTestingInline] = useState(false);
  const [inlineTestResult, setInlineTestResult] = useState<{ status: string; response?: string; error?: string; latency_ms: number } | null>(null);

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

  async function loadModels() {
    try {
      const data = await models.list();
      setModelList(data.models || []);
    } catch (err) {
      console.error('Failed to load models:', err);
    } finally {
      setLoadingModels(false);
    }
  }

  useEffect(() => { loadModels(); }, []);

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

  async function handleSaveModel() {
    setSavingModel(true);
    try {
      // Pack provider-specific fields into extra_config
      const extra_config: Record<string, any> = {};
      const isBedrock = modelForm.provider === 'bedrock' || modelForm.provider === 'cdao';
      const isAzure = modelForm.provider === 'azure';
      if (isBedrock) {
        if (modelForm.aws_account_number) extra_config.aws_account_number = modelForm.aws_account_number;
        if (modelForm.aws_region) extra_config.aws_region = modelForm.aws_region;
        if (modelForm.workspace_id) extra_config.workspace_id = modelForm.workspace_id;
        extra_config.is_execution_role = modelForm.is_execution_role;
      }
      if (isAzure) {
        if (modelForm.endpoint) extra_config.endpoint = modelForm.endpoint;
        if (modelForm.deployment_name) extra_config.deployment_name = modelForm.deployment_name;
      }
      const payload = {
        label: modelForm.label,
        provider: modelForm.provider,
        model: modelForm.model,
        api_key: modelForm.api_key,
        base_url: modelForm.base_url,
        extra_config,
      };
      if (editingModel) {
        await models.update(editingModel.id, payload);
      } else {
        await models.create(payload);
      }
      setShowAddModel(false);
      setEditingModel(null);
      setModelForm({ label: '', provider: 'openai', model: '', api_key: '', base_url: '', aws_account_number: '', aws_region: 'us-east-1', workspace_id: '', is_execution_role: false, endpoint: '', deployment_name: '' });
      await loadModels();
    } catch (err: any) {
      setError(err.message || 'Failed to save model');
    } finally {
      setSavingModel(false);
    }
  }

  async function handleDeleteModel(id: string) {
    if (!confirm('Delete this model configuration?')) return;
    try {
      await models.delete(id);
      await loadModels();
    } catch (err: any) {
      setError(err.message || 'Failed to delete model');
    }
  }

  async function handleSetDefault(id: string) {
    try {
      await models.setDefault(id);
      await loadModels();
    } catch (err: any) {
      setError(err.message || 'Failed to set default');
    }
  }

  async function handleTestModel(id: string) {
    setTestingModelId(id);
    setTestResults(prev => { const next = { ...prev }; delete next[id]; return next; });
    try {
      const result = await models.test(id);
      setTestResults(prev => ({ ...prev, [id]: result }));
    } catch (err: any) {
      setTestResults(prev => ({ ...prev, [id]: { status: 'error', error: err.message || 'Request failed', latency_ms: 0 } }));
    } finally {
      setTestingModelId(null);
    }
  }

  async function handleTestInline() {
    setTestingInline(true);
    setInlineTestResult(null);
    const isBedrock = modelForm.provider === 'bedrock' || modelForm.provider === 'cdao';
    const isAzure = modelForm.provider === 'azure';
    const extra_config: Record<string, any> = {};
    if (isBedrock) {
      if (modelForm.aws_account_number) extra_config.aws_account_number = modelForm.aws_account_number;
      if (modelForm.aws_region) extra_config.aws_region = modelForm.aws_region;
      if (modelForm.workspace_id) extra_config.workspace_id = modelForm.workspace_id;
      extra_config.is_execution_role = modelForm.is_execution_role;
    }
    if (isAzure) {
      if (modelForm.endpoint) extra_config.endpoint = modelForm.endpoint;
      if (modelForm.deployment_name) extra_config.deployment_name = modelForm.deployment_name;
    }
    try {
      const result = await models.testInline({
        label: modelForm.label || 'test',
        provider: modelForm.provider,
        model: modelForm.model,
        api_key: modelForm.api_key || undefined,
        base_url: modelForm.base_url || undefined,
        extra_config,
      });
      setInlineTestResult(result);
    } catch (err: any) {
      setInlineTestResult({ status: 'error', error: err.message || 'Request failed', latency_ms: 0 });
    } finally {
      setTestingInline(false);
    }
  }

  function startEditModel(m: ModelConfig) {
    setEditingModel(m);
    setInlineTestResult(null);
    const ec = m.extra_config || {};
    setModelForm({
      label: m.label, provider: m.provider, model: m.model, api_key: '', base_url: m.base_url,
      aws_account_number: ec.aws_account_number || '', aws_region: ec.aws_region || 'us-east-1',
      workspace_id: ec.workspace_id || '', is_execution_role: ec.is_execution_role || false,
      endpoint: ec.endpoint || '', deployment_name: ec.deployment_name || '',
    });
    setShowAddModel(true);
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

      {/* Models Section */}
      <div className="bg-white rounded-lg border border-gray-200 overflow-hidden">
        <div className="flex items-center justify-between px-4 py-3 bg-gray-50 border-b border-gray-200">
          <h2 className="text-sm font-semibold text-gray-700">LLM Models</h2>
          <button
            onClick={() => { setShowAddModel(true); setEditingModel(null); setModelForm({ label: '', provider: 'openai', model: '', api_key: '', base_url: '', aws_account_number: '', aws_region: 'us-east-1', workspace_id: '', is_execution_role: false, endpoint: '', deployment_name: '' }); }}
            className="px-3 py-1 bg-indigo-600 text-white text-xs rounded-md hover:bg-indigo-700"
          >
            Add Model
          </button>
        </div>

        {loadingModels ? (
          <div className="p-4 text-sm text-gray-400">Loading models...</div>
        ) : modelList.length === 0 ? (
          <div className="p-4 text-sm text-gray-400">No models configured. Models will be auto-seeded from config.ini on first API call.</div>
        ) : (
          <div className="divide-y divide-gray-100">
            {modelList.map(m => (
              <div key={m.id}>
              <div className={`flex items-center justify-between px-4 py-3 ${m.is_system ? 'bg-gray-50/70' : 'hover:bg-gray-50'}`}>
                <div className="flex items-center gap-3">
                  <span className={`w-2.5 h-2.5 rounded-full ${
                    m.provider === 'openai' ? 'bg-green-500' :
                    m.provider === 'anthropic' ? 'bg-orange-500' :
                    m.provider === 'gemini' || m.provider === 'google' ? 'bg-blue-500' :
                    m.provider === 'azure' ? 'bg-cyan-500' :
                    m.provider === 'bedrock' || m.provider === 'cdao' ? 'bg-purple-500' : 'bg-gray-500'
                  }`} />
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-gray-800">{m.label}</span>
                      {m.is_default && <span className="px-1.5 py-0.5 text-[10px] bg-yellow-100 text-yellow-700 rounded">default</span>}
                      {m.is_system && <span className="px-1.5 py-0.5 text-[10px] bg-gray-200 text-gray-600 rounded">system</span>}
                    </div>
                    <div className="flex items-center gap-2 mt-0.5 flex-wrap">
                      <span className="text-xs text-gray-500">{m.provider}</span>
                      <span className="text-xs text-gray-400 truncate max-w-[200px]">{m.model}</span>
                      {m.api_key_set && <span className="text-[10px] text-green-600">key set</span>}
                      {(m.provider === 'bedrock' || m.provider === 'cdao') && m.extra_config?.aws_region && (
                        <span className="text-[10px] text-purple-500">{m.extra_config.aws_region}</span>
                      )}
                      {m.provider === 'azure' && m.extra_config?.endpoint && (
                        <span className="text-[10px] text-cyan-500 truncate max-w-[150px]">{m.extra_config.endpoint}</span>
                      )}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => handleTestModel(m.id)}
                    disabled={testingModelId === m.id}
                    className="px-2 py-1 text-xs text-teal-600 hover:text-teal-800 disabled:opacity-50"
                    title="Test connection"
                  >
                    {testingModelId === m.id ? 'Testing...' : 'Test'}
                  </button>
                  {!m.is_system && !m.is_default && (
                    <button onClick={() => handleSetDefault(m.id)} className="px-2 py-1 text-xs text-gray-500 hover:text-indigo-600" title="Set as default">
                      Set Default
                    </button>
                  )}
                  {!m.is_system && (
                    <button onClick={() => startEditModel(m)} className="px-2 py-1 text-xs text-gray-500 hover:text-indigo-600">
                      Edit
                    </button>
                  )}
                  {!m.is_system && (
                    <button onClick={() => handleDeleteModel(m.id)} className="px-2 py-1 text-xs text-red-400 hover:text-red-600">
                      Delete
                    </button>
                  )}
                </div>
              </div>
              {/* Model config details (read-only for system, info for all) */}
              {m.is_system && (
                <div className="px-4 pb-3 ml-[calc(0.625rem+0.75rem)]">
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-1">
                    <div className="flex items-baseline gap-1.5">
                      <span className="text-[10px] text-gray-400">provider:</span>
                      <span className="text-[10px] text-gray-600 font-mono">{m.provider}</span>
                    </div>
                    <div className="flex items-baseline gap-1.5">
                      <span className="text-[10px] text-gray-400">model:</span>
                      <span className="text-[10px] text-gray-600 font-mono truncate">{m.model}</span>
                    </div>
                    <div className="flex items-baseline gap-1.5">
                      <span className="text-[10px] text-gray-400">api_key:</span>
                      <span className={`text-[10px] font-mono ${m.api_key_set ? 'text-green-600' : 'text-gray-400'}`}>
                        {m.api_key_set ? 'configured' : 'not set'}
                      </span>
                    </div>
                    {m.base_url && (
                      <div className="flex items-baseline gap-1.5 col-span-2">
                        <span className="text-[10px] text-gray-400">base_url:</span>
                        <span className="text-[10px] text-gray-600 font-mono truncate">{m.base_url}</span>
                      </div>
                    )}
                    {m.extra_config && Object.entries(m.extra_config).map(([key, val]) => (
                      <div key={key} className="flex items-baseline gap-1.5">
                        <span className="text-[10px] text-gray-400">{key}:</span>
                        <span className="text-[10px] text-gray-600 font-mono truncate">
                          {typeof val === 'boolean' ? (val ? 'true' : 'false') : String(val)}
                        </span>
                      </div>
                    ))}
                  </div>
                  <p className="text-[10px] text-gray-400 mt-1.5 italic">Configured in config.ini {'\u2014'} read-only</p>
                </div>
              )}
              {/* Test result inline */}
              {testResults[m.id] && (
                <div className="px-4 pb-3 -mt-1">
                  <div className={`text-xs px-3 py-2 rounded-md ${
                    testResults[m.id].status === 'ok'
                      ? 'bg-green-50 text-green-700 border border-green-200'
                      : 'bg-red-50 text-red-700 border border-red-200'
                  }`}>
                    {testResults[m.id].status === 'ok' ? (
                      <span>Connected successfully ({testResults[m.id].latency_ms}ms) {'\u2014'} <span className="font-mono text-[11px]">{testResults[m.id].response}</span></span>
                    ) : (
                      <span>Failed: {testResults[m.id].error}</span>
                    )}
                  </div>
                </div>
              )}
              </div>
            ))}
          </div>
        )}

        {/* Add/Edit Model Form */}
        {showAddModel && (
          <div className="border-t border-gray-200 p-4 bg-indigo-50/30">
            <h3 className="text-sm font-semibold text-gray-700 mb-3">{editingModel ? 'Edit Model' : 'Add Model'}</h3>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-gray-600 mb-1">Label</label>
                <input value={modelForm.label} onChange={e => setModelForm(f => ({ ...f, label: e.target.value }))} className="w-full px-3 py-2 border rounded-md text-sm" placeholder="GPT-4o" />
              </div>
              <div>
                <label className="block text-xs text-gray-600 mb-1">Provider</label>
                <select value={modelForm.provider} onChange={e => setModelForm(f => ({ ...f, provider: e.target.value }))} className="w-full px-3 py-2 border rounded-md text-sm">
                  <option value="openai">OpenAI</option>
                  <option value="anthropic">Anthropic</option>
                  <option value="gemini">Google Gemini</option>
                  <option value="azure">Azure OpenAI</option>
                  <option value="bedrock">AWS Bedrock</option>
                  <option value="cdao">AWS Bedrock (CDAO)</option>
                </select>
              </div>
              <div>
                <label className="block text-xs text-gray-600 mb-1">
                  {modelForm.provider === 'bedrock' || modelForm.provider === 'cdao' ? 'Model ARN' : 'Model ID'}
                </label>
                <input
                  value={modelForm.model}
                  onChange={e => setModelForm(f => ({ ...f, model: e.target.value }))}
                  className="w-full px-3 py-2 border rounded-md text-sm"
                  placeholder={
                    modelForm.provider === 'bedrock' || modelForm.provider === 'cdao'
                      ? 'arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-...'
                      : modelForm.provider === 'azure' ? 'gpt-4o' : 'gpt-4o'
                  }
                />
              </div>
              {/* API Key — not needed for Bedrock/CDAO */}
              {modelForm.provider !== 'bedrock' && modelForm.provider !== 'cdao' && (
                <div>
                  <label className="block text-xs text-gray-600 mb-1">API Key</label>
                  <input type="password" value={modelForm.api_key} onChange={e => setModelForm(f => ({ ...f, api_key: e.target.value }))} className="w-full px-3 py-2 border rounded-md text-sm" placeholder={editingModel ? '(unchanged if empty)' : 'sk-...'} />
                </div>
              )}
              {/* Base URL — for OpenAI/Anthropic/Gemini */}
              {modelForm.provider !== 'bedrock' && modelForm.provider !== 'cdao' && modelForm.provider !== 'azure' && (
                <div className="col-span-2">
                  <label className="block text-xs text-gray-600 mb-1">Base URL (optional)</label>
                  <input value={modelForm.base_url} onChange={e => setModelForm(f => ({ ...f, base_url: e.target.value }))} className="w-full px-3 py-2 border rounded-md text-sm" placeholder="https://api.openai.com/v1" />
                </div>
              )}

              {/* --- Bedrock / CDAO fields --- */}
              {(modelForm.provider === 'bedrock' || modelForm.provider === 'cdao') && (
                <>
                  <div>
                    <label className="block text-xs text-gray-600 mb-1">AWS Account Number</label>
                    <input value={modelForm.aws_account_number} onChange={e => setModelForm(f => ({ ...f, aws_account_number: e.target.value }))} className="w-full px-3 py-2 border rounded-md text-sm" placeholder="123456789012" />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-600 mb-1">AWS Region</label>
                    <input value={modelForm.aws_region} onChange={e => setModelForm(f => ({ ...f, aws_region: e.target.value }))} className="w-full px-3 py-2 border rounded-md text-sm" placeholder="us-east-1" />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-600 mb-1">Workspace ID</label>
                    <input value={modelForm.workspace_id} onChange={e => setModelForm(f => ({ ...f, workspace_id: e.target.value }))} className="w-full px-3 py-2 border rounded-md text-sm" placeholder="ws-..." />
                  </div>
                  <div className="flex items-center gap-2 pt-5">
                    <input
                      type="checkbox"
                      id="is_execution_role"
                      checked={modelForm.is_execution_role}
                      onChange={e => setModelForm(f => ({ ...f, is_execution_role: e.target.checked }))}
                      className="h-4 w-4 text-indigo-600 border-gray-300 rounded"
                    />
                    <label htmlFor="is_execution_role" className="text-xs text-gray-600">Use Execution Role</label>
                  </div>
                </>
              )}

              {/* --- Azure fields --- */}
              {modelForm.provider === 'azure' && (
                <>
                  <div>
                    <label className="block text-xs text-gray-600 mb-1">Azure Endpoint</label>
                    <input value={modelForm.endpoint} onChange={e => setModelForm(f => ({ ...f, endpoint: e.target.value }))} className="w-full px-3 py-2 border rounded-md text-sm" placeholder="https://my-resource.openai.azure.com" />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-600 mb-1">Deployment Name</label>
                    <input value={modelForm.deployment_name} onChange={e => setModelForm(f => ({ ...f, deployment_name: e.target.value }))} className="w-full px-3 py-2 border rounded-md text-sm" placeholder="gpt-4o-deployment" />
                  </div>
                  <div>
                    <label className="block text-xs text-gray-600 mb-1">API Key</label>
                    <input type="password" value={modelForm.api_key} onChange={e => setModelForm(f => ({ ...f, api_key: e.target.value }))} className="w-full px-3 py-2 border rounded-md text-sm" placeholder={editingModel ? '(unchanged if empty)' : 'Azure API key'} />
                  </div>
                </>
              )}
            </div>
            {/* Inline test result */}
            {inlineTestResult && (
              <div className={`mt-3 text-xs px-3 py-2 rounded-md ${
                inlineTestResult.status === 'ok'
                  ? 'bg-green-50 text-green-700 border border-green-200'
                  : 'bg-red-50 text-red-700 border border-red-200'
              }`}>
                {inlineTestResult.status === 'ok' ? (
                  <span>Connected successfully ({inlineTestResult.latency_ms}ms) {'\u2014'} <span className="font-mono text-[11px]">{inlineTestResult.response}</span></span>
                ) : (
                  <span>Failed: {inlineTestResult.error}</span>
                )}
              </div>
            )}
            <div className="flex justify-end gap-2 mt-3">
              <button onClick={() => { setShowAddModel(false); setEditingModel(null); setInlineTestResult(null); }} className="px-3 py-1.5 text-xs border border-gray-300 rounded-md text-gray-600 hover:bg-gray-50">Cancel</button>
              <button
                onClick={handleTestInline}
                disabled={testingInline || !modelForm.model}
                className="px-3 py-1.5 text-xs border border-teal-300 text-teal-700 rounded-md hover:bg-teal-50 disabled:opacity-50"
              >
                {testingInline ? 'Testing...' : 'Test Connection'}
              </button>
              <button onClick={handleSaveModel} disabled={savingModel || !modelForm.label || !modelForm.model} className="px-3 py-1.5 text-xs bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:opacity-50">
                {savingModel ? 'Saving...' : editingModel ? 'Update' : 'Add'}
              </button>
            </div>
          </div>
        )}
      </div>

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
