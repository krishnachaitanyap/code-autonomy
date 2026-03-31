'use client';

import { useMemo, useState } from 'react';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Symbol { fqn: string; name: string; file_path: string; symbol_type: string; line_start: number; line_end: number; signature: string; parent_class: string; }
interface FileTreeEntry { path: string; name: string; directory: string; extension: string; file_type: string; size: number; }
interface ArchitectureGraphProps { repoId: string; symbols: Symbol[]; fileTree?: FileTreeEntry[]; }

// ---------------------------------------------------------------------------
// Layer detection & colors
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
  { pattern: /\.spec\.(ts|js|tsx|jsx)$/i, layer: 'Test' },
  { pattern: /\/(util|utils|helper|helpers|common|shared|lib)\//i, layer: 'Utility' },
  { pattern: /\/(middleware|filter|interceptor|aspect)\//i, layer: 'Middleware' },
  { pattern: /\/(client|remote|proxy|feign|integration)\//i, layer: 'External' },
  { pattern: /Client\.(java|ts|py)$/i, layer: 'External' },
];

interface LayerTheme { gradient: string; border: string; text: string; icon: string; badge: string; bar: string; glow: string; }

const LAYER_THEME: Record<string, LayerTheme> = {
  'API':        { gradient: 'from-blue-500 to-blue-600',     border: 'border-blue-200',     text: 'text-blue-700',     icon: '\uD83C\uDF10', badge: 'bg-blue-100 text-blue-700',       bar: 'bg-blue-500',     glow: 'shadow-blue-200' },
  'Service':    { gradient: 'from-emerald-500 to-emerald-600', border: 'border-emerald-200', text: 'text-emerald-700', icon: '\u2699\uFE0F',  badge: 'bg-emerald-100 text-emerald-700', bar: 'bg-emerald-500', glow: 'shadow-emerald-200' },
  'Data':       { gradient: 'from-amber-500 to-amber-600',   border: 'border-amber-200',    text: 'text-amber-700',   icon: '\uD83D\uDDC3\uFE0F', badge: 'bg-amber-100 text-amber-700', bar: 'bg-amber-500', glow: 'shadow-amber-200' },
  'Model':      { gradient: 'from-violet-500 to-violet-600', border: 'border-violet-200',   text: 'text-violet-700',  icon: '\uD83D\uDCD0', badge: 'bg-violet-100 text-violet-700',   bar: 'bg-violet-500', glow: 'shadow-violet-200' },
  'Config':     { gradient: 'from-gray-500 to-gray-600',     border: 'border-gray-200',     text: 'text-gray-700',    icon: '\u2699\uFE0F', badge: 'bg-gray-100 text-gray-700',       bar: 'bg-gray-500',   glow: 'shadow-gray-200' },
  'Test':       { gradient: 'from-pink-500 to-pink-600',     border: 'border-pink-200',     text: 'text-pink-700',    icon: '\uD83E\uDDEA', badge: 'bg-pink-100 text-pink-700',       bar: 'bg-pink-500',   glow: 'shadow-pink-200' },
  'Utility':    { gradient: 'from-indigo-500 to-indigo-600', border: 'border-indigo-200',   text: 'text-indigo-700',  icon: '\uD83D\uDD27', badge: 'bg-indigo-100 text-indigo-700',   bar: 'bg-indigo-500', glow: 'shadow-indigo-200' },
  'Middleware': { gradient: 'from-orange-500 to-orange-600', border: 'border-orange-200',   text: 'text-orange-700',  icon: '\uD83D\uDEE1\uFE0F', badge: 'bg-orange-100 text-orange-700', bar: 'bg-orange-500', glow: 'shadow-orange-200' },
  'External':   { gradient: 'from-red-500 to-red-600',       border: 'border-red-200',      text: 'text-red-700',     icon: '\u2601\uFE0F',  badge: 'bg-red-100 text-red-700',         bar: 'bg-red-500',    glow: 'shadow-red-200' },
  'Other':      { gradient: 'from-slate-400 to-slate-500',   border: 'border-slate-200',    text: 'text-slate-600',   icon: '\uD83D\uDCC4', badge: 'bg-slate-100 text-slate-600',     bar: 'bg-slate-400',  glow: 'shadow-slate-200' },
};

const EXT_ICONS: Record<string, { icon: string; color: string }> = {
  '.java':  { icon: '\u2615', color: 'text-red-500' },
  '.py':    { icon: '\uD83D\uDC0D', color: 'text-green-500' },
  '.ts':    { icon: 'TS', color: 'text-blue-600' },
  '.tsx':   { icon: 'TX', color: 'text-blue-500' },
  '.js':    { icon: 'JS', color: 'text-yellow-500' },
  '.jsx':   { icon: 'JX', color: 'text-yellow-500' },
  '.go':    { icon: 'Go', color: 'text-cyan-500' },
  '.xml':   { icon: '\u2702\uFE0F', color: 'text-orange-500' },
  '.yml':   { icon: 'Y', color: 'text-purple-500' },
  '.yaml':  { icon: 'Y', color: 'text-purple-500' },
  '.json':  { icon: '{}', color: 'text-gray-500' },
  '.sql':   { icon: 'DB', color: 'text-blue-400' },
  '.properties': { icon: '#', color: 'text-gray-400' },
};

function detectLayer(p: string): string { for (const r of LAYER_RULES) { if (r.pattern.test(p)) return r.layer; } return 'Other'; }
function fmt(b: number): string { return b > 1048576 ? `${(b/1048576).toFixed(1)}M` : b > 1024 ? `${(b/1024).toFixed(0)}K` : `${b}B`; }
function getTheme(l: string): LayerTheme { return LAYER_THEME[l] || LAYER_THEME['Other']; }

// ---------------------------------------------------------------------------
// Vertical Architecture Diagram — the hero visualization
// ---------------------------------------------------------------------------

function ArchDiagram({ layers, onSelect }: { layers: [string, FileTreeEntry[]][]; onSelect: (l: string) => void }) {
  const flowOrder = ['API', 'Middleware', 'Service', 'Data', 'External'];
  const mainFlow = flowOrder.filter(l => layers.some(([n]) => n === l));
  const side = layers.filter(([n]) => !flowOrder.includes(n)).map(([n]) => n);

  return (
    <div className="flex gap-6 justify-center py-2">
      {/* Main vertical flow */}
      <div className="flex flex-col items-center">
        {/* Client entry */}
        <div className="flex items-center gap-2 mb-2">
          <div className="w-8 h-8 rounded-full bg-gray-800 text-white flex items-center justify-center text-[10px] font-bold">IN</div>
          <span className="text-[10px] text-gray-400 font-medium">Incoming Requests</span>
        </div>

        {mainFlow.map((layer, i) => {
          const t = getTheme(layer);
          const files = layers.find(([n]) => n === layer)?.[1] || [];
          const dirs = new Set(files.map(f => f.directory));
          return (
            <div key={layer} className="flex flex-col items-center">
              {/* Arrow down */}
              {i > 0 && (
                <div className="flex flex-col items-center my-1">
                  <div className="w-0.5 h-4 bg-gradient-to-b from-gray-300 to-gray-400" />
                  <svg className="w-3 h-2 text-gray-400" viewBox="0 0 12 8" fill="currentColor"><path d="M6 8L0 0h12z"/></svg>
                </div>
              )}
              {/* Layer box */}
              <button
                onClick={() => onSelect(layer)}
                className={`group relative w-64 rounded-2xl border ${t.border} bg-white hover:${t.glow} hover:shadow-lg transition-all duration-200 overflow-hidden`}
              >
                {/* Gradient top bar */}
                <div className={`h-1.5 bg-gradient-to-r ${t.gradient}`} />
                <div className="px-4 py-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="text-lg">{t.icon}</span>
                      <span className={`font-bold text-sm ${t.text}`}>{layer}</span>
                    </div>
                    <span className={`text-[10px] font-semibold px-2 py-0.5 rounded-full ${t.badge}`}>
                      {files.length}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 mt-1.5 text-[10px] text-gray-400">
                    <span>{dirs.size} dirs</span>
                    <span>{fmt(files.reduce((s, f) => s + f.size, 0))}</span>
                  </div>
                  {/* Mini file preview */}
                  <div className="mt-2 flex flex-wrap gap-1">
                    {files.slice(0, 5).map((f, j) => (
                      <span key={j} className="text-[9px] px-1.5 py-0.5 rounded bg-gray-50 text-gray-500 font-mono truncate max-w-[100px]">
                        {f.name}
                      </span>
                    ))}
                    {files.length > 5 && <span className="text-[9px] text-gray-400 self-center">+{files.length - 5}</span>}
                  </div>
                </div>
                {/* Hover indicator */}
                <div className={`absolute inset-y-0 right-0 w-1 bg-gradient-to-b ${t.gradient} opacity-0 group-hover:opacity-100 transition-opacity rounded-r-2xl`} />
              </button>
            </div>
          );
        })}

        {/* Terminal */}
        {mainFlow.length > 0 && (
          <div className="flex flex-col items-center mt-1">
            <div className="w-0.5 h-4 bg-gradient-to-b from-gray-300 to-gray-400" />
            <svg className="w-3 h-2 text-gray-400" viewBox="0 0 12 8" fill="currentColor"><path d="M6 8L0 0h12z"/></svg>
            <div className="w-8 h-8 rounded-full bg-gray-200 text-gray-500 flex items-center justify-center text-[10px] font-bold mt-1">DB</div>
          </div>
        )}
      </div>

      {/* Side layers (supporting) */}
      {side.length > 0 && (
        <div className="flex flex-col gap-3 justify-center">
          <span className="text-[9px] text-gray-400 font-semibold uppercase tracking-widest text-center mb-1">Supporting</span>
          {side.map(layer => {
            const t = getTheme(layer);
            const files = layers.find(([n]) => n === layer)?.[1] || [];
            return (
              <button
                key={layer}
                onClick={() => onSelect(layer)}
                className={`group relative w-44 rounded-xl border ${t.border} bg-white hover:shadow-md transition-all duration-200 overflow-hidden`}
              >
                <div className={`h-1 bg-gradient-to-r ${t.gradient}`} />
                <div className="px-3 py-2">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5">
                      <span className="text-sm">{t.icon}</span>
                      <span className={`font-semibold text-xs ${t.text}`}>{layer}</span>
                    </div>
                    <span className={`text-[9px] font-semibold px-1.5 py-0.5 rounded-full ${t.badge}`}>{files.length}</span>
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stats Bar
// ---------------------------------------------------------------------------

function StatsBar({ layers, totalFiles, totalSize }: { layers: [string, FileTreeEntry[]][]; totalFiles: number; totalSize: number }) {
  const maxFiles = Math.max(...layers.map(([, f]) => f.length), 1);

  return (
    <div className="flex items-end gap-1 h-16 px-2">
      {layers.map(([layer, files]) => {
        const t = getTheme(layer);
        const pct = (files.length / maxFiles) * 100;
        return (
          <div key={layer} className="flex-1 flex flex-col items-center gap-1 group" title={`${layer}: ${files.length} files`}>
            <span className="text-[8px] text-gray-400 opacity-0 group-hover:opacity-100 transition-opacity">{files.length}</span>
            <div className="w-full rounded-t-md transition-all duration-500" style={{ height: `${Math.max(pct, 8)}%` }}>
              <div className={`w-full h-full rounded-t-md ${t.bar} opacity-80 group-hover:opacity-100 transition-opacity`} />
            </div>
            <span className={`text-[8px] font-medium ${t.text} truncate w-full text-center`}>{layer}</span>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// File Explorer (drill-down)
// ---------------------------------------------------------------------------

function FileExplorer({ layer, files, onBack }: { layer: string; files: FileTreeEntry[]; onBack: () => void }) {
  const [expandedDirs, setExpandedDirs] = useState<Set<string>>(new Set());
  const [sortBy, setSortBy] = useState<'name' | 'size'>('name');
  const [fileSearch, setFileSearch] = useState('');
  const t = getTheme(layer);

  const filtered = fileSearch
    ? files.filter(f => f.name.toLowerCase().includes(fileSearch.toLowerCase()) || f.path.toLowerCase().includes(fileSearch.toLowerCase()))
    : files;

  const dirMap = new Map<string, FileTreeEntry[]>();
  for (const f of filtered) { const d = f.directory || '(root)'; dirMap.set(d, [...(dirMap.get(d) || []), f]); }

  const sortedDirs = Array.from(dirMap.entries()).sort((a, b) =>
    sortBy === 'size' ? b[1].reduce((s, f) => s + f.size, 0) - a[1].reduce((s, f) => s + f.size, 0) : a[0].localeCompare(b[0])
  );

  const toggleDir = (d: string) => {
    setExpandedDirs(prev => { const n = new Set(prev); n.has(d) ? n.delete(d) : n.add(d); return n; });
  };

  const expandAll = () => setExpandedDirs(new Set(sortedDirs.map(([d]) => d)));
  const collapseAll = () => setExpandedDirs(new Set());

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button onClick={onBack} className="p-1.5 rounded-lg bg-gray-100 hover:bg-gray-200 transition-colors">
            <svg className="w-4 h-4 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>
          <div>
            <div className="flex items-center gap-2">
              <span className="text-lg">{t.icon}</span>
              <h3 className={`text-base font-bold ${t.text}`}>{layer} Layer</h3>
            </div>
            <p className="text-[11px] text-gray-400">{files.length} files in {dirMap.size} directories · {fmt(files.reduce((s, f) => s + f.size, 0))}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={expandAll} className="text-[10px] text-gray-400 hover:text-gray-600">Expand all</button>
          <span className="text-gray-200">|</span>
          <button onClick={collapseAll} className="text-[10px] text-gray-400 hover:text-gray-600">Collapse</button>
          <span className="text-gray-200">|</span>
          <div className="flex bg-gray-100 rounded-md p-0.5">
            {(['name', 'size'] as const).map(s => (
              <button key={s} onClick={() => setSortBy(s)}
                className={`px-2 py-0.5 text-[10px] rounded font-medium transition-colors ${sortBy === s ? 'bg-white shadow-sm text-gray-800' : 'text-gray-500'}`}
              >{s === 'name' ? 'A-Z' : 'Size'}</button>
            ))}
          </div>
        </div>
      </div>

      {/* Search within layer */}
      <div className="relative">
        <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
        <input
          type="text" value={fileSearch} onChange={e => setFileSearch(e.target.value)}
          placeholder={`Search in ${layer}...`}
          className="w-full pl-9 pr-3 py-2 border border-gray-200 rounded-xl text-sm focus:ring-2 focus:ring-indigo-200 focus:border-indigo-400 transition-all"
        />
      </div>

      {/* Directory tree */}
      <div className="rounded-xl border border-gray-200 overflow-hidden">
        <div className="max-h-[500px] overflow-y-auto divide-y divide-gray-100">
          {sortedDirs.map(([dir, dirFiles]) => {
            const isOpen = expandedDirs.has(dir);
            const dirSize = dirFiles.reduce((s, f) => s + f.size, 0);
            const sorted = [...dirFiles].sort((a, b) => sortBy === 'size' ? b.size - a.size : a.name.localeCompare(b.name));

            return (
              <div key={dir}>
                <button onClick={() => toggleDir(dir)}
                  className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-gray-50/80 transition-colors text-left group"
                >
                  <svg className={`w-3 h-3 text-gray-400 transition-transform duration-200 ${isOpen ? 'rotate-90' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M9 5l7 7-7 7" />
                  </svg>
                  <svg className={`w-4 h-4 ${isOpen ? 'text-yellow-500' : 'text-yellow-400'}`} fill="currentColor" viewBox="0 0 20 20">
                    <path d="M2 6a2 2 0 012-2h5l2 2h5a2 2 0 012 2v6a2 2 0 01-2 2H4a2 2 0 01-2-2V6z" />
                  </svg>
                  <span className="text-xs font-medium text-gray-700 flex-1 truncate">{dir}</span>
                  <span className="text-[10px] text-gray-400 font-mono">{dirFiles.length}</span>
                  <span className="text-[10px] text-gray-300 w-12 text-right font-mono">{fmt(dirSize)}</span>
                </button>
                {isOpen && (
                  <div className="bg-gray-50/50">
                    {sorted.map((f, i) => {
                      const ei = EXT_ICONS[f.extension] || { icon: '\uD83D\uDCC4', color: 'text-gray-400' };
                      const sizePct = Math.min((f.size / Math.max(...sorted.map(x => x.size), 1)) * 100, 100);
                      return (
                        <div key={i} className="flex items-center gap-3 pl-12 pr-4 py-1.5 hover:bg-white/80 transition-colors group/file">
                          <span className={`text-[10px] font-mono w-6 text-center ${ei.color}`}>{ei.icon}</span>
                          <span className="text-xs text-gray-700 font-mono truncate flex-1 group-hover/file:text-gray-900">{f.name}</span>
                          {/* Size bar */}
                          <div className="w-16 h-1.5 bg-gray-200 rounded-full overflow-hidden">
                            <div className={`h-full rounded-full ${t.bar} opacity-60`} style={{ width: `${sizePct}%` }} />
                          </div>
                          <span className="text-[10px] text-gray-400 font-mono w-10 text-right">{fmt(f.size)}</span>
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
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export default function ArchitectureGraph({ repoId, symbols, fileTree }: ArchitectureGraphProps) {
  const files = fileTree || [];
  const [drillLayer, setDrillLayer] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');

  const layerData = useMemo(() => {
    const map = new Map<string, FileTreeEntry[]>();
    for (const f of files) {
      if (f.file_type !== 'source') continue;
      const layer = detectLayer(f.path);
      map.set(layer, [...(map.get(layer) || []), f]);
    }
    return Array.from(map.entries()).sort((a, b) => b[1].length - a[1].length);
  }, [files]);

  const totalFiles = layerData.reduce((s, [, f]) => s + f.length, 0);
  const totalSize = layerData.reduce((s, [, f]) => s + f.reduce((ss, ff) => ss + ff.size, 0), 0);
  const totalDirs = new Set(files.filter(f => f.file_type === 'source').map(f => f.directory)).size;

  if (files.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-48 text-gray-400">
        <svg className="w-12 h-12 mb-3 text-gray-200" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
        </svg>
        <p className="text-sm font-medium">No source files found</p>
        <p className="text-xs mt-1">Make sure the repository has a valid local path</p>
      </div>
    );
  }

  // Drill-down view
  if (drillLayer) {
    const drillFiles = layerData.find(([l]) => l === drillLayer)?.[1] || [];
    return (
      <FileExplorer
        layer={drillLayer}
        files={drillFiles}
        onBack={() => setDrillLayer(null)}
      />
    );
  }

  return (
    <div className="space-y-6">
      {/* Summary stats */}
      <div className="grid grid-cols-4 gap-3">
        <div className="bg-gradient-to-br from-indigo-50 to-white rounded-xl border border-indigo-100 p-3 text-center">
          <div className="text-2xl font-bold text-indigo-700">{layerData.length}</div>
          <div className="text-[10px] text-indigo-400 font-medium uppercase tracking-wider mt-0.5">Layers</div>
        </div>
        <div className="bg-gradient-to-br from-emerald-50 to-white rounded-xl border border-emerald-100 p-3 text-center">
          <div className="text-2xl font-bold text-emerald-700">{totalFiles}</div>
          <div className="text-[10px] text-emerald-400 font-medium uppercase tracking-wider mt-0.5">Source Files</div>
        </div>
        <div className="bg-gradient-to-br from-amber-50 to-white rounded-xl border border-amber-100 p-3 text-center">
          <div className="text-2xl font-bold text-amber-700">{totalDirs}</div>
          <div className="text-[10px] text-amber-400 font-medium uppercase tracking-wider mt-0.5">Directories</div>
        </div>
        <div className="bg-gradient-to-br from-purple-50 to-white rounded-xl border border-purple-100 p-3 text-center">
          <div className="text-2xl font-bold text-purple-700">{fmt(totalSize)}</div>
          <div className="text-[10px] text-purple-400 font-medium uppercase tracking-wider mt-0.5">Total Size</div>
        </div>
      </div>

      {/* Layer distribution bar chart */}
      <div className="bg-white rounded-xl border border-gray-200 p-4">
        <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">Layer Distribution</h4>
        <StatsBar layers={layerData} totalFiles={totalFiles} totalSize={totalSize} />
      </div>

      {/* Two-column: Diagram + Details */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        {/* Left: Architecture Diagram */}
        <div className="lg:col-span-3 bg-gradient-to-b from-gray-50/80 to-white rounded-xl border border-gray-200 p-6">
          <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-4">Architecture Flow</h4>
          <ArchDiagram layers={layerData} onSelect={setDrillLayer} />
        </div>

        {/* Right: Layer list */}
        <div className="lg:col-span-2 space-y-2">
          <h4 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">All Layers</h4>
          {layerData.map(([layer, layerFiles]) => {
            const t = getTheme(layer);
            const pct = Math.round((layerFiles.length / totalFiles) * 100);
            return (
              <button
                key={layer}
                onClick={() => setDrillLayer(layer)}
                className={`w-full flex items-center gap-3 px-4 py-3 rounded-xl border ${t.border} bg-white hover:shadow-md transition-all group text-left`}
              >
                <span className="text-xl">{t.icon}</span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between">
                    <span className={`text-sm font-semibold ${t.text}`}>{layer}</span>
                    <span className={`text-[10px] font-bold ${t.text}`}>{pct}%</span>
                  </div>
                  <div className="mt-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
                    <div className={`h-full rounded-full ${t.bar} transition-all duration-700`} style={{ width: `${pct}%` }} />
                  </div>
                  <div className="flex items-center gap-2 mt-1 text-[10px] text-gray-400">
                    <span>{layerFiles.length} files</span>
                    <span className="text-gray-200">·</span>
                    <span>{fmt(layerFiles.reduce((s, f) => s + f.size, 0))}</span>
                  </div>
                </div>
                <svg className="w-4 h-4 text-gray-300 group-hover:text-gray-500 transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
