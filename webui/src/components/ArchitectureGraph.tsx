'use client';

import { useMemo, useState, useCallback } from 'react';

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
}

// ---------------------------------------------------------------------------
// Layer detection
// ---------------------------------------------------------------------------

const LAYER_RULES: { pattern: RegExp; layer: string }[] = [
  { pattern: /\/(controller|resource|endpoint|rest|api|handler|route)\//i, layer: 'API' },
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
  { pattern: /\/(util|utils|helper|helpers|common|shared|lib)\//i, layer: 'Utility' },
  { pattern: /\/(middleware|filter|interceptor|aspect)\//i, layer: 'Middleware' },
  { pattern: /\/(client|remote|proxy|feign|integration)\//i, layer: 'External' },
  { pattern: /Client\.(java|ts|py)$/i, layer: 'External' },
];

const LAYER_COLORS: Record<string, { bg: string; border: string; text: string; light: string }> = {
  'API':        { bg: '#dbeafe', border: '#3b82f6', text: '#1e40af', light: '#eff6ff' },
  'Service':    { bg: '#d1fae5', border: '#10b981', text: '#065f46', light: '#ecfdf5' },
  'Data':       { bg: '#fef3c7', border: '#f59e0b', text: '#92400e', light: '#fffbeb' },
  'Model':      { bg: '#ede9fe', border: '#8b5cf6', text: '#5b21b6', light: '#f5f3ff' },
  'Config':     { bg: '#f3f4f6', border: '#6b7280', text: '#374151', light: '#f9fafb' },
  'Test':       { bg: '#fce7f3', border: '#ec4899', text: '#9d174d', light: '#fdf2f8' },
  'Utility':    { bg: '#e0e7ff', border: '#6366f1', text: '#3730a3', light: '#eef2ff' },
  'Middleware': { bg: '#ffedd5', border: '#f97316', text: '#9a3412', light: '#fff7ed' },
  'External':   { bg: '#fecdd3', border: '#ef4444', text: '#991b1b', light: '#fef2f2' },
  'Other':      { bg: '#f9fafb', border: '#d1d5db', text: '#6b7280', light: '#f9fafb' },
};

function detectLayer(filePath: string): string {
  for (const rule of LAYER_RULES) {
    if (rule.pattern.test(filePath)) return rule.layer;
  }
  return 'Other';
}

function formatSize(bytes: number): string {
  if (bytes > 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  if (bytes > 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${bytes} B`;
}

// ---------------------------------------------------------------------------
// Layer Card Component
// ---------------------------------------------------------------------------

function LayerCard({
  layer,
  files,
  isSelected,
  onClick,
  onDrillDown,
}: {
  layer: string;
  files: FileTreeEntry[];
  isSelected: boolean;
  onClick: () => void;
  onDrillDown: () => void;
}) {
  const colors = LAYER_COLORS[layer] || LAYER_COLORS['Other'];
  const dirs = new Set(files.map(f => f.directory || '(root)'));
  const totalSize = files.reduce((s, f) => s + f.size, 0);
  const sourceFiles = files.filter(f => f.file_type === 'source');

  return (
    <div
      onClick={onClick}
      className={`rounded-xl border-2 p-4 cursor-pointer transition-all hover:shadow-lg ${
        isSelected ? 'ring-2 ring-offset-2 shadow-lg scale-[1.02]' : 'hover:scale-[1.01]'
      }`}
      style={{
        borderColor: colors.border,
        background: isSelected ? colors.bg : colors.light,
      }}
    >
      <div className="flex items-start justify-between mb-2">
        <h3 className="text-base font-bold" style={{ color: colors.text }}>{layer}</h3>
        <span
          className="text-[10px] font-medium px-2 py-0.5 rounded-full"
          style={{ background: colors.bg, color: colors.text }}
        >
          {files.length} files
        </span>
      </div>
      <div className="text-xs text-gray-500 space-y-0.5">
        <div>{dirs.size} directories · {formatSize(totalSize)}</div>
        <div className="text-[10px] text-gray-400 line-clamp-1">
          {sourceFiles.slice(0, 3).map(f => f.name).join(', ')}
          {sourceFiles.length > 3 ? `, +${sourceFiles.length - 3}` : ''}
        </div>
      </div>
      <button
        onClick={(e) => { e.stopPropagation(); onDrillDown(); }}
        className="mt-3 w-full text-xs font-medium py-1.5 rounded-lg transition-colors"
        style={{ background: colors.bg, color: colors.text, border: `1px solid ${colors.border}` }}
      >
        Explore {layer} →
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// File List Component (drill-down view)
// ---------------------------------------------------------------------------

function FileExplorer({
  layer,
  files,
  onBack,
}: {
  layer: string;
  files: FileTreeEntry[];
  onBack: () => void;
}) {
  const [expandedDir, setExpandedDir] = useState<string | null>(null);
  const [sortBy, setSortBy] = useState<'name' | 'size'>('name');
  const colors = LAYER_COLORS[layer] || LAYER_COLORS['Other'];

  // Group by directory
  const dirMap = new Map<string, FileTreeEntry[]>();
  for (const f of files) {
    const dir = f.directory || '(root)';
    const existing = dirMap.get(dir) || [];
    existing.push(f);
    dirMap.set(dir, existing);
  }

  const sortedDirs = Array.from(dirMap.entries()).sort((a, b) => {
    if (sortBy === 'size') return b[1].reduce((s, f) => s + f.size, 0) - a[1].reduce((s, f) => s + f.size, 0);
    return a[0].localeCompare(b[0]);
  });

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <button
            onClick={onBack}
            className="flex items-center gap-1 text-sm text-gray-500 hover:text-gray-700"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
            Back
          </button>
          <span className="text-gray-300">|</span>
          <h3 className="text-sm font-bold" style={{ color: colors.text }}>
            {layer} Layer
          </h3>
          <span className="text-xs text-gray-400">{files.length} files in {dirMap.size} directories</span>
        </div>
        <div className="flex gap-1">
          <button
            onClick={() => setSortBy('name')}
            className={`px-2 py-0.5 text-[10px] rounded ${sortBy === 'name' ? 'bg-gray-200 text-gray-800' : 'text-gray-500'}`}
          >
            Name
          </button>
          <button
            onClick={() => setSortBy('size')}
            className={`px-2 py-0.5 text-[10px] rounded ${sortBy === 'size' ? 'bg-gray-200 text-gray-800' : 'text-gray-500'}`}
          >
            Size
          </button>
        </div>
      </div>

      {/* Directory tree */}
      <div className="space-y-1 max-h-[450px] overflow-y-auto">
        {sortedDirs.map(([dir, dirFiles]) => {
          const isExpanded = expandedDir === dir;
          const dirSize = dirFiles.reduce((s, f) => s + f.size, 0);
          const sortedFiles = [...dirFiles].sort((a, b) =>
            sortBy === 'size' ? b.size - a.size : a.name.localeCompare(b.name)
          );

          return (
            <div key={dir}>
              <button
                onClick={() => setExpandedDir(isExpanded ? null : dir)}
                className="w-full flex items-center gap-2 px-3 py-2 rounded-lg hover:bg-gray-50 transition-colors text-left"
              >
                <svg className={`w-3.5 h-3.5 text-gray-400 transition-transform ${isExpanded ? 'rotate-90' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
                <svg className="w-4 h-4 text-yellow-500" fill="currentColor" viewBox="0 0 20 20">
                  <path d="M2 6a2 2 0 012-2h5l2 2h5a2 2 0 012 2v6a2 2 0 01-2 2H4a2 2 0 01-2-2V6z" />
                </svg>
                <span className="text-xs font-medium text-gray-700 flex-1 truncate">{dir}</span>
                <span className="text-[10px] text-gray-400">{dirFiles.length} files · {formatSize(dirSize)}</span>
              </button>

              {isExpanded && (
                <div className="ml-10 border-l border-gray-200 pl-3 py-1 space-y-0.5">
                  {sortedFiles.map((f, i) => {
                    const ext = f.extension;
                    const extColor = ext === '.java' ? 'text-red-500' : ext === '.py' ? 'text-green-500' :
                      ext === '.ts' || ext === '.tsx' ? 'text-blue-500' : ext === '.xml' || ext === '.yml' ? 'text-purple-500' : 'text-gray-400';
                    return (
                      <div key={i} className="flex items-center gap-2 py-1 px-2 rounded hover:bg-gray-50 text-xs">
                        <span className={`font-mono text-[10px] w-10 text-right ${extColor}`}>{ext}</span>
                        <span className="text-gray-700 flex-1 truncate font-mono">{f.name}</span>
                        <span className="text-[10px] text-gray-400">{formatSize(f.size)}</span>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Architecture flow arrows (SVG)
// ---------------------------------------------------------------------------

function FlowArrows({ layers }: { layers: string[] }) {
  const order = ['API', 'Middleware', 'Service', 'Data', 'External'];
  const present = order.filter(l => layers.includes(l));
  if (present.length < 2) return null;

  return (
    <div className="flex items-center justify-center gap-1 py-3">
      {present.map((layer, i) => {
        const colors = LAYER_COLORS[layer] || LAYER_COLORS['Other'];
        return (
          <div key={layer} className="flex items-center gap-1">
            <span
              className="text-[10px] font-bold px-2 py-0.5 rounded-full"
              style={{ background: colors.bg, color: colors.text, border: `1px solid ${colors.border}` }}
            >
              {layer}
            </span>
            {i < present.length - 1 && (
              <svg className="w-5 h-3 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 20 12">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M1 6h16m0 0l-4-4m4 4l-4 4" />
              </svg>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export default function ArchitectureGraph({ repoId, symbols, fileTree }: ArchitectureGraphProps) {
  const files = fileTree || [];
  const [selectedLayer, setSelectedLayer] = useState<string | null>(null);
  const [drillLayer, setDrillLayer] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');

  // Build layer data
  const layerData = useMemo(() => {
    const map = new Map<string, FileTreeEntry[]>();
    for (const f of files) {
      if (f.file_type !== 'source') continue;
      const layer = detectLayer(f.path);
      const existing = map.get(layer) || [];
      existing.push(f);
      map.set(layer, existing);
    }
    // Sort by file count descending
    return Array.from(map.entries()).sort((a, b) => b[1].length - a[1].length);
  }, [files]);

  const filteredLayerData = useMemo(() => {
    if (!searchQuery) return layerData;
    const q = searchQuery.toLowerCase();
    return layerData
      .map(([layer, files]) => [layer, files.filter(f => f.name.toLowerCase().includes(q) || f.path.toLowerCase().includes(q))] as [string, FileTreeEntry[]])
      .filter(([, files]) => files.length > 0);
  }, [layerData, searchQuery]);

  const allLayers = layerData.map(([l]) => l);
  const totalFiles = files.filter(f => f.file_type === 'source').length;

  if (files.length === 0) {
    return (
      <div className="flex items-center justify-center h-48 text-gray-400">
        <div className="text-center">
          <p className="text-sm">No files found.</p>
          <p className="text-xs mt-1">Make sure the repository has a valid local path.</p>
        </div>
      </div>
    );
  }

  // Drill-down view
  if (drillLayer) {
    const drillFiles = layerData.find(([l]) => l === drillLayer)?.[1] || [];
    const filtered = searchQuery
      ? drillFiles.filter(f => f.name.toLowerCase().includes(searchQuery.toLowerCase()) || f.path.toLowerCase().includes(searchQuery.toLowerCase()))
      : drillFiles;

    return (
      <div>
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search files..."
          className="w-full px-3 py-2 border border-gray-200 rounded-lg text-sm mb-4 focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500"
        />
        <FileExplorer
          layer={drillLayer}
          files={filtered}
          onBack={() => { setDrillLayer(null); setSearchQuery(''); }}
        />
      </div>
    );
  }

  // Layer overview
  return (
    <div>
      {/* Search + stats */}
      <div className="flex items-center gap-4 mb-4">
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search files, classes..."
          className="flex-1 px-3 py-2 border border-gray-200 rounded-lg text-sm focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500"
        />
        <span className="text-xs text-gray-400 flex-shrink-0">
          {totalFiles} source files · {allLayers.length} layers
        </span>
      </div>

      {/* Architectural flow */}
      <FlowArrows layers={allLayers} />

      {/* Layer grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 mt-4">
        {filteredLayerData.map(([layer, layerFiles]) => (
          <LayerCard
            key={layer}
            layer={layer}
            files={layerFiles}
            isSelected={selectedLayer === layer}
            onClick={() => setSelectedLayer(selectedLayer === layer ? null : layer)}
            onDrillDown={() => { setDrillLayer(layer); setSearchQuery(''); }}
          />
        ))}
      </div>

      {/* Selected layer detail */}
      {selectedLayer && (
        <div className="mt-4 rounded-xl border border-gray-200 bg-gray-50 p-4">
          <div className="flex items-center justify-between mb-3">
            <h4 className="text-sm font-semibold text-gray-700">
              {selectedLayer} — Top Files
            </h4>
            <button
              onClick={() => setDrillLayer(selectedLayer)}
              className="text-xs text-indigo-600 hover:text-indigo-800 font-medium"
            >
              See all →
            </button>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
            {(layerData.find(([l]) => l === selectedLayer)?.[1] || [])
              .sort((a, b) => b.size - a.size)
              .slice(0, 9)
              .map((f, i) => {
                const colors = LAYER_COLORS[selectedLayer] || LAYER_COLORS['Other'];
                return (
                  <div
                    key={i}
                    className="flex items-center gap-2 px-3 py-2 bg-white rounded-lg border border-gray-100 text-xs"
                  >
                    <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: colors.border }} />
                    <span className="font-mono text-gray-700 truncate flex-1">{f.name}</span>
                    <span className="text-[10px] text-gray-400">{formatSize(f.size)}</span>
                  </div>
                );
              })}
          </div>
        </div>
      )}
    </div>
  );
}
