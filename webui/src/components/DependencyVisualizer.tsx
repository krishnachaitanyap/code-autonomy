'use client';

import { useEffect, useState } from 'react';
import {
  repos,
  type RepoDependencies,
  type DownstreamService,
  type DataStore,
  type MessagingEntry,
  type ApiEndpointEntry,
} from '@/lib/api';

interface DependencyVisualizerProps {
  repoId: string;
  repoName: string;
}

type NodeKind = 'service' | 'datastore' | 'messaging' | 'api';

interface DepNode {
  id: string;
  label: string;
  kind: NodeKind;
  detail: string;
  direction?: string;
  confidence?: string;
  url?: string;
  http_method?: string;
  auth_type?: string;
  source_files?: string[];
  source_classes?: string[];
  invoking_endpoints?: ApiEndpointEntry[];
  impacted_services?: string[];
  impacted_datastores?: string[];
  impacted_messaging?: string[];
  regions?: string[];
}

const KIND_STYLES: Record<NodeKind, { bg: string; border: string; icon: string }> = {
  service:   { bg: 'bg-blue-50',   border: 'border-blue-300',   icon: '\u2601' },  // cloud
  datastore: { bg: 'bg-emerald-50', border: 'border-emerald-300', icon: '\uD83D\uDDC4\uFE0F' },  // file cabinet
  messaging: { bg: 'bg-amber-50',  border: 'border-amber-300',  icon: '\uD83D\uDCE8' },  // envelope
  api:       { bg: 'bg-purple-50', border: 'border-purple-300', icon: '\uD83D\uDD17' },  // link
};

function buildNodes(deps: RepoDependencies, identified: DownstreamService[]): DepNode[] {
  const nodes: DepNode[] = [];
  const seen = new Set<string>();

  for (const svc of deps.downstream_services) {
    const id = `svc-${svc.name}`;
    if (seen.has(id)) continue;
    seen.add(id);
    nodes.push({
      id,
      label: svc.name,
      kind: 'service',
      detail: svc.client_type ? `${svc.client_type}${svc.url ? ` \u2192 ${svc.url}` : ''}` : svc.url || '',
      url: svc.url,
      http_method: svc.http_method,
      auth_type: svc.auth_type,
      source_files: svc.source_files,
      source_classes: svc.source_classes,
      invoking_endpoints: svc.invoking_endpoints,
      regions: svc.regions,
    });
  }

  for (const ds of deps.data_stores) {
    const label = ds.entities?.join(', ') || ds.type;
    const id = `ds-${label}`;
    if (seen.has(id)) continue;
    seen.add(id);
    nodes.push({
      id,
      label,
      kind: 'datastore',
      detail: ds.type + (ds.url_pattern ? ` (${ds.url_pattern})` : ''),
      source_files: ds.source_files,
      source_classes: ds.source_classes,
      invoking_endpoints: ds.invoking_endpoints,
    });
  }

  for (const msg of deps.messaging) {
    const label = msg.topic || msg.type;
    const id = `msg-${label}-${msg.direction}`;
    if (seen.has(id)) continue;
    seen.add(id);
    nodes.push({
      id,
      label,
      kind: 'messaging',
      detail: `${msg.type} ${msg.direction}${msg.group ? ` (group: ${msg.group})` : ''}`,
      direction: msg.direction,
      source_files: msg.source_files,
      source_classes: msg.source_classes,
      invoking_endpoints: msg.invoking_endpoints,
    });
  }

  for (const ep of deps.api_endpoints.slice(0, 10)) {
    if (!ep.path) continue;
    const id = `api-${ep.http_method}-${ep.path}`;
    if (seen.has(id)) continue;
    seen.add(id);
    nodes.push({
      id,
      label: `${ep.http_method} ${ep.path}`,
      kind: 'api',
      detail: ep.class,
      impacted_services: ep.impacted_services,
      impacted_datastores: ep.impacted_datastores,
      impacted_messaging: ep.impacted_messaging,
    });
  }

  // Add identified services
  for (const svc of identified) {
    const id = `ident-${svc.name}`;
    if (seen.has(id)) continue;
    seen.add(id);
    nodes.push({
      id,
      label: svc.name,
      kind: 'service',
      detail: `identified (${svc.confidence || 'unknown'} confidence)`,
      confidence: svc.confidence,
    });
  }

  return nodes;
}

export default function DependencyVisualizer({ repoId, repoName }: DependencyVisualizerProps) {
  const [deps, setDeps] = useState<RepoDependencies | null>(null);
  const [identified, setIdentified] = useState<DownstreamService[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMessage, setLoadingMessage] = useState('Analyzing dependencies...');
  const [identifyPrompt, setIdentifyPrompt] = useState('');
  const [identifying, setIdentifying] = useState(false);
  const [filter, setFilter] = useState<NodeKind | 'all'>('all');
  const [selectedNode, setSelectedNode] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoadingMessage('Analyzing dependencies (may clone repo on first run)...');
    repos.getDependencies(repoId)
      .then(data => { if (!cancelled) setDeps(data); })
      .catch(() => { if (!cancelled) setDeps(prev => prev ?? { downstream_services: [], data_stores: [], messaging: [], api_endpoints: [] }); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [repoId]);

  async function handleIdentify() {
    if (!identifyPrompt.trim()) return;
    setIdentifying(true);
    try {
      const result = await repos.identifyDependencies(repoId, identifyPrompt);
      setIdentified(prev => {
        const existing = new Set(prev.map(s => s.name));
        const newOnes = result.identified_services.filter(s => !existing.has(s.name));
        return [...prev, ...newOnes];
      });
    } catch (err: any) {
      alert(err.message || 'Failed to identify dependencies');
    } finally {
      setIdentifying(false);
    }
  }

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-8 gap-2">
        <div className="w-5 h-5 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin" />
        <span className="text-xs text-gray-500">{loadingMessage}</span>
      </div>
    );
  }

  if (!deps) return null;

  const allNodes = buildNodes(deps, identified);
  const filteredNodes = filter === 'all' ? allNodes : allNodes.filter(n => n.kind === filter);

  const counts = {
    service: allNodes.filter(n => n.kind === 'service').length,
    datastore: allNodes.filter(n => n.kind === 'datastore').length,
    messaging: allNodes.filter(n => n.kind === 'messaging').length,
    api: allNodes.filter(n => n.kind === 'api').length,
  };

  return (
    <div className="space-y-4">
      {/* Summary counters */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => setFilter('all')}
          className={`px-2.5 py-1 rounded-full text-xs font-medium transition-colors ${
            filter === 'all' ? 'bg-gray-800 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
          }`}
        >
          All ({allNodes.length})
        </button>
        {(['service', 'datastore', 'messaging', 'api'] as NodeKind[]).map(kind => (
          <button
            key={kind}
            onClick={() => setFilter(kind)}
            className={`px-2.5 py-1 rounded-full text-xs font-medium transition-colors ${
              filter === kind
                ? `${KIND_STYLES[kind].bg} ${KIND_STYLES[kind].border} border`
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
            }`}
          >
            {KIND_STYLES[kind].icon} {kind} ({counts[kind]})
          </button>
        ))}
      </div>

      {/* Dependency graph (radial layout) */}
      <div className="relative bg-white border border-gray-200 rounded-lg p-6 min-h-[320px]">
        {filteredNodes.length === 0 ? (
          <p className="text-sm text-gray-400 text-center py-8">
            No downstream dependencies detected. Use the identify tool below to find more.
          </p>
        ) : (
          <div className="relative">
            {/* Central node */}
            <div className="flex justify-center mb-6">
              <div className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium shadow-sm">
                {repoName || 'This Service'}
              </div>
            </div>

            {/* Dependency nodes organized by kind */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
              {(['service', 'datastore', 'messaging', 'api'] as NodeKind[]).map(kind => {
                const kindNodes = filteredNodes.filter(n => n.kind === kind);
                if (kindNodes.length === 0) return null;
                return (
                  <div key={kind}>
                    <div className="text-[10px] font-medium text-gray-400 uppercase tracking-wider mb-2">
                      {KIND_STYLES[kind].icon} {kind === 'datastore' ? 'Data Stores' : kind === 'api' ? 'API Endpoints' : kind === 'messaging' ? 'Messaging' : 'Services'}
                    </div>
                    <div className="space-y-1.5">
                      {kindNodes.map(node => {
                        const isClickable = node.kind === 'service' || node.kind === 'datastore' || node.kind === 'messaging' || node.kind === 'api';
                        const isSelected = selectedNode === node.id;
                        return (
                        <div
                          key={node.id}
                          onClick={isClickable ? () => setSelectedNode(isSelected ? null : node.id) : undefined}
                          className={`px-3 py-2 rounded-lg border text-xs ${KIND_STYLES[node.kind].bg} ${KIND_STYLES[node.kind].border}${isClickable ? ' cursor-pointer hover:shadow-sm' : ''}${isSelected ? ' ring-2 ring-indigo-500' : ''}`}
                        >
                          <div className="flex items-center justify-between gap-2">
                            <span className="font-medium text-gray-800 truncate">{node.label}</span>
                            {node.confidence && (
                              <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                                node.confidence === 'high' ? 'bg-green-100 text-green-700' :
                                node.confidence === 'medium' ? 'bg-yellow-100 text-yellow-700' :
                                'bg-gray-100 text-gray-600'
                              }`}>
                                {node.confidence}
                              </span>
                            )}
                            {node.direction && (
                              <span className="text-[10px] text-gray-500">
                                {node.direction === 'consumer' ? '\u2B07' : node.direction === 'producer' ? '\u2B06' : '\u2194'}
                              </span>
                            )}
                          </div>
                          {node.detail && (
                            <div className="text-[10px] text-gray-500 mt-0.5 truncate">{node.detail}</div>
                          )}
                          {node.url && node.url.includes('/') && (
                            <div className="text-[10px] text-gray-400 mt-0.5 truncate font-mono">{node.url}</div>
                          )}
                          {(node.http_method || node.auth_type) && (
                            <div className="flex items-center gap-1 mt-1 flex-wrap">
                              {node.http_method && (
                                <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                                  node.http_method === 'GET' ? 'bg-green-100 text-green-700' :
                                  node.http_method === 'POST' ? 'bg-blue-100 text-blue-700' :
                                  node.http_method === 'PUT' ? 'bg-yellow-100 text-yellow-700' :
                                  node.http_method === 'DELETE' ? 'bg-red-100 text-red-700' :
                                  'bg-gray-100 text-gray-700'
                                }`}>
                                  {node.http_method}
                                </span>
                              )}
                              {node.auth_type && (
                                <span className="px-1.5 py-0.5 bg-violet-50 border border-violet-200 rounded text-[10px] text-violet-700 font-medium">
                                  {node.auth_type}
                                </span>
                              )}
                            </div>
                          )}
                        </div>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>

      {/* Detail panel for selected node */}
      {selectedNode && (() => {
        const node = allNodes.find(n => n.id === selectedNode);
        if (!node) return null;
        return (
          <div className="bg-white border border-indigo-200 rounded-lg p-4 space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="font-medium text-gray-900 text-sm">{node.label}</span>
                {node.detail && (
                  <span className="px-2 py-0.5 bg-indigo-50 text-indigo-700 text-[10px] rounded-full font-medium">
                    {node.detail.split(' ')[0]}
                  </span>
                )}
              </div>
              <button
                onClick={() => setSelectedNode(null)}
                className="text-gray-400 hover:text-gray-600 text-sm"
              >
                ✕
              </button>
            </div>

            {node.url && node.url.includes('/') && (
              <div>
                <h5 className="text-xs font-medium text-gray-500 mb-1">URL</h5>
                <div className="text-xs text-gray-700 font-mono bg-gray-50 px-2 py-1 rounded break-all">{node.url}</div>
              </div>
            )}

            {(node.http_method || node.auth_type) && (
              <div className="flex items-center gap-2">
                {node.http_method && (
                  <div>
                    <h5 className="text-xs font-medium text-gray-500 mb-1">HTTP Method</h5>
                    <span className={`px-2 py-0.5 rounded text-[11px] font-bold ${
                      node.http_method === 'GET' ? 'bg-green-100 text-green-700' :
                      node.http_method === 'POST' ? 'bg-blue-100 text-blue-700' :
                      node.http_method === 'PUT' ? 'bg-yellow-100 text-yellow-700' :
                      node.http_method === 'DELETE' ? 'bg-red-100 text-red-700' :
                      'bg-gray-100 text-gray-700'
                    }`}>
                      {node.http_method}
                    </span>
                  </div>
                )}
                {node.auth_type && (
                  <div>
                    <h5 className="text-xs font-medium text-gray-500 mb-1">Auth Type</h5>
                    <span className="px-2 py-0.5 bg-violet-50 border border-violet-200 rounded text-[11px] text-violet-700 font-medium">
                      {node.auth_type}
                    </span>
                  </div>
                )}
              </div>
            )}

            {node.regions && node.regions.length > 0 && (
              <div>
                <h5 className="text-xs font-medium text-gray-500 mb-1">Regions</h5>
                <div className="flex flex-wrap gap-1.5">
                  {node.regions.map((r, i) => (
                    <span key={i} className="px-2 py-0.5 bg-violet-50 border border-violet-200 rounded text-[11px] text-violet-700 font-medium">{r}</span>
                  ))}
                </div>
              </div>
            )}

            {node.source_files && node.source_files.length > 0 && (
              <div>
                <h5 className="text-xs font-medium text-gray-500 mb-1">Source Files</h5>
                <ul className="space-y-0.5">
                  {node.source_files.map((f, i) => (
                    <li key={i} className="text-xs text-gray-700 font-mono bg-gray-50 px-2 py-1 rounded">
                      {f}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {node.invoking_endpoints && node.invoking_endpoints.length > 0 && (
              <div>
                <h5 className="text-xs font-medium text-gray-500 mb-1">Invoking APIs</h5>
                <table className="w-full text-xs">
                  <thead>
                    <tr className="text-left text-gray-400 border-b border-gray-100">
                      <th className="pb-1 pr-3 font-medium">Method</th>
                      <th className="pb-1 pr-3 font-medium">Path</th>
                      <th className="pb-1 font-medium">Class</th>
                    </tr>
                  </thead>
                  <tbody>
                    {node.invoking_endpoints.map((ep, i) => (
                      <tr key={i} className="border-b border-gray-50">
                        <td className="py-1 pr-3">
                          <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                            ep.http_method === 'GET' ? 'bg-green-100 text-green-700' :
                            ep.http_method === 'POST' ? 'bg-blue-100 text-blue-700' :
                            ep.http_method === 'PUT' ? 'bg-yellow-100 text-yellow-700' :
                            ep.http_method === 'DELETE' ? 'bg-red-100 text-red-700' :
                            'bg-gray-100 text-gray-700'
                          }`}>
                            {ep.http_method}
                          </span>
                        </td>
                        <td className="py-1 pr-3 font-mono text-gray-700">{ep.path}</td>
                        <td className="py-1 text-gray-500">{ep.class}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* Downstream impact for API endpoint nodes */}
            {node.kind === 'api' && (node.impacted_services?.length || node.impacted_datastores?.length || node.impacted_messaging?.length) ? (
              <div className="space-y-2">
                {node.impacted_services && node.impacted_services.length > 0 && (
                  <div>
                    <h5 className="text-xs font-medium text-gray-500 mb-1">Downstream Services</h5>
                    <div className="flex flex-wrap gap-1.5">
                      {node.impacted_services.map((s, i) => (
                        <span key={i} className="px-2 py-0.5 bg-blue-50 border border-blue-200 rounded text-[11px] text-blue-700 font-medium">{s}</span>
                      ))}
                    </div>
                  </div>
                )}
                {node.impacted_datastores && node.impacted_datastores.length > 0 && (
                  <div>
                    <h5 className="text-xs font-medium text-gray-500 mb-1">Data Stores</h5>
                    <div className="flex flex-wrap gap-1.5">
                      {node.impacted_datastores.map((d, i) => (
                        <span key={i} className="px-2 py-0.5 bg-emerald-50 border border-emerald-200 rounded text-[11px] text-emerald-700 font-medium">{d}</span>
                      ))}
                    </div>
                  </div>
                )}
                {node.impacted_messaging && node.impacted_messaging.length > 0 && (
                  <div>
                    <h5 className="text-xs font-medium text-gray-500 mb-1">Messaging</h5>
                    <div className="flex flex-wrap gap-1.5">
                      {node.impacted_messaging.map((m, i) => (
                        <span key={i} className="px-2 py-0.5 bg-amber-50 border border-amber-200 rounded text-[11px] text-amber-700 font-medium">{m}</span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            ) : node.kind === 'api' ? (
              <p className="text-xs text-gray-400">No downstream impact detected.</p>
            ) : null}

            {node.kind !== 'api' && (!node.source_files || node.source_files.length === 0) &&
             (!node.invoking_endpoints || node.invoking_endpoints.length === 0) && (
              <p className="text-xs text-gray-400">No source location or invoking API data available for this node.</p>
            )}
          </div>
        );
      })()}

      {/* Identified Skill — prompt to identify additional downstreams */}
      <div className="bg-white border border-gray-200 rounded-lg p-4">
        <div className="mb-2">
          <h4 className="text-sm font-medium text-gray-900">Identify Additional Dependencies</h4>
          <p className="text-xs text-gray-500 mt-0.5">
            Provide service names, patterns, or keywords to scan for in the codebase.
            Separate multiple terms with commas. Type <span className="font-mono text-gray-600">RESTProxy</span> or <span className="font-mono text-gray-600">enterprise</span> to scan for custom proxy patterns and property-based service URLs.
          </p>
        </div>
        <div className="flex gap-2">
          <textarea
            value={identifyPrompt}
            onChange={e => setIdentifyPrompt(e.target.value)}
            rows={2}
            placeholder="e.g. OrderService, PaymentGateway, RESTProxy, enterprise"
            className="flex-1 px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none"
          />
          <button
            onClick={handleIdentify}
            disabled={identifying || !identifyPrompt.trim()}
            className="px-4 py-2 bg-indigo-600 text-white text-sm rounded-md hover:bg-indigo-700 disabled:opacity-50 self-end"
          >
            {identifying ? 'Scanning...' : 'Identify'}
          </button>
        </div>
        {identified.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2">
            {identified.map((svc, i) => (
              <span key={i} className="px-2 py-1 bg-blue-50 border border-blue-200 rounded-md text-xs text-blue-700">
                {svc.name}
                <span className="text-[10px] text-blue-400 ml-1">({svc.confidence})</span>
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
