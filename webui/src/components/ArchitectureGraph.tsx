'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Panel,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type NodeMouseHandler,
  MarkerType,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import dagre from 'dagre';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Symbol {
  fqn: string;
  name: string;
  file_path: string;
  symbol_type: string;
  line_start: number;
  line_end: number;
  signature: string;
  parent_class: string;
}

interface FileTreeEntry {
  path: string;
  name: string;
  directory: string;
  extension: string;
  file_type: string;
  size: number;
}

interface ArchitectureGraphProps {
  repoId: string;
  symbols: Symbol[];
  fileTree?: FileTreeEntry[];
  dependencies?: any;
}

// ---------------------------------------------------------------------------
// Layer detection — classify files into architectural layers
// ---------------------------------------------------------------------------

const LAYER_RULES: { pattern: RegExp; layer: string }[] = [
  { pattern: /\/(controller|resource|endpoint|rest|api|handler|route)\//i, layer: 'API' },
  { pattern: /\/(controller|Controller|Resource)\./i, layer: 'API' },
  { pattern: /Controller\.(java|ts|py|go)$/i, layer: 'API' },
  { pattern: /Resource\.(java|ts|py)$/i, layer: 'API' },
  { pattern: /\/(service|usecase|business|domain)\//i, layer: 'Service' },
  { pattern: /Service\.(java|ts|py|go)$/i, layer: 'Service' },
  { pattern: /Impl\.(java|ts|py)$/i, layer: 'Service' },
  { pattern: /\/(repository|repo|dao|mapper|persistence|data)\//i, layer: 'Data' },
  { pattern: /Repository\.(java|ts|py)$/i, layer: 'Data' },
  { pattern: /Dao\.(java|ts|py)$/i, layer: 'Data' },
  { pattern: /\/(model|entity|dto|vo|pojo|schema)\//i, layer: 'Model' },
  { pattern: /\/(config|configuration|setup|properties)\//i, layer: 'Config' },
  { pattern: /Config\.(java|ts|py)$/i, layer: 'Config' },
  { pattern: /\/(test|spec|__test__|__spec__|e2e)\//i, layer: 'Test' },
  { pattern: /Test\.(java|ts|py)$/i, layer: 'Test' },
  { pattern: /\.test\.(ts|js|tsx|jsx)$/i, layer: 'Test' },
  { pattern: /\.spec\.(ts|js|tsx|jsx)$/i, layer: 'Test' },
  { pattern: /\/(util|utils|helper|helpers|common|shared|lib)\//i, layer: 'Utility' },
  { pattern: /\/(middleware|filter|interceptor|aspect)\//i, layer: 'Middleware' },
  { pattern: /\/(client|remote|proxy|feign|integration)\//i, layer: 'External' },
  { pattern: /Client\.(java|ts|py)$/i, layer: 'External' },
];

const LAYER_COLORS: Record<string, { bg: string; border: string; text: string; minimap: string }> = {
  'API':        { bg: '#dbeafe', border: '#3b82f6', text: '#1e40af', minimap: '#3b82f6' },
  'Service':    { bg: '#d1fae5', border: '#10b981', text: '#065f46', minimap: '#10b981' },
  'Data':       { bg: '#fef3c7', border: '#f59e0b', text: '#92400e', minimap: '#f59e0b' },
  'Model':      { bg: '#ede9fe', border: '#8b5cf6', text: '#5b21b6', minimap: '#8b5cf6' },
  'Config':     { bg: '#f3f4f6', border: '#6b7280', text: '#374151', minimap: '#6b7280' },
  'Test':       { bg: '#fce7f3', border: '#ec4899', text: '#9d174d', minimap: '#ec4899' },
  'Utility':    { bg: '#e0e7ff', border: '#6366f1', text: '#3730a3', minimap: '#6366f1' },
  'Middleware': { bg: '#ffedd5', border: '#f97316', text: '#9a3412', minimap: '#f97316' },
  'External':   { bg: '#fecdd3', border: '#ef4444', text: '#991b1b', minimap: '#ef4444' },
  'Other':      { bg: '#f9fafb', border: '#d1d5db', text: '#6b7280', minimap: '#9ca3af' },
};

function detectLayer(filePath: string): string {
  for (const rule of LAYER_RULES) {
    if (rule.pattern.test(filePath)) return rule.layer;
  }
  return 'Other';
}

// ---------------------------------------------------------------------------
// Graph layout with Dagre
// ---------------------------------------------------------------------------

function getLayoutedElements(
  nodes: Node[],
  edges: Edge[],
  direction: 'TB' | 'LR' = 'TB',
): { nodes: Node[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: direction, nodesep: 60, ranksep: 80, marginx: 30, marginy: 30 });

  nodes.forEach((node) => {
    g.setNode(node.id, { width: 220, height: 60 });
  });

  edges.forEach((edge) => {
    g.setEdge(edge.source, edge.target);
  });

  dagre.layout(g);

  const layoutedNodes = nodes.map((node) => {
    const pos = g.node(node.id);
    return {
      ...node,
      position: { x: pos.x - 110, y: pos.y - 30 },
    };
  });

  return { nodes: layoutedNodes, edges };
}

// ---------------------------------------------------------------------------
// Build graph from symbols
// ---------------------------------------------------------------------------

function buildGraph(symbols: Symbol[], viewMode: 'files' | 'classes') {
  const nodes: Node[] = [];
  const edges: Edge[] = [];
  const nodeIds = new Set<string>();

  if (viewMode === 'files') {
    // Group symbols by file → one node per file
    const fileMap = new Map<string, Symbol[]>();
    for (const sym of symbols) {
      if (!sym.file_path) continue;
      const existing = fileMap.get(sym.file_path) || [];
      existing.push(sym);
      fileMap.set(sym.file_path, existing);
    }

    for (const [filePath, syms] of Array.from(fileMap.entries())) {
      const layer = detectLayer(filePath);
      const colors = LAYER_COLORS[layer] || LAYER_COLORS['Other'];
      const fileName = filePath.split('/').pop() || filePath;
      const classCount = syms.filter(s => s.symbol_type === 'class').length;
      const methodCount = syms.filter(s => s.symbol_type === 'method' || s.symbol_type === 'function').length;

      const id = filePath;
      nodeIds.add(id);
      nodes.push({
        id,
        type: 'default',
        position: { x: 0, y: 0 },
        data: {
          label: (
            <div style={{ fontSize: 11, lineHeight: 1.3 }}>
              <div style={{ fontWeight: 600, color: colors.text, marginBottom: 2 }}>
                {fileName}
              </div>
              <div style={{ fontSize: 9, color: '#6b7280' }}>
                {layer} · {classCount}C · {methodCount}M
              </div>
            </div>
          ),
        },
        style: {
          background: colors.bg,
          border: `1.5px solid ${colors.border}`,
          borderRadius: 8,
          padding: '6px 10px',
          width: 220,
          fontSize: 11,
        },
      });
    }

    // Edges: file A imports from file B (inferred from parent_class references)
    const classToFile = new Map<string, string>();
    for (const sym of symbols) {
      if (sym.symbol_type === 'class' && sym.file_path) {
        classToFile.set(sym.name, sym.file_path);
      }
    }

    for (const sym of symbols) {
      if (sym.parent_class && sym.file_path) {
        const targetFile = classToFile.get(sym.parent_class);
        if (targetFile && targetFile !== sym.file_path && nodeIds.has(targetFile)) {
          const edgeId = `${sym.file_path}->${targetFile}`;
          if (!edges.find(e => e.id === edgeId)) {
            edges.push({
              id: edgeId,
              source: sym.file_path,
              target: targetFile,
              animated: false,
              style: { stroke: '#94a3b8', strokeWidth: 1.5 },
              markerEnd: { type: MarkerType.ArrowClosed, color: '#94a3b8', width: 15, height: 15 },
            });
          }
        }
      }
    }
  } else {
    // Class/function view — one node per class
    for (const sym of symbols) {
      if (sym.symbol_type !== 'class' && sym.symbol_type !== 'interface') continue;
      const layer = detectLayer(sym.file_path);
      const colors = LAYER_COLORS[layer] || LAYER_COLORS['Other'];
      const methods = symbols.filter(s => s.parent_class === sym.name && (s.symbol_type === 'method' || s.symbol_type === 'function'));

      const id = sym.fqn || sym.name;
      nodeIds.add(id);
      nodes.push({
        id,
        type: 'default',
        position: { x: 0, y: 0 },
        data: {
          label: (
            <div style={{ fontSize: 11, lineHeight: 1.3 }}>
              <div style={{ fontWeight: 600, color: colors.text }}>
                {sym.name}
              </div>
              <div style={{ fontSize: 9, color: '#6b7280' }}>
                {sym.symbol_type} · {methods.length} methods · {layer}
              </div>
            </div>
          ),
        },
        style: {
          background: colors.bg,
          border: `1.5px solid ${colors.border}`,
          borderRadius: 8,
          padding: '6px 10px',
          width: 220,
          fontSize: 11,
        },
      });
    }

    // Edges: inheritance / parent_class relationships
    for (const sym of symbols) {
      if (sym.parent_class && sym.symbol_type === 'class') {
        const sourceId = sym.fqn || sym.name;
        const targetId = symbols.find(s => s.name === sym.parent_class)?.fqn || sym.parent_class;
        if (nodeIds.has(sourceId) && nodeIds.has(targetId) && sourceId !== targetId) {
          edges.push({
            id: `${sourceId}-extends->${targetId}`,
            source: sourceId,
            target: targetId,
            label: 'extends',
            animated: false,
            style: { stroke: '#8b5cf6', strokeWidth: 1.5, strokeDasharray: '5 3' },
            markerEnd: { type: MarkerType.ArrowClosed, color: '#8b5cf6', width: 15, height: 15 },
          });
        }
      }
    }
  }

  // Apply Dagre layout
  if (nodes.length > 0) {
    return getLayoutedElements(nodes, edges, 'TB');
  }
  return { nodes, edges };
}

// ---------------------------------------------------------------------------
// Build graph from file tree (fallback when no symbols)
// ---------------------------------------------------------------------------

function buildGraphFromFileTree(files: FileTreeEntry[], groupBy: 'directory' | 'layer') {
  const nodes: Node[] = [];
  const edges: Edge[] = [];

  if (groupBy === 'directory') {
    // Group files by directory → one node per directory
    const dirMap = new Map<string, FileTreeEntry[]>();
    for (const f of files) {
      const dir = f.directory || '(root)';
      const existing = dirMap.get(dir) || [];
      existing.push(f);
      dirMap.set(dir, existing);
    }

    for (const [dir, dirFiles] of Array.from(dirMap.entries())) {
      const layer = detectLayer(dir + '/');
      const colors = LAYER_COLORS[layer] || LAYER_COLORS['Other'];
      const sourceCount = dirFiles.filter(f => f.file_type === 'source').length;
      const configCount = dirFiles.filter(f => f.file_type === 'config').length;

      nodes.push({
        id: dir,
        type: 'default',
        position: { x: 0, y: 0 },
        data: {
          label: (
            <div style={{ fontSize: 11, lineHeight: 1.3 }}>
              <div style={{ fontWeight: 600, color: colors.text, marginBottom: 2 }}>
                {dir.split('/').pop() || dir}
              </div>
              <div style={{ fontSize: 9, color: '#6b7280' }}>
                {layer} · {dirFiles.length} files ({sourceCount} src, {configCount} cfg)
              </div>
            </div>
          ),
        },
        style: {
          background: colors.bg,
          border: `1.5px solid ${colors.border}`,
          borderRadius: 8,
          padding: '6px 10px',
          width: 220,
        },
      });
    }

    // Edges: parent directory → child directory
    const dirNames = Array.from(dirMap.keys());
    const dirNameSet = new Set(dirNames);
    for (const dir of dirNames) {
      const parts = dir.split('/');
      if (parts.length > 1) {
        const parent = parts.slice(0, -1).join('/');
        if (dirNameSet.has(parent)) {
          edges.push({
            id: `${parent}->${dir}`,
            source: parent,
            target: dir,
            style: { stroke: '#d1d5db', strokeWidth: 1.5 },
            markerEnd: { type: MarkerType.ArrowClosed, color: '#d1d5db', width: 12, height: 12 },
          });
        }
      }
    }
  } else {
    // Group by architectural layer
    const layerMap = new Map<string, FileTreeEntry[]>();
    for (const f of files) {
      if (f.file_type !== 'source') continue;
      const layer = detectLayer(f.path);
      const existing = layerMap.get(layer) || [];
      existing.push(f);
      layerMap.set(layer, existing);
    }

    for (const [layer, layerFiles] of Array.from(layerMap.entries())) {
      const colors = LAYER_COLORS[layer] || LAYER_COLORS['Other'];
      const dirs = new Set(layerFiles.map(f => f.directory));

      nodes.push({
        id: layer,
        type: 'default',
        position: { x: 0, y: 0 },
        data: {
          label: (
            <div style={{ fontSize: 12, lineHeight: 1.4 }}>
              <div style={{ fontWeight: 700, color: colors.text, marginBottom: 3, fontSize: 13 }}>
                {layer}
              </div>
              <div style={{ fontSize: 10, color: '#6b7280' }}>
                {layerFiles.length} files · {dirs.size} dirs
              </div>
              <div style={{ fontSize: 9, color: '#9ca3af', marginTop: 2, maxHeight: 40, overflow: 'hidden' }}>
                {layerFiles.slice(0, 4).map(f => f.name).join(', ')}
                {layerFiles.length > 4 ? `, +${layerFiles.length - 4}` : ''}
              </div>
            </div>
          ),
        },
        style: {
          background: colors.bg,
          border: `2px solid ${colors.border}`,
          borderRadius: 12,
          padding: '10px 14px',
          width: 240,
        },
      });
    }

    // Standard architectural edges
    const layerOrder = ['API', 'Middleware', 'Service', 'Data', 'External'];
    const presentLayers = layerOrder.filter(l => layerMap.has(l));
    for (let i = 0; i < presentLayers.length - 1; i++) {
      edges.push({
        id: `${presentLayers[i]}->${presentLayers[i + 1]}`,
        source: presentLayers[i],
        target: presentLayers[i + 1],
        style: { stroke: '#94a3b8', strokeWidth: 2 },
        markerEnd: { type: MarkerType.ArrowClosed, color: '#94a3b8', width: 15, height: 15 },
      });
    }
    // Model connects to Service and Data
    if (layerMap.has('Model')) {
      if (layerMap.has('Service')) edges.push({
        id: 'Service->Model', source: 'Service', target: 'Model',
        style: { stroke: '#8b5cf6', strokeWidth: 1.5, strokeDasharray: '5 3' },
        markerEnd: { type: MarkerType.ArrowClosed, color: '#8b5cf6', width: 12, height: 12 },
      });
      if (layerMap.has('Data')) edges.push({
        id: 'Data->Model', source: 'Data', target: 'Model',
        style: { stroke: '#8b5cf6', strokeWidth: 1.5, strokeDasharray: '5 3' },
        markerEnd: { type: MarkerType.ArrowClosed, color: '#8b5cf6', width: 12, height: 12 },
      });
    }
    // Config connects to everything
    if (layerMap.has('Config')) {
      for (const l of presentLayers) {
        if (l !== 'Config') edges.push({
          id: `Config->${l}`, source: 'Config', target: l,
          style: { stroke: '#d1d5db', strokeWidth: 1, strokeDasharray: '3 3' },
          markerEnd: { type: MarkerType.ArrowClosed, color: '#d1d5db', width: 10, height: 10 },
        });
      }
    }
    // Test connects to Service and API
    if (layerMap.has('Test')) {
      if (layerMap.has('Service')) edges.push({
        id: 'Test->Service', source: 'Test', target: 'Service',
        style: { stroke: '#ec4899', strokeWidth: 1, strokeDasharray: '3 3' },
        markerEnd: { type: MarkerType.ArrowClosed, color: '#ec4899', width: 10, height: 10 },
      });
    }
  }

  if (nodes.length > 0) {
    return getLayoutedElements(nodes, edges, 'TB');
  }
  return { nodes, edges };
}

// ---------------------------------------------------------------------------
// Detail Panel
// ---------------------------------------------------------------------------

function DetailPanel({ symbol, symbols, onClose }: { symbol: Symbol | null; symbols: Symbol[]; onClose: () => void }) {
  if (!symbol) return null;

  const layer = detectLayer(symbol.file_path);
  const colors = LAYER_COLORS[layer] || LAYER_COLORS['Other'];
  const relatedSymbols = symbols.filter(
    s => s.file_path === symbol.file_path && s.name !== symbol.name
  );
  const referencedBy = symbols.filter(s => s.parent_class === symbol.name);

  return (
    <div className="absolute top-2 right-2 w-80 bg-white rounded-lg border border-gray-200 shadow-xl z-10 max-h-[calc(100%-16px)] overflow-y-auto">
      <div className="sticky top-0 bg-white border-b border-gray-200 px-4 py-3 flex items-center justify-between">
        <div>
          <h3 className="font-semibold text-sm text-gray-900">{symbol.name}</h3>
          <p className="text-[10px] text-gray-500">{symbol.symbol_type} · {layer}</p>
        </div>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>
      <div className="p-4 space-y-3 text-xs">
        <div>
          <span className="text-gray-500">File:</span>
          <span className="ml-1 font-mono text-gray-800">{symbol.file_path}</span>
        </div>
        {symbol.signature && (
          <div>
            <span className="text-gray-500">Signature:</span>
            <pre className="mt-1 bg-gray-50 rounded p-2 text-[10px] font-mono overflow-x-auto">{symbol.signature}</pre>
          </div>
        )}
        <div className="flex gap-4">
          <div>
            <span className="text-gray-500">Lines:</span>
            <span className="ml-1">{symbol.line_start}–{symbol.line_end}</span>
          </div>
          {symbol.parent_class && (
            <div>
              <span className="text-gray-500">Extends:</span>
              <span className="ml-1 font-medium" style={{ color: colors.text }}>{symbol.parent_class}</span>
            </div>
          )}
        </div>

        {relatedSymbols.length > 0 && (
          <div>
            <p className="text-gray-500 font-medium mb-1">In same file ({relatedSymbols.length}):</p>
            <div className="space-y-0.5 max-h-32 overflow-y-auto">
              {relatedSymbols.slice(0, 15).map((s, i) => (
                <div key={i} className="flex items-center gap-1.5">
                  <span className="text-[9px] px-1 py-0.5 rounded bg-gray-100 text-gray-600">{s.symbol_type}</span>
                  <span className="text-gray-800 truncate">{s.name}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {referencedBy.length > 0 && (
          <div>
            <p className="text-gray-500 font-medium mb-1">Referenced by ({referencedBy.length}):</p>
            <div className="space-y-0.5 max-h-32 overflow-y-auto">
              {referencedBy.slice(0, 10).map((s, i) => (
                <div key={i} className="text-gray-800 truncate">{s.name} ({s.symbol_type})</div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export default function ArchitectureGraph({ repoId, symbols, fileTree, dependencies }: ArchitectureGraphProps) {
  const hasSymbols = symbols.length > 0;
  const hasFileTree = (fileTree || []).length > 0;

  const [viewMode, setViewMode] = useState<'files' | 'classes' | 'directories' | 'layers'>(
    hasSymbols ? 'files' : 'layers'
  );
  const [layerFilter, setLayerFilter] = useState<string | null>(null);
  const [selectedSymbol, setSelectedSymbol] = useState<Symbol | null>(null);
  const [searchQuery, setSearchQuery] = useState('');

  const filteredSymbols = useMemo(() => {
    let syms = symbols;
    if (layerFilter) {
      syms = syms.filter(s => detectLayer(s.file_path) === layerFilter);
    }
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      syms = syms.filter(s =>
        s.name.toLowerCase().includes(q) ||
        s.file_path.toLowerCase().includes(q) ||
        s.fqn.toLowerCase().includes(q)
      );
    }
    return syms;
  }, [symbols, layerFilter, searchQuery]);

  const filteredFileTree = useMemo(() => {
    let files = fileTree || [];
    if (layerFilter) {
      files = files.filter(f => detectLayer(f.path) === layerFilter);
    }
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      files = files.filter(f => f.path.toLowerCase().includes(q) || f.name.toLowerCase().includes(q));
    }
    return files;
  }, [fileTree, layerFilter, searchQuery]);

  const { nodes: layoutedNodes, edges: layoutedEdges } = useMemo(() => {
    if (viewMode === 'files' && hasSymbols) return buildGraph(filteredSymbols, 'files');
    if (viewMode === 'classes' && hasSymbols) return buildGraph(filteredSymbols, 'classes');
    if (viewMode === 'directories') return buildGraphFromFileTree(filteredFileTree, 'directory');
    if (viewMode === 'layers') return buildGraphFromFileTree(filteredFileTree, 'layer');
    // Fallback to file tree
    return buildGraphFromFileTree(filteredFileTree, 'layer');
  }, [filteredSymbols, filteredFileTree, viewMode, hasSymbols]);

  const [nodes, setNodes, onNodesChange] = useNodesState(layoutedNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(layoutedEdges);

  useEffect(() => {
    setNodes(layoutedNodes);
    setEdges(layoutedEdges);
  }, [layoutedNodes, layoutedEdges, setNodes, setEdges]);

  // Compute layer stats from whichever data source is available
  const layerStats = useMemo(() => {
    const stats = new Map<string, number>();
    const seen = new Set<string>();

    // Prefer symbols, fall back to fileTree
    const sourceFiles = symbols.length > 0
      ? symbols.map(s => s.file_path)
      : (fileTree || []).map(f => f.path);

    for (const fp of sourceFiles) {
      if (!fp || seen.has(fp)) continue;
      seen.add(fp);
      const layer = detectLayer(fp);
      stats.set(layer, (stats.get(layer) || 0) + 1);
    }
    return Array.from(stats.entries()).sort((a, b) => b[1] - a[1]);
  }, [symbols, fileTree]);

  const onNodeClick: NodeMouseHandler = useCallback((_event, node) => {
    // Find the symbol for this node
    const sym = symbols.find(s => {
      if (viewMode === 'files') return s.file_path === node.id;
      return (s.fqn || s.name) === node.id;
    });
    setSelectedSymbol(sym || null);
  }, [symbols, viewMode]);

  if (symbols.length === 0 && (fileTree || []).length === 0) {
    return (
      <div className="flex items-center justify-center h-64 text-gray-400">
        <div className="text-center">
          <p className="text-sm">No files found.</p>
          <p className="text-xs mt-1">Make sure the repository has a valid local path.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="relative" style={{ height: 600 }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onNodeClick={onNodeClick}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        nodesDraggable={true}
        nodesConnectable={false}
        minZoom={0.1}
        maxZoom={3}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={20} size={1} color="#f1f5f9" />
        <Controls position="bottom-left" />
        <MiniMap
          nodeColor={(node) => {
            // Extract layer from node style border color
            for (const [, colors] of Object.entries(LAYER_COLORS)) {
              if (node.style?.border?.toString().includes(colors.border)) return colors.minimap;
            }
            return '#9ca3af';
          }}
          maskColor="rgba(255,255,255,0.7)"
          position="bottom-right"
        />

        {/* Controls panel */}
        <Panel position="top-left">
          <div className="bg-white/95 backdrop-blur rounded-lg border border-gray-200 shadow-sm p-3 space-y-3" style={{ maxWidth: 260 }}>
            {/* Search */}
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search files, classes..."
              className="w-full px-2.5 py-1.5 border border-gray-200 rounded-md text-xs focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500"
            />

            {/* View mode toggle */}
            <div className="flex gap-1 flex-wrap">
              <button
                onClick={() => setViewMode('layers')}
                className={`px-2 py-1 text-[10px] font-medium rounded transition-colors ${
                  viewMode === 'layers' ? 'bg-indigo-100 text-indigo-700' : 'bg-gray-50 text-gray-600 hover:bg-gray-100'
                }`}
              >
                Layers
              </button>
              <button
                onClick={() => setViewMode('directories')}
                className={`px-2 py-1 text-[10px] font-medium rounded transition-colors ${
                  viewMode === 'directories' ? 'bg-indigo-100 text-indigo-700' : 'bg-gray-50 text-gray-600 hover:bg-gray-100'
                }`}
              >
                Directories
              </button>
              {hasSymbols && (
                <>
                  <button
                    onClick={() => setViewMode('files')}
                    className={`px-2 py-1 text-[10px] font-medium rounded transition-colors ${
                      viewMode === 'files' ? 'bg-indigo-100 text-indigo-700' : 'bg-gray-50 text-gray-600 hover:bg-gray-100'
                    }`}
                  >
                    Files
                  </button>
                  <button
                    onClick={() => setViewMode('classes')}
                    className={`px-2 py-1 text-[10px] font-medium rounded transition-colors ${
                      viewMode === 'classes' ? 'bg-indigo-100 text-indigo-700' : 'bg-gray-50 text-gray-600 hover:bg-gray-100'
                    }`}
                  >
                    Classes
                  </button>
                </>
              )}
            </div>

            {/* Layer legend + filter */}
            <div>
              <p className="text-[10px] font-medium text-gray-500 mb-1.5">Layers (click to filter)</p>
              <div className="flex flex-wrap gap-1">
                {layerStats.map(([layer, count]) => {
                  const colors = LAYER_COLORS[layer] || LAYER_COLORS['Other'];
                  const isActive = layerFilter === layer;
                  return (
                    <button
                      key={layer}
                      onClick={() => setLayerFilter(isActive ? null : layer)}
                      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[9px] font-medium transition-colors ${
                        isActive
                          ? 'ring-2 ring-offset-1'
                          : 'opacity-80 hover:opacity-100'
                      }`}
                      style={{
                        background: colors.bg,
                        color: colors.text,
                        borderColor: colors.border,
                        ...(isActive ? { ringColor: colors.border } : {}),
                      }}
                    >
                      <span className="w-2 h-2 rounded-full" style={{ background: colors.border }} />
                      {layer} ({count})
                    </button>
                  );
                })}
                {layerFilter && (
                  <button
                    onClick={() => setLayerFilter(null)}
                    className="text-[9px] text-gray-400 hover:text-gray-600 ml-1"
                  >
                    Clear
                  </button>
                )}
              </div>
            </div>

            {/* Stats */}
            <div className="text-[10px] text-gray-400">
              {nodes.length} nodes · {edges.length} edges
            </div>
          </div>
        </Panel>
      </ReactFlow>

      {/* Detail panel */}
      {selectedSymbol && (
        <DetailPanel
          symbol={selectedSymbol}
          symbols={symbols}
          onClose={() => setSelectedSymbol(null)}
        />
      )}
    </div>
  );
}
