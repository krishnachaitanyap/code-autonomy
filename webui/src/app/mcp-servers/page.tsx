'use client';

import { useEffect, useState } from 'react';
import { mcpServers, type McpServer, type McpServerTool } from '@/lib/api';

const TRANSPORT_BADGE: Record<string, { label: string; color: string }> = {
  stdio: { label: 'stdio', color: 'bg-blue-100 text-blue-700' },
  sse: { label: 'SSE', color: 'bg-purple-100 text-purple-700' },
  'streamable-http': { label: 'HTTP', color: 'bg-emerald-100 text-emerald-700' },
};

const STATUS_DOT: Record<string, string> = {
  connected: 'bg-green-500',
  pending: 'bg-yellow-400',
  error: 'bg-red-500',
};

export default function McpServersPage() {
  const [servers, setServers] = useState<McpServer[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [discovering, setDiscovering] = useState<string | null>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<Record<string, { status: string; latency_ms: number; error?: string }>>({});

  // Form state
  const [formName, setFormName] = useState('');
  const [formDesc, setFormDesc] = useState('');
  const [formTransport, setFormTransport] = useState('stdio');
  const [formCommand, setFormCommand] = useState('');
  const [formUrl, setFormUrl] = useState('');
  const [formEnvVars, setFormEnvVars] = useState<[string, string][]>([]);
  const [formAuthType, setFormAuthType] = useState('none');
  const [formAuthToken, setFormAuthToken] = useState('');

  useEffect(() => { loadServers(); }, []);

  async function loadServers() {
    try {
      const { servers: s } = await mcpServers.list();
      setServers(s);
    } catch (err) {
      console.error('Failed to load MCP servers:', err);
    } finally {
      setLoading(false);
    }
  }

  function resetForm() {
    setFormName(''); setFormDesc(''); setFormTransport('stdio');
    setFormCommand(''); setFormUrl(''); setFormEnvVars([]);
    setFormAuthType('none'); setFormAuthToken('');
    setEditingId(null);
  }

  function openEdit(server: McpServer) {
    setFormName(server.name);
    setFormDesc(server.description);
    setFormTransport(server.transport);
    setFormCommand(server.command);
    setFormUrl(server.url);
    setFormEnvVars(Object.entries(server.env_vars || {}));
    setFormAuthType(server.auth_set ? 'bearer' : 'none');
    setFormAuthToken('');
    setEditingId(server.id);
    setShowForm(true);
  }

  async function handleSave() {
    const data: any = {
      name: formName,
      description: formDesc,
      transport: formTransport,
      command: formCommand,
      url: formUrl,
      env_vars: Object.fromEntries(formEnvVars.filter(([k]) => k)),
    };
    if (formAuthType !== 'none' && formAuthToken) {
      data.auth_config = { auth_type: formAuthType, token: formAuthToken };
    }
    try {
      if (editingId) {
        await mcpServers.update(editingId, data);
      } else {
        await mcpServers.create(data);
      }
      setShowForm(false);
      resetForm();
      loadServers();
    } catch (err: any) {
      alert(err.message || 'Failed to save');
    }
  }

  async function handleDelete(id: string) {
    if (!confirm('Delete this MCP server?')) return;
    try {
      await mcpServers.delete(id);
      loadServers();
    } catch (err: any) {
      alert(err.message || 'Failed to delete');
    }
  }

  async function handleDiscover(id: string) {
    setDiscovering(id);
    try {
      await mcpServers.discover(id);
      loadServers();
      setExpandedId(id);
    } catch (err: any) {
      alert(err.message || 'Discovery failed');
    } finally {
      setDiscovering(null);
    }
  }

  async function handleTest(id: string) {
    setTesting(id);
    try {
      const result = await mcpServers.test(id);
      setTestResult(prev => ({ ...prev, [id]: result }));
    } catch (err: any) {
      setTestResult(prev => ({ ...prev, [id]: { status: 'error', latency_ms: 0, error: err.message } }));
    } finally {
      setTesting(null);
    }
  }

  if (loading) return <p className="text-gray-500 p-4">Loading MCP servers...</p>;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">MCP Servers</h1>
          <p className="text-sm text-gray-500 mt-1">Register and manage Model Context Protocol servers</p>
        </div>
        <button
          onClick={() => { resetForm(); setShowForm(true); }}
          className="px-4 py-2 bg-indigo-600 text-white rounded-xl text-sm font-medium hover:bg-indigo-700 shadow-sm"
        >
          + Register Server
        </button>
      </div>

      {/* Add/Edit Form */}
      {showForm && (
        <div className="bg-white rounded-xl border border-gray-200 p-6 space-y-4 shadow-sm">
          <div className="flex items-center justify-between">
            <h2 className="text-lg font-semibold text-gray-900">
              {editingId ? 'Edit MCP Server' : 'Register New MCP Server'}
            </h2>
            <button onClick={() => { setShowForm(false); resetForm(); }} className="text-gray-400 hover:text-gray-600 text-sm">Cancel</button>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Server Name *</label>
              <input type="text" value={formName} onChange={e => setFormName(e.target.value)}
                placeholder="e.g., Filesystem Server" className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm" />
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Transport</label>
              <select value={formTransport} onChange={e => setFormTransport(e.target.value)}
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm">
                <option value="stdio">stdio (local process)</option>
                <option value="sse">SSE (Server-Sent Events)</option>
                <option value="streamable-http">Streamable HTTP</option>
              </select>
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Description</label>
            <input type="text" value={formDesc} onChange={e => setFormDesc(e.target.value)}
              placeholder="What does this server provide?" className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm" />
          </div>

          {/* Conditional: Command for stdio */}
          {formTransport === 'stdio' && (
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Command</label>
              <input type="text" value={formCommand} onChange={e => setFormCommand(e.target.value)}
                placeholder="e.g., npx -y @modelcontextprotocol/server-filesystem /path"
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm font-mono" />
              <p className="text-[10px] text-gray-400 mt-1">Shell command to launch the MCP server process</p>
            </div>
          )}

          {/* Conditional: URL for sse/http */}
          {formTransport !== 'stdio' && (
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Server URL</label>
              <input type="text" value={formUrl} onChange={e => setFormUrl(e.target.value)}
                placeholder="e.g., http://localhost:3001/mcp"
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm font-mono" />
            </div>
          )}

          {/* Environment Variables */}
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Environment Variables</label>
            {formEnvVars.map(([k, v], i) => (
              <div key={i} className="flex gap-2 mb-1">
                <input type="text" value={k} onChange={e => { const n = [...formEnvVars]; n[i] = [e.target.value, v]; setFormEnvVars(n); }}
                  placeholder="KEY" className="flex-1 px-2 py-1 border border-gray-200 rounded text-xs font-mono" />
                <input type="text" value={v} onChange={e => { const n = [...formEnvVars]; n[i] = [k, e.target.value]; setFormEnvVars(n); }}
                  placeholder="value" className="flex-1 px-2 py-1 border border-gray-200 rounded text-xs font-mono" />
                <button onClick={() => setFormEnvVars(formEnvVars.filter((_, j) => j !== i))} className="text-red-400 hover:text-red-600 text-xs">Remove</button>
              </div>
            ))}
            <button onClick={() => setFormEnvVars([...formEnvVars, ['', '']])} className="text-xs text-indigo-600 hover:text-indigo-800 mt-1">+ Add Variable</button>
          </div>

          {/* Auth */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Authentication</label>
              <select value={formAuthType} onChange={e => setFormAuthType(e.target.value)}
                className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm">
                <option value="none">None</option>
                <option value="bearer">Bearer Token</option>
                <option value="basic">Basic Auth</option>
                <option value="api_key">API Key</option>
              </select>
            </div>
            {formAuthType !== 'none' && (
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Token / Key</label>
                <input type="password" value={formAuthToken} onChange={e => setFormAuthToken(e.target.value)}
                  placeholder="Enter secret" className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm" />
              </div>
            )}
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <button onClick={() => { setShowForm(false); resetForm(); }}
              className="px-4 py-2 text-sm text-gray-600 hover:text-gray-800">Cancel</button>
            <button onClick={handleSave} disabled={!formName}
              className="px-4 py-2 bg-indigo-600 text-white rounded-xl text-sm font-medium hover:bg-indigo-700 disabled:opacity-40">
              {editingId ? 'Update Server' : 'Register Server'}
            </button>
          </div>
        </div>
      )}

      {/* Server List */}
      {servers.length > 0 ? (
        <div className="space-y-3">
          {servers.map(server => {
            const tb = TRANSPORT_BADGE[server.transport] || TRANSPORT_BADGE.stdio;
            const isExpanded = expandedId === server.id;
            const tr = testResult[server.id];

            return (
              <div key={server.id} className="bg-white rounded-xl border border-gray-200 overflow-hidden">
                {/* Server header */}
                <div className="px-5 py-4 flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className={`w-2.5 h-2.5 rounded-full ${STATUS_DOT[server.status] || 'bg-gray-300'}`} />
                    <div>
                      <div className="flex items-center gap-2">
                        <h3 className="text-sm font-semibold text-gray-900">{server.name}</h3>
                        <span className={`text-[10px] font-medium px-2 py-0.5 rounded-full ${tb.color}`}>{tb.label}</span>
                        {server.tools_count > 0 && (
                          <span className="text-[10px] font-mono text-gray-400">{server.tools_count} tools</span>
                        )}
                      </div>
                      {server.description && <p className="text-xs text-gray-500 mt-0.5">{server.description}</p>}
                      <div className="flex items-center gap-3 mt-1 text-[10px] text-gray-400">
                        {server.transport === 'stdio' && server.command && (
                          <span className="font-mono truncate max-w-xs">{server.command}</span>
                        )}
                        {server.transport !== 'stdio' && server.url && (
                          <span className="font-mono truncate max-w-xs">{server.url}</span>
                        )}
                        {server.last_connected_at && (
                          <span>Connected {new Date(server.last_connected_at).toLocaleDateString()}</span>
                        )}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    {tr && (
                      <span className={`text-[10px] font-mono px-2 py-0.5 rounded ${tr.status === 'ok' ? 'bg-green-50 text-green-600' : 'bg-red-50 text-red-600'}`}>
                        {tr.status === 'ok' ? `${tr.latency_ms}ms` : tr.error?.slice(0, 30)}
                      </span>
                    )}
                    <button onClick={() => handleTest(server.id)} disabled={testing === server.id}
                      className="px-2.5 py-1 text-[10px] font-medium bg-gray-100 rounded-lg hover:bg-gray-200 disabled:opacity-40">
                      {testing === server.id ? 'Testing...' : 'Test'}
                    </button>
                    <button onClick={() => handleDiscover(server.id)} disabled={discovering === server.id}
                      className="px-2.5 py-1 text-[10px] font-medium bg-indigo-50 text-indigo-700 rounded-lg hover:bg-indigo-100 disabled:opacity-40">
                      {discovering === server.id ? 'Discovering...' : 'Discover Tools'}
                    </button>
                    <button onClick={() => setExpandedId(isExpanded ? null : server.id)}
                      className="px-2.5 py-1 text-[10px] font-medium bg-gray-100 rounded-lg hover:bg-gray-200">
                      {isExpanded ? 'Collapse' : 'Details'}
                    </button>
                    <button onClick={() => openEdit(server)}
                      className="px-2.5 py-1 text-[10px] font-medium bg-gray-100 rounded-lg hover:bg-gray-200">
                      Edit
                    </button>
                    <button onClick={() => handleDelete(server.id)}
                      className="px-2.5 py-1 text-[10px] font-medium text-red-600 bg-red-50 rounded-lg hover:bg-red-100">
                      Delete
                    </button>
                  </div>
                </div>

                {/* Error banner */}
                {server.status === 'error' && server.last_error && (
                  <div className="px-5 py-2 bg-red-50 border-t border-red-100 text-xs text-red-600">
                    Error: {server.last_error}
                  </div>
                )}

                {/* Expanded: Discovered tools */}
                {isExpanded && (
                  <div className="px-5 pb-4 border-t border-gray-100 pt-3">
                    <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
                      Discovered Tools ({server.discovered_tools.length})
                    </h4>
                    {server.discovered_tools.length === 0 ? (
                      <p className="text-xs text-gray-400 italic">No tools discovered yet. Click &quot;Discover Tools&quot; to scan.</p>
                    ) : (
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                        {server.discovered_tools.map((tool, i) => (
                          <div key={i} className="bg-gray-50 rounded-lg px-3 py-2">
                            <div className="flex items-center gap-2">
                              <span className="text-[10px] font-mono font-bold text-indigo-600">{tool.name}</span>
                            </div>
                            <p className="text-[10px] text-gray-500 mt-0.5 line-clamp-2">{tool.description}</p>
                            {tool.inputSchema && Object.keys(tool.inputSchema).length > 0 && (
                              <div className="mt-1 flex flex-wrap gap-1">
                                {Object.keys(tool.inputSchema.properties || {}).slice(0, 5).map((param, j) => (
                                  <span key={j} className="text-[8px] font-mono px-1 py-0.5 rounded bg-gray-200 text-gray-600">{param}</span>
                                ))}
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      ) : (
        !showForm && (
          <div className="text-center py-16 bg-gradient-to-br from-indigo-50/50 to-white rounded-2xl border border-indigo-100">
            <div className="text-5xl mb-4">{'\uD83D\uDD0C'}</div>
            <h3 className="text-lg font-semibold text-gray-900">Model Context Protocol</h3>
            <p className="text-sm text-gray-500 mt-1 max-w-md mx-auto">
              Register MCP servers to extend your agent tools with external capabilities — file systems, databases, APIs, and more.
            </p>
            <button onClick={() => { resetForm(); setShowForm(true); }}
              className="mt-5 px-5 py-2.5 bg-indigo-600 text-white rounded-xl text-sm font-medium hover:bg-indigo-700 shadow-sm">
              Register First Server
            </button>
          </div>
        )
      )}
    </div>
  );
}
