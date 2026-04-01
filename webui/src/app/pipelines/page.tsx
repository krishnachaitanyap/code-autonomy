'use client';

import { useEffect, useRef, useState } from 'react';
import { tools, type CustomTool } from '@/lib/api';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface PipelineStep {
  id: string;
  tool_id: string;
  tool_name: string;
  tool_description: string;
  tool_type: string;
  parallel_group: number;
  input_mapping: Record<string, string>;
  output_keys: string[];
  config: Record<string, string>;
}

interface Pipeline {
  id: string;
  name: string;
  description: string;
  steps: PipelineStep[];
}

const TOOL_TYPE_THEME: Record<string, { icon: string; color: string; bg: string; border: string }> = {
  analyzer:    { icon: '\uD83D\uDD0D', color: 'text-purple-700',  bg: 'bg-purple-50',  border: 'border-purple-300' },
  agent:       { icon: '\uD83E\uDD16', color: 'text-blue-700',    bg: 'bg-blue-50',    border: 'border-blue-300' },
  transformer: { icon: '\u2699\uFE0F', color: 'text-emerald-700', bg: 'bg-emerald-50', border: 'border-emerald-300' },
  validator:   { icon: '\u2705',       color: 'text-green-700',   bg: 'bg-green-50',   border: 'border-green-300' },
};

function getToolTheme(type: string) { return TOOL_TYPE_THEME[type] || TOOL_TYPE_THEME.agent; }
function uid() { return `step-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`; }

// ---------------------------------------------------------------------------
// Visual Canvas — the pipeline flow visualization
// ---------------------------------------------------------------------------

function PipelineCanvas({
  steps,
  selectedStep,
  onSelectStep,
  onRemoveStep,
  onReorder,
  onToggleParallel,
}: {
  steps: PipelineStep[];
  selectedStep: string | null;
  onSelectStep: (id: string | null) => void;
  onRemoveStep: (id: string) => void;
  onReorder: (fromIdx: number, toIdx: number) => void;
  onToggleParallel: (id: string) => void;
}) {
  const [dragIdx, setDragIdx] = useState<number | null>(null);
  const [dragOverIdx, setDragOverIdx] = useState<number | null>(null);

  if (steps.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-gray-300 select-none">
        <svg className="w-16 h-16 mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M12 4v16m8-8H4" />
        </svg>
        <p className="text-sm font-medium text-gray-400">Drag tools here to build your pipeline</p>
        <p className="text-xs text-gray-300 mt-1">Or click a tool from the sidebar to add it</p>
      </div>
    );
  }

  // Group by parallel_group
  const groups: { group: number; steps: (PipelineStep & { originalIdx: number })[] }[] = [];
  steps.forEach((step, idx) => {
    const existing = groups.find(g => g.group === step.parallel_group);
    if (existing) {
      existing.steps.push({ ...step, originalIdx: idx });
    } else {
      groups.push({ group: step.parallel_group, steps: [{ ...step, originalIdx: idx }] });
    }
  });
  groups.sort((a, b) => a.group - b.group);

  return (
    <div className="flex flex-col items-center py-6 px-4 min-h-full">
      {/* Start node */}
      <div className="flex items-center gap-2 mb-2">
        <div className="w-10 h-10 rounded-full bg-gradient-to-br from-gray-700 to-gray-900 text-white flex items-center justify-center text-xs font-bold shadow-md">
          IN
        </div>
        <span className="text-[10px] text-gray-400 font-medium">Start</span>
      </div>
      <div className="w-0.5 h-6 bg-gradient-to-b from-gray-400 to-gray-300" />

      {groups.map((group, gi) => (
        <div key={gi} className="flex flex-col items-center w-full">
          {/* Parallel group container */}
          {group.steps.length > 1 && (
            <div className="text-[9px] font-semibold text-orange-500 uppercase tracking-wider mb-1 flex items-center gap-1">
              <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
              </svg>
              Parallel Group {group.group + 1}
            </div>
          )}

          <div className={`flex items-start justify-center gap-4 ${group.steps.length > 1 ? 'bg-orange-50/50 border border-dashed border-orange-200 rounded-2xl px-6 py-4' : ''}`}>
            {group.steps.map((step, si) => {
              const theme = getToolTheme(step.tool_type);
              const isSelected = selectedStep === step.id;
              const isDragging = dragIdx === step.originalIdx;
              const isDragOver = dragOverIdx === step.originalIdx;

              return (
                <div key={step.id} className="flex flex-col items-center">
                  {/* Step node */}
                  <div
                    draggable
                    onDragStart={() => setDragIdx(step.originalIdx)}
                    onDragEnd={() => { setDragIdx(null); setDragOverIdx(null); }}
                    onDragOver={(e) => { e.preventDefault(); setDragOverIdx(step.originalIdx); }}
                    onDrop={() => {
                      if (dragIdx !== null && dragIdx !== step.originalIdx) onReorder(dragIdx, step.originalIdx);
                      setDragIdx(null); setDragOverIdx(null);
                    }}
                    onClick={() => onSelectStep(isSelected ? null : step.id)}
                    className={`
                      relative group w-52 rounded-2xl border-2 bg-white transition-all duration-200 cursor-pointer select-none
                      ${isSelected ? `${theme.border} ring-2 ring-offset-2 shadow-lg scale-105` : `border-gray-200 hover:${theme.border} hover:shadow-md`}
                      ${isDragging ? 'opacity-40 scale-95' : ''}
                      ${isDragOver ? 'border-indigo-400 ring-2 ring-indigo-200' : ''}
                    `}
                  >
                    {/* Gradient top bar */}
                    <div className={`h-1.5 rounded-t-xl ${theme.bg}`} style={{ background: `linear-gradient(to right, var(--tw-gradient-stops))` }}>
                      <div className={`h-full rounded-t-xl ${theme.bg}`} />
                    </div>

                    <div className="px-4 py-3">
                      {/* Header */}
                      <div className="flex items-center justify-between mb-1">
                        <div className="flex items-center gap-2">
                          <span className="text-lg">{theme.icon}</span>
                          <div>
                            <h4 className={`text-sm font-bold ${theme.color} leading-tight`}>{step.tool_name}</h4>
                            <span className={`text-[9px] font-medium px-1.5 py-0.5 rounded-full ${theme.bg} ${theme.color}`}>
                              {step.tool_type}
                            </span>
                          </div>
                        </div>
                        <span className="text-[9px] text-gray-300 font-mono">#{step.originalIdx + 1}</span>
                      </div>

                      {/* Description */}
                      <p className="text-[10px] text-gray-500 line-clamp-2 mt-1">{step.tool_description}</p>

                      {/* Output keys */}
                      {step.output_keys.length > 0 && (
                        <div className="flex flex-wrap gap-1 mt-2">
                          {step.output_keys.map((k, ki) => (
                            <span key={ki} className="text-[8px] font-mono px-1.5 py-0.5 rounded bg-gray-100 text-gray-500">
                              {k}
                            </span>
                          ))}
                        </div>
                      )}

                      {/* Input mappings */}
                      {Object.keys(step.input_mapping).length > 0 && (
                        <div className="mt-2 space-y-0.5">
                          {Object.entries(step.input_mapping).map(([k, v]) => (
                            <div key={k} className="flex items-center gap-1 text-[8px]">
                              <span className="text-indigo-500 font-mono">{v}</span>
                              <span className="text-gray-300">{'\u2192'}</span>
                              <span className="text-gray-600 font-mono">{k}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>

                    {/* Action buttons (visible on hover) */}
                    <div className="absolute -top-2 -right-2 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button
                        onClick={(e) => { e.stopPropagation(); onToggleParallel(step.id); }}
                        className="w-5 h-5 rounded-full bg-orange-100 text-orange-600 flex items-center justify-center text-[10px] hover:bg-orange-200 shadow-sm"
                        title="Toggle parallel execution"
                      >
                        {'\u2016'}
                      </button>
                      <button
                        onClick={(e) => { e.stopPropagation(); onRemoveStep(step.id); }}
                        className="w-5 h-5 rounded-full bg-red-100 text-red-600 flex items-center justify-center text-[10px] hover:bg-red-200 shadow-sm"
                        title="Remove step"
                      >
                        {'\u00d7'}
                      </button>
                    </div>

                    {/* Drag handle */}
                    <div className="absolute top-1/2 -left-3 -translate-y-1/2 opacity-0 group-hover:opacity-100 transition-opacity cursor-grab">
                      <svg className="w-4 h-4 text-gray-300" viewBox="0 0 24 24" fill="currentColor">
                        <circle cx="9" cy="6" r="1.5"/><circle cx="15" cy="6" r="1.5"/>
                        <circle cx="9" cy="12" r="1.5"/><circle cx="15" cy="12" r="1.5"/>
                        <circle cx="9" cy="18" r="1.5"/><circle cx="15" cy="18" r="1.5"/>
                      </svg>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Arrow to next group */}
          {gi < groups.length - 1 && (
            <div className="flex flex-col items-center my-1">
              <div className="w-0.5 h-5 bg-gradient-to-b from-gray-300 to-gray-400" />
              <svg className="w-3 h-2 text-gray-400" viewBox="0 0 12 8" fill="currentColor"><path d="M6 8L0 0h12z"/></svg>
            </div>
          )}
        </div>
      ))}

      {/* End node */}
      <div className="flex flex-col items-center mt-2">
        <div className="w-0.5 h-6 bg-gradient-to-b from-gray-300 to-gray-400" />
        <svg className="w-3 h-2 text-gray-400" viewBox="0 0 12 8" fill="currentColor"><path d="M6 8L0 0h12z"/></svg>
        <div className="w-10 h-10 rounded-full bg-gradient-to-br from-green-500 to-emerald-600 text-white flex items-center justify-center text-sm shadow-md mt-1">
          {'\u2713'}
        </div>
        <span className="text-[10px] text-gray-400 font-medium mt-1">Done</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step Configuration Panel
// ---------------------------------------------------------------------------

function StepConfigPanel({
  step,
  allSteps,
  onUpdate,
  onClose,
}: {
  step: PipelineStep;
  allSteps: PipelineStep[];
  onUpdate: (updated: PipelineStep) => void;
  onClose: () => void;
}) {
  const theme = getToolTheme(step.tool_type);
  const priorSteps = allSteps.filter(s => s.parallel_group < step.parallel_group);

  // Collect all available output keys from prior steps
  const availableInputs: { stepName: string; key: string; ref: string }[] = [];
  for (const ps of priorSteps) {
    for (const k of ps.output_keys) {
      availableInputs.push({ stepName: ps.tool_name, key: k, ref: `${ps.id}.${k}` });
    }
  }

  const [newOutputKey, setNewOutputKey] = useState('');
  const [newInputKey, setNewInputKey] = useState('');
  const [newInputSource, setNewInputSource] = useState('');

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-lg overflow-hidden">
      {/* Header */}
      <div className={`px-5 py-3 ${theme.bg} border-b ${theme.border} flex items-center justify-between`}>
        <div className="flex items-center gap-2">
          <span className="text-lg">{theme.icon}</span>
          <div>
            <h3 className={`text-sm font-bold ${theme.color}`}>{step.tool_name}</h3>
            <span className="text-[10px] text-gray-500">{step.tool_type} · Step #{allSteps.indexOf(step) + 1}</span>
          </div>
        </div>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      <div className="p-5 space-y-5">
        {/* Description */}
        <p className="text-xs text-gray-600">{step.tool_description}</p>

        {/* Input Mapping */}
        <div>
          <h4 className="text-xs font-semibold text-gray-700 mb-2 flex items-center gap-1">
            <svg className="w-3.5 h-3.5 text-indigo-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
            </svg>
            Input Mapping
          </h4>
          {Object.entries(step.input_mapping).length > 0 ? (
            <div className="space-y-1.5">
              {Object.entries(step.input_mapping).map(([key, source]) => (
                <div key={key} className="flex items-center gap-2 bg-gray-50 rounded-lg px-3 py-1.5">
                  <span className="text-[10px] font-mono text-indigo-600 bg-indigo-50 px-1.5 py-0.5 rounded">{source}</span>
                  <svg className="w-3 h-3 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
                  </svg>
                  <span className="text-[10px] font-mono text-gray-700 bg-gray-100 px-1.5 py-0.5 rounded">{key}</span>
                  <button
                    onClick={() => {
                      const { [key]: _, ...rest } = step.input_mapping;
                      onUpdate({ ...step, input_mapping: rest });
                    }}
                    className="ml-auto text-red-400 hover:text-red-600 text-xs"
                  >{'\u00d7'}</button>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-[10px] text-gray-400 italic">No inputs mapped — this step starts fresh</p>
          )}

          {/* Add input mapping */}
          {availableInputs.length > 0 && (
            <div className="flex items-center gap-2 mt-2">
              <select
                value={newInputSource}
                onChange={e => setNewInputSource(e.target.value)}
                className="text-[10px] px-2 py-1 border border-gray-200 rounded-lg flex-1"
              >
                <option value="">Select source...</option>
                {availableInputs.map((ai, i) => (
                  <option key={i} value={ai.ref}>{ai.stepName}.{ai.key}</option>
                ))}
              </select>
              <input
                type="text" value={newInputKey} onChange={e => setNewInputKey(e.target.value)}
                placeholder="as..."
                className="text-[10px] px-2 py-1 border border-gray-200 rounded-lg w-20"
              />
              <button
                onClick={() => {
                  if (newInputSource && newInputKey) {
                    onUpdate({ ...step, input_mapping: { ...step.input_mapping, [newInputKey]: newInputSource } });
                    setNewInputKey(''); setNewInputSource('');
                  }
                }}
                disabled={!newInputSource || !newInputKey}
                className="text-[10px] px-2 py-1 bg-indigo-100 text-indigo-700 rounded-lg font-medium disabled:opacity-30"
              >+ Map</button>
            </div>
          )}
        </div>

        {/* Output Keys */}
        <div>
          <h4 className="text-xs font-semibold text-gray-700 mb-2 flex items-center gap-1">
            <svg className="w-3.5 h-3.5 text-emerald-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 5l7 7-7 7M5 5l7 7-7 7" />
            </svg>
            Output Keys
          </h4>
          <div className="flex flex-wrap gap-1.5">
            {step.output_keys.map((k, i) => (
              <span key={i} className="inline-flex items-center gap-1 text-[10px] font-mono px-2 py-1 rounded-lg bg-emerald-50 text-emerald-700 border border-emerald-200">
                {k}
                <button
                  onClick={() => onUpdate({ ...step, output_keys: step.output_keys.filter((_, j) => j !== i) })}
                  className="text-emerald-400 hover:text-red-500"
                >{'\u00d7'}</button>
              </span>
            ))}
          </div>
          <div className="flex items-center gap-2 mt-2">
            <input
              type="text" value={newOutputKey} onChange={e => setNewOutputKey(e.target.value)}
              placeholder="Add output key..."
              onKeyDown={e => {
                if (e.key === 'Enter' && newOutputKey) {
                  onUpdate({ ...step, output_keys: [...step.output_keys, newOutputKey] });
                  setNewOutputKey('');
                }
              }}
              className="text-[10px] px-2 py-1 border border-gray-200 rounded-lg flex-1"
            />
            <button
              onClick={() => {
                if (newOutputKey) {
                  onUpdate({ ...step, output_keys: [...step.output_keys, newOutputKey] });
                  setNewOutputKey('');
                }
              }}
              disabled={!newOutputKey}
              className="text-[10px] px-2 py-1 bg-emerald-100 text-emerald-700 rounded-lg font-medium disabled:opacity-30"
            >+ Add</button>
          </div>
        </div>

        {/* Parallel group */}
        <div className="flex items-center justify-between bg-orange-50 rounded-lg px-3 py-2">
          <div>
            <span className="text-xs font-medium text-orange-700">Parallel Group</span>
            <p className="text-[10px] text-orange-500">Steps in same group run concurrently</p>
          </div>
          <input
            type="number" min={0} value={step.parallel_group}
            onChange={e => onUpdate({ ...step, parallel_group: parseInt(e.target.value) || 0 })}
            className="w-14 text-center text-sm font-mono border border-orange-200 rounded-lg px-2 py-1"
          />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tool Sidebar
// ---------------------------------------------------------------------------

function ToolSidebar({ tools: toolList, onAddTool }: { tools: CustomTool[]; onAddTool: (tool: CustomTool) => void }) {
  const [search, setSearch] = useState('');
  const filtered = search
    ? toolList.filter(t => t.name.toLowerCase().includes(search.toLowerCase()) || t.description.toLowerCase().includes(search.toLowerCase()))
    : toolList;

  // Group by tool_type
  const groups = new Map<string, CustomTool[]>();
  for (const t of filtered) {
    const type = t.tool_type || 'agent';
    groups.set(type, [...(groups.get(type) || []), t]);
  }

  return (
    <div className="h-full flex flex-col">
      <div className="px-4 py-3 border-b border-gray-200">
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Tool Palette</h3>
        <div className="relative">
          <svg className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
          <input
            type="text" value={search} onChange={e => setSearch(e.target.value)}
            placeholder="Search tools..."
            className="w-full pl-8 pr-3 py-1.5 border border-gray-200 rounded-lg text-xs focus:ring-1 focus:ring-indigo-400"
          />
        </div>
      </div>
      <div className="flex-1 overflow-y-auto px-3 py-2 space-y-4">
        {Array.from(groups.entries()).map(([type, groupTools]) => {
          const theme = getToolTheme(type);
          return (
            <div key={type}>
              <div className="flex items-center gap-1.5 mb-1.5">
                <span className="text-sm">{theme.icon}</span>
                <span className={`text-[10px] font-semibold uppercase tracking-wider ${theme.color}`}>{type}</span>
              </div>
              <div className="space-y-1">
                {groupTools.map(tool => (
                  <button
                    key={tool.id}
                    onClick={() => onAddTool(tool)}
                    className={`w-full text-left px-3 py-2 rounded-xl border ${theme.border} bg-white hover:${theme.bg} hover:shadow-sm transition-all group`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold text-gray-800">{tool.name}</span>
                      <span className="text-gray-300 group-hover:text-indigo-400 transition-colors text-lg">+</span>
                    </div>
                    <p className="text-[10px] text-gray-500 line-clamp-1 mt-0.5">{tool.description}</p>
                  </button>
                ))}
              </div>
            </div>
          );
        })}
        {filtered.length === 0 && (
          <p className="text-xs text-gray-400 text-center py-4">No tools found</p>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function PipelinesPage() {
  const [availableTools, setAvailableTools] = useState<CustomTool[]>([]);
  const [pipelines, setPipelines] = useState<Pipeline[]>([]);
  const [editingPipeline, setEditingPipeline] = useState<Pipeline | null>(null);
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    tools.list({ is_active: true })
      .then(({ tools: t }) => setAvailableTools(t))
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  function createPipeline() {
    setEditingPipeline({ id: `pipeline-${Date.now()}`, name: 'New Pipeline', description: '', steps: [] });
    setSelectedStepId(null);
  }

  function addTool(tool: CustomTool) {
    if (!editingPipeline) return;
    const step: PipelineStep = {
      id: uid(),
      tool_id: tool.id,
      tool_name: tool.name,
      tool_description: tool.description,
      tool_type: tool.tool_type,
      parallel_group: editingPipeline.steps.length,
      input_mapping: {},
      output_keys: ['findings', 'summary'],
      config: {},
    };
    setEditingPipeline({ ...editingPipeline, steps: [...editingPipeline.steps, step] });
    setSelectedStepId(step.id);
  }

  function removeStep(stepId: string) {
    if (!editingPipeline) return;
    setEditingPipeline({ ...editingPipeline, steps: editingPipeline.steps.filter(s => s.id !== stepId) });
    if (selectedStepId === stepId) setSelectedStepId(null);
  }

  function reorder(from: number, to: number) {
    if (!editingPipeline) return;
    const steps = [...editingPipeline.steps];
    const [moved] = steps.splice(from, 1);
    steps.splice(to, 0, moved);
    // Re-assign parallel groups based on position
    steps.forEach((s, i) => { s.parallel_group = i; });
    setEditingPipeline({ ...editingPipeline, steps });
  }

  function toggleParallel(stepId: string) {
    if (!editingPipeline) return;
    const idx = editingPipeline.steps.findIndex(s => s.id === stepId);
    if (idx <= 0) return;
    const steps = [...editingPipeline.steps];
    const prev = steps[idx - 1];
    // Toggle: same group as previous = parallel, own group = sequential
    if (steps[idx].parallel_group === prev.parallel_group) {
      steps[idx] = { ...steps[idx], parallel_group: steps[idx].parallel_group + 1 };
      // Shift all subsequent
      for (let i = idx + 1; i < steps.length; i++) steps[i] = { ...steps[i], parallel_group: steps[i].parallel_group + 1 };
    } else {
      steps[idx] = { ...steps[idx], parallel_group: prev.parallel_group };
    }
    setEditingPipeline({ ...editingPipeline, steps });
  }

  function updateStep(updated: PipelineStep) {
    if (!editingPipeline) return;
    setEditingPipeline({
      ...editingPipeline,
      steps: editingPipeline.steps.map(s => s.id === updated.id ? updated : s),
    });
  }

  function savePipeline() {
    if (!editingPipeline) return;
    setPipelines(prev => {
      const idx = prev.findIndex(p => p.id === editingPipeline.id);
      if (idx >= 0) { const u = [...prev]; u[idx] = editingPipeline; return u; }
      return [...prev, editingPipeline];
    });
    setEditingPipeline(null);
    setSelectedStepId(null);
  }

  const selectedStep = editingPipeline?.steps.find(s => s.id === selectedStepId) || null;

  if (loading) return <p className="text-gray-500 p-4">Loading...</p>;

  // --- Pipeline list view ---
  if (!editingPipeline) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Agent Pipelines</h1>
            <p className="text-sm text-gray-500 mt-1">Build multi-agent workflows with a visual pipeline builder</p>
          </div>
          <button onClick={createPipeline} className="px-4 py-2 bg-indigo-600 text-white rounded-xl text-sm font-medium hover:bg-indigo-700 shadow-sm">
            + New Pipeline
          </button>
        </div>

        {pipelines.length > 0 ? (
          <div className="grid gap-4">
            {pipelines.map(p => (
              <div key={p.id} className="bg-white rounded-xl border border-gray-200 p-5 hover:shadow-md transition-shadow">
                <div className="flex items-center justify-between mb-3">
                  <div>
                    <h3 className="font-semibold text-gray-900">{p.name}</h3>
                    {p.description && <p className="text-xs text-gray-500 mt-0.5">{p.description}</p>}
                  </div>
                  <div className="flex gap-2">
                    <button onClick={() => { setEditingPipeline(p); setSelectedStepId(null); }}
                      className="px-3 py-1.5 text-xs bg-gray-100 rounded-lg hover:bg-gray-200 font-medium">Edit</button>
                    <button className="px-3 py-1.5 text-xs bg-green-100 text-green-700 rounded-lg hover:bg-green-200 font-medium">Run</button>
                  </div>
                </div>
                {/* Mini flow preview */}
                <div className="flex items-center gap-1.5 overflow-x-auto py-1">
                  <div className="w-6 h-6 rounded-full bg-gray-800 text-white flex items-center justify-center text-[8px] font-bold flex-shrink-0">IN</div>
                  {p.steps.map((step, i) => {
                    const theme = getToolTheme(step.tool_type);
                    return (
                      <div key={i} className="flex items-center gap-1.5">
                        <svg className="w-4 h-2 text-gray-300 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 16 8">
                          <path strokeLinecap="round" strokeWidth={1.5} d="M1 4h12m0 0l-3-3m3 3l-3 3" />
                        </svg>
                        <span className={`text-[10px] font-medium px-2 py-1 rounded-lg ${theme.bg} ${theme.color} flex-shrink-0 border ${theme.border}`}>
                          {theme.icon} {step.tool_name}
                        </span>
                      </div>
                    );
                  })}
                  <svg className="w-4 h-2 text-gray-300 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 16 8">
                    <path strokeLinecap="round" strokeWidth={1.5} d="M1 4h12m0 0l-3-3m3 3l-3 3" />
                  </svg>
                  <div className="w-6 h-6 rounded-full bg-green-500 text-white flex items-center justify-center text-[10px] flex-shrink-0">{'\u2713'}</div>
                </div>
                <p className="text-[10px] text-gray-400 mt-2">{p.steps.length} steps</p>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-center py-16 bg-gradient-to-br from-indigo-50/50 to-white rounded-2xl border border-indigo-100">
            <div className="text-5xl mb-4">{'\uD83D\uDD17'}</div>
            <h3 className="text-lg font-semibold text-gray-900">Visual Pipeline Builder</h3>
            <p className="text-sm text-gray-500 mt-1 max-w-md mx-auto">
              Chain multiple agent tools into automated workflows. Each step passes its findings to the next.
            </p>
            <button onClick={createPipeline}
              className="mt-5 px-5 py-2.5 bg-indigo-600 text-white rounded-xl text-sm font-medium hover:bg-indigo-700 shadow-sm">
              Create Your First Pipeline
            </button>
          </div>
        )}
      </div>
    );
  }

  // --- Visual builder ---
  return (
    <div className="space-y-4">
      {/* Top bar */}
      <div className="flex items-center justify-between bg-white rounded-xl border border-gray-200 px-5 py-3 shadow-sm">
        <div className="flex items-center gap-4">
          <button onClick={() => { setEditingPipeline(null); setSelectedStepId(null); }}
            className="p-1.5 rounded-lg bg-gray-100 hover:bg-gray-200">
            <svg className="w-4 h-4 text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>
          <div>
            <input
              type="text" value={editingPipeline.name}
              onChange={e => setEditingPipeline({ ...editingPipeline, name: e.target.value })}
              className="text-lg font-bold text-gray-900 border-none outline-none bg-transparent w-64"
              placeholder="Pipeline name"
            />
            <input
              type="text" value={editingPipeline.description}
              onChange={e => setEditingPipeline({ ...editingPipeline, description: e.target.value })}
              className="block text-xs text-gray-500 border-none outline-none bg-transparent w-80 mt-0.5"
              placeholder="Add a description..."
            />
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-400">{editingPipeline.steps.length} steps</span>
          <button onClick={() => { setEditingPipeline(null); setSelectedStepId(null); }}
            className="px-3 py-1.5 text-sm text-gray-600 hover:text-gray-800">Cancel</button>
          <button onClick={savePipeline}
            className="px-4 py-1.5 text-sm bg-indigo-600 text-white rounded-xl hover:bg-indigo-700 font-medium shadow-sm">
            Save Pipeline
          </button>
        </div>
      </div>

      {/* Builder layout: Sidebar | Canvas | Config */}
      <div className="flex gap-4" style={{ height: 'calc(100vh - 180px)' }}>
        {/* Left: Tool palette */}
        <div className="w-64 bg-white rounded-xl border border-gray-200 overflow-hidden flex-shrink-0">
          <ToolSidebar tools={availableTools} onAddTool={addTool} />
        </div>

        {/* Center: Visual canvas */}
        <div className="flex-1 bg-gradient-to-b from-gray-50 to-white rounded-xl border border-gray-200 overflow-auto">
          <PipelineCanvas
            steps={editingPipeline.steps}
            selectedStep={selectedStepId}
            onSelectStep={setSelectedStepId}
            onRemoveStep={removeStep}
            onReorder={reorder}
            onToggleParallel={toggleParallel}
          />
        </div>

        {/* Right: Step config */}
        <div className="w-80 flex-shrink-0">
          {selectedStep ? (
            <StepConfigPanel
              step={selectedStep}
              allSteps={editingPipeline.steps}
              onUpdate={updateStep}
              onClose={() => setSelectedStepId(null)}
            />
          ) : (
            <div className="bg-white rounded-xl border border-gray-200 p-5 h-full flex flex-col items-center justify-center text-center">
              <svg className="w-10 h-10 text-gray-200 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <p className="text-sm font-medium text-gray-400">Select a step</p>
              <p className="text-xs text-gray-300 mt-1">Click a step in the canvas to configure its inputs, outputs, and settings</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
