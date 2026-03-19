'use client';

import { useEffect, useState, useCallback } from 'react';
import { tools, models, type CustomTool, type BuiltinTool, type ModelConfig } from '@/lib/api';

const TOOL_TYPES = [
  { value: 'agent', label: 'Agent', color: 'bg-green-100 text-green-700' },
  { value: 'validator', label: 'Validator', color: 'bg-blue-100 text-blue-700' },
  { value: 'transformer', label: 'Transformer', color: 'bg-purple-100 text-purple-700' },
  { value: 'analyzer', label: 'Analyzer', color: 'bg-amber-100 text-amber-700' },
];

const AVAILABLE_TOOLS = [
  'Read', 'Write', 'Edit', 'Bash', 'Grep', 'Glob',
  'WebSearch', 'WebFetch', 'ListDir', 'FindFiles', 'DeleteFile',
];

const PROVIDER_COLORS: Record<string, string> = {
  openai: 'bg-green-500',
  anthropic: 'bg-orange-500',
  gemini: 'bg-blue-500',
  google: 'bg-blue-500',
  azure: 'bg-cyan-500',
  bedrock: 'bg-purple-500',
};

type FilterTab = 'all' | 'migration' | 'chat' | 'testing';

const AUTH_TYPES = ['none', 'basic', 'bearer', 'kerberos'] as const;
type AuthType = typeof AUTH_TYPES[number];
type CredSource = 'direct' | 'profile';

const CONNECTION_TYPES = [
  { value: '', label: 'None' },
  { value: 'database', label: 'Database' },
  { value: 'rest_api', label: 'REST API' },
  { value: 'mcp_server', label: 'MCP Server' },
] as const;

const DB_ENGINES = ['postgresql', 'mysql', 'oracle', 'sqlserver', 'db2', 'other'] as const;

const EMPTY_FORM = {
  name: '',
  description: '',
  tool_type: 'agent',
  enabled_for_migration: false,
  enabled_for_chat: false,
  enabled_for_testing: false,
  agent_instructions: '',
  goal: '',
  allowed_tools: ['Read', 'Edit', 'Bash', 'Grep'] as string[],
  parameters: {} as Record<string, any>,
  credential_config: { auth_type: 'none' } as Record<string, any>,
  tags: [] as string[],
  prerequisites: [] as string[],
  max_turns: 20,
  model: '',
  model_config_id: '' as string,
  timeout_seconds: 300,
};

export default function ToolsPage() {
  const [toolList, setToolList] = useState<CustomTool[]>([]);
  const [builtinTools, setBuiltinTools] = useState<BuiltinTool[]>([]);
  const [loading, setLoading] = useState(true);
  const [filterTab, setFilterTab] = useState<FilterTab>('all');
  const [showForm, setShowForm] = useState(false);
  const [editingTool, setEditingTool] = useState<CustomTool | null>(null);
  const [form, setForm] = useState({ ...EMPTY_FORM });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [expandedBuiltinId, setExpandedBuiltinId] = useState<string | null>(null);
  const [modelList, setModelList] = useState<ModelConfig[]>([]);
  const [collapsedBuiltinCats, setCollapsedBuiltinCats] = useState<Set<string>>(new Set());
  const [tagInput, setTagInput] = useState('');
  const [credSource, setCredSource] = useState<CredSource>('direct');
  const [credTestResult, setCredTestResult] = useState<{ status: string; detail?: string } | null>(null);
  const [credTesting, setCredTesting] = useState(false);

  const loadTools = useCallback(async () => {
    try {
      const params: { enabled_for?: string } = {};
      if (filterTab !== 'all') params.enabled_for = filterTab;
      const [customRes, builtinRes, modelsRes] = await Promise.all([
        tools.list(params),
        tools.listBuiltin().catch(() => ({ tools: [] })),
        models.list().catch(() => ({ models: [] })),
      ]);
      setToolList(customRes.tools);
      setBuiltinTools(builtinRes.tools);
      setModelList(modelsRes.models || []);
    } catch (err) {
      console.error('Failed to load tools:', err);
    } finally {
      setLoading(false);
    }
  }, [filterTab]);

  useEffect(() => {
    setLoading(true);
    loadTools();
  }, [loadTools]);

  const openCreate = () => {
    setEditingTool(null);
    setForm({ ...EMPTY_FORM });
    setTagInput('');
    setError('');
    setCredSource('direct');
    setCredTestResult(null);
    setShowForm(true);
  };

  const openEdit = (tool: CustomTool) => {
    setEditingTool(tool);
    const cc = tool.credential_config || { auth_type: 'none' };
    setForm({
      name: tool.name,
      description: tool.description,
      tool_type: tool.tool_type,
      enabled_for_migration: tool.enabled_for_migration,
      enabled_for_chat: tool.enabled_for_chat,
      enabled_for_testing: tool.enabled_for_testing,
      agent_instructions: tool.agent_instructions,
      goal: tool.goal,
      allowed_tools: tool.allowed_tools || [],
      parameters: tool.parameters || {},
      credential_config: cc,
      tags: tool.tags || [],
      prerequisites: tool.prerequisites || [],
      max_turns: tool.max_turns,
      model: tool.model,
      model_config_id: tool.model_config_id || '',
      timeout_seconds: tool.timeout_seconds,
    });
    setTagInput('');
    setError('');
    setCredSource(cc.config_section ? 'profile' : 'direct');
    setCredTestResult(null);
    setShowForm(true);
  };

  const handleSave = async () => {
    if (!form.name.trim()) {
      setError('Name is required');
      return;
    }
    if (!form.agent_instructions.trim()) {
      setError('Agent instructions are required');
      return;
    }
    setSaving(true);
    setError('');
    try {
      // Build credential_config for submission — strip empty secret fields
      // to avoid overwriting stored secrets with empty strings
      const credConfig = { ...form.credential_config };
      for (const secretField of ['password', 'token', 'keytab_path']) {
        if (credConfig[secretField] === '') {
          delete credConfig[secretField];
        }
      }
      const payload = { ...form, credential_config: credConfig };

      if (editingTool) {
        await tools.update(editingTool.id, payload);
      } else {
        await tools.create(payload);
      }
      setShowForm(false);
      setEditingTool(null);
      loadTools();
    } catch (err: any) {
      setError(err.message || 'Failed to save tool');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    try {
      await tools.delete(id);
      loadTools();
    } catch (err) {
      console.error('Delete failed:', err);
    }
  };

  const handleDuplicate = async (id: string) => {
    try {
      await tools.duplicate(id);
      loadTools();
    } catch (err) {
      console.error('Duplicate failed:', err);
    }
  };

  const handleToggleActive = async (tool: CustomTool) => {
    try {
      await tools.update(tool.id, { is_active: !tool.is_active } as any);
      loadTools();
    } catch (err) {
      console.error('Toggle failed:', err);
    }
  };

  const addTag = () => {
    const tag = tagInput.trim();
    if (tag && !form.tags.includes(tag)) {
      setForm({ ...form, tags: [...form.tags, tag] });
      setTagInput('');
    }
  };

  const removeTag = (tag: string) => {
    setForm({ ...form, tags: form.tags.filter(t => t !== tag) });
  };

  const toggleAllowedTool = (tool: string) => {
    setForm({
      ...form,
      allowed_tools: form.allowed_tools.includes(tool)
        ? form.allowed_tools.filter(t => t !== tool)
        : [...form.allowed_tools, tool],
    });
  };

  const updateCredConfig = (updates: Record<string, any>) => {
    setForm({ ...form, credential_config: { ...form.credential_config, ...updates } });
  };

  const handleTestCredentials = async () => {
    if (!editingTool) return;
    setCredTesting(true);
    setCredTestResult(null);
    try {
      const result = await tools.testCredentials(editingTool.id);
      setCredTestResult(result);
    } catch (err: any) {
      setCredTestResult({ status: 'error', detail: err.message || 'Test failed' });
    } finally {
      setCredTesting(false);
    }
  };

  const typeColor = (type: string) =>
    TOOL_TYPES.find(t => t.value === type)?.color || 'bg-gray-100 text-gray-600';

  const enabledBadges = (tool: CustomTool) => {
    const badges: { label: string; color: string }[] = [];
    if (tool.enabled_for_migration) badges.push({ label: 'Migration', color: 'bg-indigo-100 text-indigo-700' });
    if (tool.enabled_for_chat) badges.push({ label: 'Chat', color: 'bg-cyan-100 text-cyan-700' });
    if (tool.enabled_for_testing) badges.push({ label: 'Testing', color: 'bg-emerald-100 text-emerald-700' });
    return badges;
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <svg className="w-5 h-5 animate-spin text-indigo-600" fill="none" viewBox="0 0 24 24">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Custom Tools</h1>
          <p className="text-sm text-gray-500 mt-1">
            Build custom agent tools for migration, chat, and testing workflows
          </p>
        </div>
        <button
          onClick={openCreate}
          className="px-4 py-2 bg-indigo-600 text-white rounded-md text-sm font-medium hover:bg-indigo-700 transition-colors"
        >
          + New Tool
        </button>
      </div>

      {/* Filter tabs */}
      <div className="flex gap-1 bg-gray-100 rounded-lg p-1 w-fit">
        {(['all', 'migration', 'chat', 'testing'] as FilterTab[]).map(tab => (
          <button
            key={tab}
            onClick={() => setFilterTab(tab)}
            className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors capitalize ${
              filterTab === tab
                ? 'bg-white text-gray-900 shadow-sm'
                : 'text-gray-500 hover:text-gray-700'
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Built-in Tools (read-only) */}
      {builtinTools.length > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-2">
            <h2 className="text-sm font-semibold text-gray-700">Built-in Tools</h2>
            <span className="px-1.5 py-0.5 bg-gray-100 text-gray-500 rounded text-[10px] font-medium">
              {builtinTools.length} system tools
            </span>
            <span className="text-[10px] text-gray-400">Read-only — these are the core agent capabilities</span>
          </div>
          <div className="bg-white rounded-lg border border-gray-200 divide-y divide-gray-100">
            {(() => {
              const CATEGORY_META: Record<string, { label: string; color: string; icon: string }> = {
                read: { label: 'Read', color: 'bg-blue-100 text-blue-700', icon: 'eye' },
                write: { label: 'Write', color: 'bg-orange-100 text-orange-700', icon: 'pencil' },
                execution: { label: 'Execution', color: 'bg-red-100 text-red-700', icon: 'terminal' },
                memory: { label: 'Memory', color: 'bg-violet-100 text-violet-700', icon: 'brain' },
                completion: { label: 'Completion', color: 'bg-green-100 text-green-700', icon: 'check' },
                plan: { label: 'Plan', color: 'bg-amber-100 text-amber-700', icon: 'map' },
                gcc: { label: 'GCC', color: 'bg-cyan-100 text-cyan-700', icon: 'git' },
                code_index: { label: 'Code Index', color: 'bg-indigo-100 text-indigo-700', icon: 'search' },
                mcp: { label: 'MCP', color: 'bg-rose-100 text-rose-700', icon: 'plug' },
              };

              // Group by category
              const groups: Record<string, BuiltinTool[]> = {};
              builtinTools.forEach(t => {
                if (!groups[t.category]) groups[t.category] = [];
                groups[t.category].push(t);
              });

              const categoryOrder = ['read', 'write', 'execution', 'memory', 'completion', 'plan', 'gcc', 'code_index', 'mcp'];
              const sortedCategories = Object.keys(groups).sort(
                (a, b) => (categoryOrder.indexOf(a) === -1 ? 99 : categoryOrder.indexOf(a)) -
                           (categoryOrder.indexOf(b) === -1 ? 99 : categoryOrder.indexOf(b))
              );

              return sortedCategories.map(cat => {
                const meta = CATEGORY_META[cat] || { label: cat, color: 'bg-gray-100 text-gray-600' };
                const catTools = groups[cat];
                return (
                  <div key={cat}>
                    {/* Category header — click to collapse/expand */}
                    <div
                      className="px-4 py-2 bg-gray-50/50 flex items-center gap-2 cursor-pointer hover:bg-gray-100/50 transition-colors select-none"
                      onClick={() => setCollapsedBuiltinCats(prev => {
                        const next = new Set(prev);
                        if (next.has(cat)) next.delete(cat); else next.add(cat);
                        return next;
                      })}
                    >
                      <svg
                        className={`w-3 h-3 text-gray-400 transition-transform flex-shrink-0 ${collapsedBuiltinCats.has(cat) ? '-rotate-90' : ''}`}
                        fill="none" stroke="currentColor" viewBox="0 0 24 24"
                      >
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                      </svg>
                      <span className={`px-2 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wider ${meta.color}`}>
                        {meta.label}
                      </span>
                      <span className="text-[10px] text-gray-400">{catTools.length} tool{catTools.length > 1 ? 's' : ''}</span>
                      {collapsedBuiltinCats.has(cat) && (
                        <span className="text-[10px] text-gray-400 ml-auto">
                          {catTools.map(t => t.name).join(', ')}
                        </span>
                      )}
                    </div>
                    {/* Tools in category — collapsible */}
                    {!collapsedBuiltinCats.has(cat) && catTools.map(bt => {
                      const isExpanded = expandedBuiltinId === `${cat}:${bt.name}`;
                      return (
                        <div key={bt.name}>
                          <div
                            className="flex items-center gap-3 px-4 py-2.5 hover:bg-gray-50 transition-colors cursor-pointer"
                            onClick={() => setExpandedBuiltinId(isExpanded ? null : `${cat}:${bt.name}`)}
                          >
                            <svg className="w-3 h-3 text-gray-300 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                            </svg>
                            <code className="text-sm font-mono font-medium text-gray-800">{bt.name}</code>
                            <span className="text-xs text-gray-400 truncate flex-1">{bt.description.split('.')[0]}</span>
                            {Object.keys(bt.parameters).length > 0 && (
                              <span className="text-[9px] text-gray-400 flex-shrink-0">
                                {Object.keys(bt.parameters).length} param{Object.keys(bt.parameters).length > 1 ? 's' : ''}
                              </span>
                            )}
                            <svg
                              className={`w-3.5 h-3.5 text-gray-400 transition-transform flex-shrink-0 ${isExpanded ? 'rotate-180' : ''}`}
                              fill="none" stroke="currentColor" viewBox="0 0 24 24"
                            >
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                            </svg>
                          </div>
                          {isExpanded && (
                            <div className="px-4 pb-3 bg-gray-50/50 border-t border-gray-100">
                              <p className="text-xs text-gray-600 mt-2 mb-3 leading-relaxed">{bt.description}</p>
                              {Object.keys(bt.parameters).length > 0 && (
                                <div>
                                  <label className="block text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-1.5">Parameters</label>
                                  <div className="space-y-1">
                                    {Object.entries(bt.parameters).map(([param, desc]) => (
                                      <div key={param} className="flex items-start gap-2 text-xs">
                                        <code className={`font-mono px-1.5 py-0.5 rounded flex-shrink-0 ${
                                          bt.required.includes(param)
                                            ? 'bg-indigo-50 text-indigo-700'
                                            : 'bg-gray-100 text-gray-600'
                                        }`}>
                                          {param}
                                          {bt.required.includes(param) && <span className="text-indigo-400 ml-0.5">*</span>}
                                        </code>
                                        <span className="text-gray-500">{desc}</span>
                                      </div>
                                    ))}
                                  </div>
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                );
              });
            })()}
          </div>
        </div>
      )}

      {/* Custom Tool list */}
      <div className="flex items-center gap-2">
        <h2 className="text-sm font-semibold text-gray-700">Custom Tools</h2>
        <span className="px-1.5 py-0.5 bg-gray-100 text-gray-500 rounded text-[10px] font-medium">
          {toolList.length} tool{toolList.length !== 1 ? 's' : ''}
        </span>
        <span className="text-[10px] text-gray-400">User-defined — editable, can be enabled per workflow</span>
      </div>

      {toolList.length === 0 ? (
        <div className="bg-white rounded-lg border border-gray-200 p-12 text-center">
          <svg className="w-10 h-10 mx-auto text-gray-300 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M11.42 15.17l-5.384-3.19A2.625 2.625 0 013 9.792V9.72a2.625 2.625 0 011.036-2.188l5.384-3.19a2.625 2.625 0 012.76 0l5.384 3.19A2.625 2.625 0 0121 9.72v.072a2.625 2.625 0 01-1.036 2.188l-5.384 3.19a2.625 2.625 0 01-2.76 0z" />
          </svg>
          <p className="text-sm text-gray-500">No custom tools yet</p>
          <button
            onClick={openCreate}
            className="mt-3 text-sm text-indigo-600 hover:text-indigo-700 font-medium"
          >
            Create your first tool
          </button>
        </div>
      ) : (
        <div className="bg-white rounded-lg border border-gray-200 divide-y divide-gray-100">
          {toolList.map(tool => (
            <div key={tool.id}>
              {/* Row */}
              <div
                className="flex items-center gap-3 px-4 py-3 hover:bg-gray-50 transition-colors cursor-pointer"
                onClick={() => setExpandedId(expandedId === tool.id ? null : tool.id)}
              >
                {/* Active indicator */}
                <div className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                  tool.is_active ? 'bg-green-500' : 'bg-gray-300'
                }`} />

                {/* Type badge */}
                <span className={`px-2 py-0.5 rounded text-[10px] font-medium flex-shrink-0 ${typeColor(tool.tool_type)}`}>
                  {tool.tool_type}
                </span>

                {/* Name + description */}
                <div className="flex-1 min-w-0">
                  <span className="text-sm font-medium text-gray-900">{tool.name}</span>
                  {tool.description && (
                    <span className="text-xs text-gray-400 ml-2 truncate">{tool.description}</span>
                  )}
                </div>

                {/* Enabled-for badges */}
                <div className="flex gap-1 flex-shrink-0">
                  {enabledBadges(tool).map(b => (
                    <span key={b.label} className={`px-1.5 py-0.5 rounded text-[9px] font-medium ${b.color}`}>
                      {b.label}
                    </span>
                  ))}
                </div>

                {/* Goal preview */}
                {tool.goal && (
                  <span className="text-[10px] text-gray-400 max-w-[140px] truncate flex-shrink-0" title={tool.goal}>
                    Goal: {tool.goal}
                  </span>
                )}

                {/* Chevron */}
                <svg
                  className={`w-4 h-4 text-gray-400 transition-transform flex-shrink-0 ${
                    expandedId === tool.id ? 'rotate-180' : ''
                  }`}
                  fill="none" stroke="currentColor" viewBox="0 0 24 24"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </div>

              {/* Expanded detail */}
              {expandedId === tool.id && (
                <div className="px-4 pb-4 bg-gray-50 border-t border-gray-100">
                  <div className="grid grid-cols-2 gap-4 mt-3">
                    {/* Left: Instructions + Goal */}
                    <div className="space-y-3">
                      {tool.goal && (
                        <div>
                          <label className="block text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-1">Goal</label>
                          <div className="bg-white rounded border border-gray-200 px-3 py-2 text-sm text-gray-700">
                            {tool.goal}
                          </div>
                        </div>
                      )}
                      <div>
                        <label className="block text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-1">Agent Instructions</label>
                        <pre className="bg-white rounded border border-gray-200 px-3 py-2 text-xs text-gray-700 whitespace-pre-wrap max-h-40 overflow-y-auto font-mono">
                          {tool.agent_instructions || '(none)'}
                        </pre>
                      </div>
                    </div>

                    {/* Right: Config */}
                    <div className="space-y-3">
                      <div>
                        <label className="block text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-1">Allowed Tools</label>
                        <div className="flex flex-wrap gap-1">
                          {(tool.allowed_tools || []).map(t => (
                            <span key={t} className="px-1.5 py-0.5 bg-gray-200 text-gray-700 rounded text-[10px] font-mono">
                              {t}
                            </span>
                          ))}
                          {(!tool.allowed_tools || tool.allowed_tools.length === 0) && (
                            <span className="text-xs text-gray-400">All tools</span>
                          )}
                        </div>
                      </div>
                      <div className="grid grid-cols-3 gap-2 text-xs">
                        <div>
                          <span className="text-gray-400">Model</span>
                          <div className="text-gray-700 font-medium">
                            {tool.resolved_model
                              ? `${tool.resolved_model.label} (${tool.resolved_model.provider})`
                              : 'default'}
                          </div>
                          {tool.resolved_model && (
                            <div className="text-[10px] text-gray-400 font-mono">{tool.resolved_model.model}</div>
                          )}
                        </div>
                        <div>
                          <span className="text-gray-400">Max Turns</span>
                          <div className="text-gray-700 font-medium">{tool.max_turns}</div>
                        </div>
                        <div>
                          <span className="text-gray-400">Timeout</span>
                          <div className="text-gray-700 font-medium">{tool.timeout_seconds}s</div>
                        </div>
                      </div>
                      {tool.credentials_set && (
                        <div>
                          <label className="block text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-1">Connection & Auth</label>
                          <div className="flex flex-wrap gap-1">
                            {tool.credential_config?.connection_type && (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-blue-50 text-blue-700 rounded text-[10px] font-medium">
                                {tool.credential_config.connection_type === 'database' && `DB: ${tool.credential_config.host || '?'}:${tool.credential_config.port || '?'}/${tool.credential_config.database || '?'}`}
                                {tool.credential_config.connection_type === 'rest_api' && `API: ${tool.credential_config.base_url || '?'}`}
                                {tool.credential_config.connection_type === 'mcp_server' && `MCP: ${tool.credential_config.mcp_server_name || '?'} (${tool.credential_config.mcp_transport || 'stdio'})`}
                              </span>
                            )}
                            {tool.credential_config?.auth_type && tool.credential_config.auth_type !== 'none' && (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 bg-amber-50 text-amber-700 rounded text-[10px] font-medium">
                                {tool.credential_config.auth_type}
                                {tool.credential_config?.config_section && ` (profile: ${tool.credential_config.config_section})`}
                              </span>
                            )}
                          </div>
                        </div>
                      )}
                      {(tool.tags || []).length > 0 && (
                        <div>
                          <label className="block text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-1">Tags</label>
                          <div className="flex flex-wrap gap-1">
                            {tool.tags.map(t => (
                              <span key={t} className="px-1.5 py-0.5 bg-indigo-50 text-indigo-600 rounded text-[10px]">
                                {t}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-2 mt-4 pt-3 border-t border-gray-200">
                    <button
                      onClick={(e) => { e.stopPropagation(); openEdit(tool); }}
                      className="px-2.5 py-1 text-[11px] font-medium text-indigo-600 bg-indigo-50 rounded hover:bg-indigo-100 transition-colors"
                    >
                      Edit
                    </button>
                    <button
                      onClick={(e) => { e.stopPropagation(); handleDuplicate(tool.id); }}
                      className="px-2.5 py-1 text-[11px] font-medium text-gray-600 bg-gray-100 rounded hover:bg-gray-200 transition-colors"
                    >
                      Duplicate
                    </button>
                    <button
                      onClick={(e) => { e.stopPropagation(); handleToggleActive(tool); }}
                      className={`px-2.5 py-1 text-[11px] font-medium rounded transition-colors ${
                        tool.is_active
                          ? 'text-yellow-700 bg-yellow-50 hover:bg-yellow-100'
                          : 'text-green-700 bg-green-50 hover:bg-green-100'
                      }`}
                    >
                      {tool.is_active ? 'Disable' : 'Enable'}
                    </button>
                    <div className="flex-1" />
                    <button
                      onClick={(e) => { e.stopPropagation(); handleDelete(tool.id); }}
                      className="px-2.5 py-1 text-[11px] font-medium text-red-600 bg-red-50 rounded hover:bg-red-100 transition-colors"
                    >
                      Delete
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Create/Edit Modal */}
      {showForm && (
        <div className="fixed inset-0 bg-black/40 flex items-start justify-center z-50 pt-16 px-4 overflow-y-auto">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-2xl mb-16">
            {/* Modal header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-200">
              <h2 className="text-lg font-semibold text-gray-900">
                {editingTool ? 'Edit Tool' : 'Create Custom Tool'}
              </h2>
              <button
                onClick={() => setShowForm(false)}
                className="text-gray-400 hover:text-gray-600"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>

            {/* Modal body */}
            <div className="px-6 py-4 space-y-4 max-h-[70vh] overflow-y-auto">
              {error && (
                <div className="bg-red-50 border border-red-200 text-red-700 px-3 py-2 rounded text-sm">
                  {error}
                </div>
              )}

              {/* Name + Type */}
              <div className="grid grid-cols-3 gap-3">
                <div className="col-span-2">
                  <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
                  <input
                    type="text"
                    value={form.name}
                    onChange={e => setForm({ ...form, name: e.target.value })}
                    placeholder="e.g. Spring Boot Migrator"
                    className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Type</label>
                  <select
                    value={form.tool_type}
                    onChange={e => setForm({ ...form, tool_type: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  >
                    {TOOL_TYPES.map(t => (
                      <option key={t.value} value={t.value}>{t.label}</option>
                    ))}
                  </select>
                </div>
              </div>

              {/* Description */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
                <input
                  type="text"
                  value={form.description}
                  onChange={e => setForm({ ...form, description: e.target.value })}
                  placeholder="Short description of what this tool does"
                  className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>

              {/* Enabled For */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Enabled For</label>
                <div className="flex gap-3">
                  {([
                    { key: 'enabled_for_migration' as const, label: 'Migration', color: 'indigo' },
                    { key: 'enabled_for_chat' as const, label: 'Chat', color: 'cyan' },
                    { key: 'enabled_for_testing' as const, label: 'Testing', color: 'emerald' },
                  ]).map(({ key, label, color }) => (
                    <label key={key} className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={form[key]}
                        onChange={e => setForm({ ...form, [key]: e.target.checked })}
                        className={`rounded border-gray-300 text-${color}-600 focus:ring-${color}-500`}
                      />
                      <span className="text-sm text-gray-700">{label}</span>
                    </label>
                  ))}
                </div>
              </div>

              {/* Goal */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Goal
                  <span className="text-gray-400 font-normal ml-1">
                    — what should be achieved when this tool runs
                  </span>
                </label>
                <textarea
                  value={form.goal}
                  onChange={e => setForm({ ...form, goal: e.target.value })}
                  placeholder="e.g. Migrate all Spring Boot 2.x configurations to Spring Boot 3.x format, ensuring backward compatibility and passing all existing tests."
                  rows={3}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>

              {/* Agent Instructions */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Agent Instructions</label>
                <textarea
                  value={form.agent_instructions}
                  onChange={e => setForm({ ...form, agent_instructions: e.target.value })}
                  placeholder={`You are a specialized agent for...\n\nStep 1: Analyze the current codebase...\nStep 2: Identify patterns that need migration...\nStep 3: Apply transformations...`}
                  rows={8}
                  className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>

              {/* Allowed Tools */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-2">Allowed Tools</label>
                <div className="flex flex-wrap gap-1.5">
                  {AVAILABLE_TOOLS.map(t => (
                    <button
                      key={t}
                      type="button"
                      onClick={() => toggleAllowedTool(t)}
                      className={`px-2.5 py-1 rounded-md text-xs font-mono border transition-colors ${
                        form.allowed_tools.includes(t)
                          ? 'border-indigo-400 bg-indigo-50 text-indigo-700'
                          : 'border-gray-200 text-gray-500 hover:bg-gray-50'
                      }`}
                    >
                      {t}
                    </button>
                  ))}
                </div>
              </div>

              {/* Model + Max Turns + Timeout */}
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Model</label>
                  <select
                    value={form.model_config_id}
                    onChange={e => {
                      const configId = e.target.value;
                      const selected = modelList.find(m => m.id === configId);
                      setForm({
                        ...form,
                        model_config_id: configId,
                        model: selected ? selected.model : '',
                      });
                    }}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  >
                    <option value="">Default (config.ini)</option>
                    {modelList.map(m => (
                      <option key={m.id} value={m.id}>
                        {m.label} ({m.provider})
                      </option>
                    ))}
                  </select>
                  {form.model_config_id && (() => {
                    const sel = modelList.find(m => m.id === form.model_config_id);
                    if (!sel) return null;
                    const dot = PROVIDER_COLORS[sel.provider] || 'bg-gray-500';
                    return (
                      <div className="flex items-center gap-1.5 mt-1.5 text-xs text-gray-500">
                        <span className={`w-2 h-2 rounded-full ${dot}`} />
                        <span>{sel.provider}</span>
                        <span className="text-gray-300">|</span>
                        <span className="font-mono text-gray-400">{sel.model}</span>
                      </div>
                    );
                  })()}
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Max Turns</label>
                  <input
                    type="number"
                    value={form.max_turns}
                    onChange={e => setForm({ ...form, max_turns: parseInt(e.target.value) || 20 })}
                    min={1}
                    max={100}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Timeout (s)</label>
                  <input
                    type="number"
                    value={form.timeout_seconds}
                    onChange={e => setForm({ ...form, timeout_seconds: parseInt(e.target.value) || 300 })}
                    min={30}
                    max={3600}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                </div>
              </div>

              {/* Connection & Authentication */}
              <div className="border border-gray-200 rounded-lg p-4 space-y-4">
                <label className="block text-sm font-semibold text-gray-800">Connection & Authentication</label>

                {/* Connection Type */}
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Connection Type</label>
                  <select
                    value={form.credential_config.connection_type || ''}
                    onChange={e => updateCredConfig({ connection_type: e.target.value || undefined })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  >
                    {CONNECTION_TYPES.map(ct => (
                      <option key={ct.value} value={ct.value}>{ct.label}</option>
                    ))}
                  </select>
                </div>

                {/* Database connection fields */}
                {form.credential_config.connection_type === 'database' && (
                  <div className="space-y-2 bg-gray-50 rounded-md p-3">
                    <label className="block text-[10px] font-semibold text-gray-500 uppercase tracking-wider">Database Connection</label>
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <label className="block text-xs font-medium text-gray-600 mb-1">Host</label>
                        <input
                          type="text"
                          value={form.credential_config.host || ''}
                          onChange={e => updateCredConfig({ host: e.target.value })}
                          placeholder="db.example.com"
                          className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-600 mb-1">Port</label>
                        <input
                          type="text"
                          value={form.credential_config.port || ''}
                          onChange={e => updateCredConfig({ port: e.target.value })}
                          placeholder="5432"
                          className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                        />
                      </div>
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <label className="block text-xs font-medium text-gray-600 mb-1">Database</label>
                        <input
                          type="text"
                          value={form.credential_config.database || ''}
                          onChange={e => updateCredConfig({ database: e.target.value })}
                          placeholder="mydb"
                          className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                        />
                      </div>
                      <div>
                        <label className="block text-xs font-medium text-gray-600 mb-1">Schema</label>
                        <input
                          type="text"
                          value={form.credential_config.schema || ''}
                          onChange={e => updateCredConfig({ schema: e.target.value })}
                          placeholder="public"
                          className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                        />
                      </div>
                    </div>
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <label className="block text-xs font-medium text-gray-600 mb-1">Service Name <span className="text-gray-400 font-normal">(Oracle)</span></label>
                        <input
                          type="text"
                          value={form.credential_config.service_name || ''}
                          onChange={e => updateCredConfig({ service_name: e.target.value })}
                          placeholder="ORCL"
                          className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                        />
                      </div>
                      <div className="flex items-end pb-1">
                        <label className="flex items-center gap-2 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={form.credential_config.ssl_enabled === 'true'}
                            onChange={e => updateCredConfig({ ssl_enabled: e.target.checked ? 'true' : '' })}
                            className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                          />
                          <span className="text-sm text-gray-700">SSL / TLS</span>
                        </label>
                      </div>
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-600 mb-1">
                        Extra Parameters <span className="text-gray-400 font-normal">(JDBC params, connection string options)</span>
                      </label>
                      <input
                        type="text"
                        value={form.credential_config.extra_params || ''}
                        onChange={e => updateCredConfig({ extra_params: e.target.value })}
                        placeholder="e.g. ?sslmode=require&connect_timeout=10"
                        className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                      />
                    </div>
                  </div>
                )}

                {/* REST API connection fields */}
                {form.credential_config.connection_type === 'rest_api' && (
                  <div className="space-y-2 bg-gray-50 rounded-md p-3">
                    <label className="block text-[10px] font-semibold text-gray-500 uppercase tracking-wider">REST API Endpoint</label>
                    <div>
                      <label className="block text-xs font-medium text-gray-600 mb-1">Base URL</label>
                      <input
                        type="text"
                        value={form.credential_config.base_url || ''}
                        onChange={e => updateCredConfig({ base_url: e.target.value })}
                        placeholder="https://api.internal.example.com"
                        className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                      />
                    </div>
                  </div>
                )}

                {/* MCP Server connection fields */}
                {form.credential_config.connection_type === 'mcp_server' && (
                  <div className="space-y-2 bg-gray-50 rounded-md p-3">
                    <label className="block text-[10px] font-semibold text-gray-500 uppercase tracking-wider">MCP Server</label>
                    <div>
                      <label className="block text-xs font-medium text-gray-600 mb-1">Transport</label>
                      <div className="flex gap-3">
                        <label className="flex items-center gap-1.5 cursor-pointer">
                          <input
                            type="radio"
                            name="mcp_transport"
                            checked={(form.credential_config.mcp_transport || 'stdio') === 'stdio'}
                            onChange={() => updateCredConfig({ mcp_transport: 'stdio' })}
                            className="text-indigo-600 focus:ring-indigo-500"
                          />
                          <span className="text-sm text-gray-700">stdio (local process)</span>
                        </label>
                        <label className="flex items-center gap-1.5 cursor-pointer">
                          <input
                            type="radio"
                            name="mcp_transport"
                            checked={form.credential_config.mcp_transport === 'sse'}
                            onChange={() => updateCredConfig({ mcp_transport: 'sse' })}
                            className="text-indigo-600 focus:ring-indigo-500"
                          />
                          <span className="text-sm text-gray-700">SSE (HTTP endpoint)</span>
                        </label>
                      </div>
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-600 mb-1">
                        {form.credential_config.mcp_transport === 'sse' ? 'Endpoint URL' : 'Command'}
                      </label>
                      <input
                        type="text"
                        value={form.credential_config.mcp_command || ''}
                        onChange={e => updateCredConfig({ mcp_command: e.target.value })}
                        placeholder={form.credential_config.mcp_transport === 'sse'
                          ? 'http://localhost:3000/sse'
                          : 'npx -y @modelcontextprotocol/server-filesystem /path'}
                        className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500"
                      />
                    </div>
                    <div>
                      <label className="block text-xs font-medium text-gray-600 mb-1">Server Name</label>
                      <input
                        type="text"
                        value={form.credential_config.mcp_server_name || ''}
                        onChange={e => updateCredConfig({ mcp_server_name: e.target.value })}
                        placeholder="e.g. filesystem, db-tools"
                        className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                      />
                      <p className="text-[10px] text-gray-400 mt-1">
                        Short name used to reference this server in mcp_call
                      </p>
                    </div>
                  </div>
                )}

                {/* Divider between connection and auth */}
                {form.credential_config.connection_type && (
                  <div className="border-t border-gray-200 pt-3">
                    <label className="block text-[10px] font-semibold text-gray-500 uppercase tracking-wider mb-2">Authentication</label>
                  </div>
                )}

                {!form.credential_config.connection_type && (
                  <label className="block text-[10px] font-semibold text-gray-500 uppercase tracking-wider">Authentication</label>
                )}

                {/* Auth type selector */}
                <div className="flex gap-3">
                  {AUTH_TYPES.map(at => (
                    <label key={at} className="flex items-center gap-1.5 cursor-pointer">
                      <input
                        type="radio"
                        name="auth_type"
                        checked={(form.credential_config.auth_type || 'none') === at}
                        onChange={() => {
                          // Preserve connection fields when changing auth type
                          const connFields: Record<string, any> = {};
                          for (const k of ['connection_type', 'host', 'port', 'database', 'schema', 'service_name', 'ssl_enabled', 'extra_params', 'base_url', 'mcp_transport', 'mcp_command', 'mcp_server_name']) {
                            if (form.credential_config[k]) connFields[k] = form.credential_config[k];
                          }
                          if (at === 'none') {
                            setForm({ ...form, credential_config: { auth_type: 'none', ...connFields } });
                          } else {
                            updateCredConfig({ auth_type: at });
                          }
                        }}
                        className="text-indigo-600 focus:ring-indigo-500"
                      />
                      <span className="text-sm text-gray-700 capitalize">{at}</span>
                    </label>
                  ))}
                </div>

                {form.credential_config.auth_type && form.credential_config.auth_type !== 'none' && (
                  <>
                    {/* Credential source toggle */}
                    <div className="flex gap-3">
                      <label className="flex items-center gap-1.5 cursor-pointer">
                        <input
                          type="radio"
                          name="cred_source"
                          checked={credSource === 'direct'}
                          onChange={() => {
                            setCredSource('direct');
                            const cc = { ...form.credential_config };
                            delete cc.config_section;
                            setForm({ ...form, credential_config: cc });
                          }}
                          className="text-indigo-600 focus:ring-indigo-500"
                        />
                        <span className="text-sm text-gray-700">Enter directly</span>
                      </label>
                      <label className="flex items-center gap-1.5 cursor-pointer">
                        <input
                          type="radio"
                          name="cred_source"
                          checked={credSource === 'profile'}
                          onChange={() => setCredSource('profile')}
                          className="text-indigo-600 focus:ring-indigo-500"
                        />
                        <span className="text-sm text-gray-700">Config profile reference</span>
                      </label>
                    </div>

                    {/* Config profile reference */}
                    {credSource === 'profile' && (
                      <div>
                        <label className="block text-xs font-medium text-gray-600 mb-1">Profile Name</label>
                        <input
                          type="text"
                          value={form.credential_config.config_section || ''}
                          onChange={e => updateCredConfig({ config_section: e.target.value })}
                          placeholder="e.g. kerberos_prod"
                          className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                        />
                        <p className="text-[10px] text-gray-400 mt-1">
                          References [tool_cred_{form.credential_config.config_section || '<name>'}] in config.ini
                        </p>
                      </div>
                    )}

                    {/* Direct entry fields */}
                    {credSource === 'direct' && (
                      <div className="space-y-2">
                        {/* Basic auth fields */}
                        {form.credential_config.auth_type === 'basic' && (
                          <>
                            {/* Only show Base URL if not already set via REST API connection */}
                            {form.credential_config.connection_type !== 'rest_api' && (
                              <div>
                                <label className="block text-xs font-medium text-gray-600 mb-1">Base URL</label>
                                <input
                                  type="text"
                                  value={form.credential_config.base_url || ''}
                                  onChange={e => updateCredConfig({ base_url: e.target.value })}
                                  placeholder="https://api.internal.com"
                                  className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                                />
                              </div>
                            )}
                            <div className="grid grid-cols-2 gap-2">
                              <div>
                                <label className="block text-xs font-medium text-gray-600 mb-1">Username</label>
                                <input
                                  type="text"
                                  value={form.credential_config.username || ''}
                                  onChange={e => updateCredConfig({ username: e.target.value })}
                                  placeholder="svc-user"
                                  className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                                />
                              </div>
                              <div>
                                <label className="block text-xs font-medium text-gray-600 mb-1">Password</label>
                                <input
                                  type="password"
                                  value={form.credential_config.password || ''}
                                  onChange={e => updateCredConfig({ password: e.target.value })}
                                  placeholder={editingTool?.credential_config?.password_set ? '••••••••' : ''}
                                  className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                                />
                              </div>
                            </div>
                          </>
                        )}

                        {/* Bearer auth fields */}
                        {form.credential_config.auth_type === 'bearer' && (
                          <>
                            {form.credential_config.connection_type !== 'rest_api' && (
                              <div>
                                <label className="block text-xs font-medium text-gray-600 mb-1">Base URL</label>
                                <input
                                  type="text"
                                  value={form.credential_config.base_url || ''}
                                  onChange={e => updateCredConfig({ base_url: e.target.value })}
                                  placeholder="https://api.example.com"
                                  className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                                />
                              </div>
                            )}
                            <div>
                              <label className="block text-xs font-medium text-gray-600 mb-1">Token</label>
                              <input
                                type="password"
                                value={form.credential_config.token || ''}
                                onChange={e => updateCredConfig({ token: e.target.value })}
                                placeholder={editingTool?.credential_config?.token_set ? '••••••••' : ''}
                                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                              />
                            </div>
                          </>
                        )}

                        {/* Kerberos auth fields */}
                        {form.credential_config.auth_type === 'kerberos' && (
                          <>
                            <div className="grid grid-cols-2 gap-2">
                              <div>
                                <label className="block text-xs font-medium text-gray-600 mb-1">Realm</label>
                                <input
                                  type="text"
                                  value={form.credential_config.realm || ''}
                                  onChange={e => updateCredConfig({ realm: e.target.value })}
                                  placeholder="CORP.EXAMPLE.COM"
                                  className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                                />
                              </div>
                              <div>
                                <label className="block text-xs font-medium text-gray-600 mb-1">KDC</label>
                                <input
                                  type="text"
                                  value={form.credential_config.kdc || ''}
                                  onChange={e => updateCredConfig({ kdc: e.target.value })}
                                  placeholder="kdc.corp.example.com"
                                  className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                                />
                              </div>
                            </div>
                            <div>
                              <label className="block text-xs font-medium text-gray-600 mb-1">Principal</label>
                              <input
                                type="text"
                                value={form.credential_config.principal || ''}
                                onChange={e => updateCredConfig({ principal: e.target.value })}
                                placeholder="svc@CORP.EXAMPLE.COM"
                                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                              />
                            </div>
                            <div>
                              <label className="block text-xs font-medium text-gray-600 mb-1">Keytab Path</label>
                              <input
                                type="text"
                                value={form.credential_config.keytab_path || ''}
                                onChange={e => updateCredConfig({ keytab_path: e.target.value })}
                                placeholder={editingTool?.credential_config?.keytab_path_set ? '(set) /etc/keytabs/...' : '/etc/keytabs/svc.keytab'}
                                className="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                              />
                            </div>
                          </>
                        )}
                      </div>
                    )}

                    {/* Test Credentials button */}
                    <div className="flex items-center gap-3">
                      <button
                        type="button"
                        onClick={handleTestCredentials}
                        disabled={credTesting || !editingTool}
                        className="px-3 py-1.5 text-xs font-medium text-indigo-600 bg-indigo-50 rounded-md hover:bg-indigo-100 disabled:opacity-50 transition-colors"
                      >
                        {credTesting ? 'Testing...' : 'Test Credentials'}
                      </button>
                      {!editingTool && (
                        <span className="text-[10px] text-gray-400">Save first to test</span>
                      )}
                      {credTestResult && (
                        <span className={`text-xs ${credTestResult.status === 'ok' ? 'text-green-600' : 'text-red-600'}`}>
                          {credTestResult.status === 'ok' ? '\u2713' : '\u2717'} {credTestResult.detail}
                        </span>
                      )}
                    </div>
                  </>
                )}
              </div>

              {/* Tags */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Tags</label>
                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    value={tagInput}
                    onChange={e => setTagInput(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addTag(); } }}
                    placeholder="Add tag..."
                    className="flex-1 px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                  <button
                    type="button"
                    onClick={addTag}
                    className="px-3 py-2 text-sm text-indigo-600 hover:bg-indigo-50 rounded-md transition-colors"
                  >
                    Add
                  </button>
                </div>
                {form.tags.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-2">
                    {form.tags.map(tag => (
                      <span key={tag} className="inline-flex items-center gap-1 px-2 py-0.5 bg-indigo-50 text-indigo-700 rounded text-xs">
                        {tag}
                        <button onClick={() => removeTag(tag)} className="hover:text-indigo-900">&times;</button>
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* Modal footer */}
            <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-gray-200">
              <button
                onClick={() => setShowForm(false)}
                className="px-4 py-2 border border-gray-300 rounded-md text-sm font-medium text-gray-700 hover:bg-gray-50 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleSave}
                disabled={saving}
                className="px-4 py-2 bg-indigo-600 text-white rounded-md text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors"
              >
                {saving ? 'Saving...' : editingTool ? 'Update Tool' : 'Create Tool'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
