'use client';

import { useState } from 'react';
import type { WorkflowSubtask } from '@/lib/api';

// ---------------------------------------------------------------------------
// Subtask type metadata
// ---------------------------------------------------------------------------

const TYPE_META: Record<string, { icon: string; color: string; bg: string; ring: string; label: string }> = {
  discovery: { icon: '\uD83D\uDD0D', color: 'text-purple-700', bg: 'bg-purple-50',  ring: 'ring-purple-300', label: 'Discovery' },
  agent:     { icon: '\uD83E\uDD16', color: 'text-blue-700',   bg: 'bg-blue-50',    ring: 'ring-blue-300',   label: 'Agent' },
  test:      { icon: '\uD83E\uDDEA', color: 'text-emerald-700', bg: 'bg-emerald-50', ring: 'ring-emerald-300', label: 'Test' },
  coverage:  { icon: '\uD83D\uDCCA', color: 'text-cyan-700',   bg: 'bg-cyan-50',    ring: 'ring-cyan-300',   label: 'Coverage' },
  command:   { icon: '\u26A1',       color: 'text-orange-700',  bg: 'bg-orange-50',  ring: 'ring-orange-300', label: 'Command' },
};

const DEFAULT_TYPE = { icon: '\uD83D\uDCCC', color: 'text-gray-700', bg: 'bg-gray-50', ring: 'ring-gray-300', label: 'Task' };

function getTypeMeta(type: string) { return TYPE_META[type] || DEFAULT_TYPE; }

const STATUS_STYLES: Record<string, { dot: string; line: string; text: string; label: string }> = {
  completed: { dot: 'bg-green-500', line: 'bg-green-300', text: 'text-green-700', label: 'Completed' },
  running:   { dot: 'bg-blue-500',  line: 'bg-blue-300',  text: 'text-blue-700',  label: 'Running' },
  failed:    { dot: 'bg-red-500',   line: 'bg-red-300',   text: 'text-red-700',   label: 'Failed' },
  skipped:   { dot: 'bg-gray-400',  line: 'bg-gray-200',  text: 'text-gray-500',  label: 'Skipped' },
  pending:   { dot: 'bg-gray-300',  line: 'bg-gray-200',  text: 'text-gray-400',  label: 'Pending' },
};

function getStatusStyle(status: string) { return STATUS_STYLES[status] || STATUS_STYLES.pending; }

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDuration(start: string | null, end: string | null): string {
  if (!start) return '';
  const s = new Date(start).getTime();
  const e = end ? new Date(end).getTime() : Date.now();
  const ms = e - s;
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60000).toFixed(1)}m`;
}

function formatTokens(n: number): string {
  if (n >= 1000000) return `${(n / 1000000).toFixed(1)}M`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface RecipeInfo {
  id: string;
  name: string;
  category: string;
  description: string;
  tool_names: string[];
}

interface WorkflowDiagramProps {
  subtasks: WorkflowSubtask[];
  currentStep: number;
  goal?: string;
  status?: string;
  mode?: string;
  recipes?: RecipeInfo[];
  workflowId?: string;
  onRetryStep?: (stepIndex: number, extraTurns: number) => void;
}

export default function WorkflowDiagram({ subtasks, currentStep, goal, status, mode, recipes, workflowId, onRetryStep }: WorkflowDiagramProps) {
  const [expandedStep, setExpandedStep] = useState<number | null>(null);
  const [retryTurns, setRetryTurns] = useState<Record<number, number>>({});

  if (!subtasks || subtasks.length === 0) {
    return (
      <div className="flex items-center justify-center py-10 text-gray-400">
        <div className="text-center">
          <svg className="w-10 h-10 mx-auto mb-2 text-gray-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 17V7m0 10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h2a2 2 0 012 2m0 10a2 2 0 002 2h2a2 2 0 002-2M9 7a2 2 0 012-2h2a2 2 0 012 2m0 10V7m0 10a2 2 0 002 2h2a2 2 0 002-2V7a2 2 0 00-2-2h-2a2 2 0 00-2 2" />
          </svg>
          <p className="text-sm">No subtasks yet</p>
        </div>
      </div>
    );
  }

  const completedCount = subtasks.filter(s => s.status === 'completed').length;
  const failedCount = subtasks.filter(s => s.status === 'failed').length;
  const totalTokens = subtasks.reduce((sum, s) => sum + (s.tokens_used || 0), 0);

  return (
    <div className="space-y-4">
      {/* Header — goal + summary stats */}
      <div className="bg-white border border-gray-200 rounded-xl p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            {goal && (
              <h3 className="text-sm font-semibold text-gray-900 mb-1 line-clamp-2">{goal}</h3>
            )}
            <div className="flex items-center gap-3 text-xs">
              {mode && (
                <span className={`px-2 py-0.5 rounded-full font-medium ${
                  mode === 'testing' ? 'bg-emerald-100 text-emerald-700' : 'bg-blue-100 text-blue-700'
                }`}>
                  {mode}
                </span>
              )}
              {status && (
                <span className={`px-2 py-0.5 rounded-full font-medium ${
                  status === 'completed' ? 'bg-green-100 text-green-700' :
                  status === 'running' ? 'bg-blue-100 text-blue-700' :
                  status === 'paused' ? 'bg-amber-100 text-amber-700' :
                  status === 'failed' ? 'bg-red-100 text-red-700' :
                  'bg-gray-100 text-gray-600'
                }`}>
                  {status}
                </span>
              )}
            </div>
          </div>
          {/* Summary stats */}
          <div className="flex gap-4 text-center flex-shrink-0">
            <div>
              <div className="text-lg font-bold text-gray-900">{completedCount}/{subtasks.length}</div>
              <div className="text-[10px] text-gray-500 uppercase tracking-wider">Steps</div>
            </div>
            {failedCount > 0 && (
              <div>
                <div className="text-lg font-bold text-red-600">{failedCount}</div>
                <div className="text-[10px] text-red-500 uppercase tracking-wider">Failed</div>
              </div>
            )}
            {totalTokens > 0 && (
              <div>
                <div className="text-lg font-bold text-gray-700">{formatTokens(totalTokens)}</div>
                <div className="text-[10px] text-gray-500 uppercase tracking-wider">Tokens</div>
              </div>
            )}
          </div>
        </div>

        {/* Progress bar */}
        <div className="mt-3">
          <div className="h-2 bg-gray-100 rounded-full overflow-hidden flex">
            {subtasks.map((st, i) => {
              const ss = getStatusStyle(st.status);
              const width = 100 / subtasks.length;
              return (
                <div
                  key={i}
                  className={`h-full transition-all duration-500 ${
                    st.status === 'completed' ? 'bg-green-400' :
                    st.status === 'running' ? 'bg-blue-400 animate-pulse' :
                    st.status === 'failed' ? 'bg-red-400' :
                    st.status === 'skipped' ? 'bg-gray-300' :
                    'bg-gray-100'
                  }`}
                  style={{ width: `${width}%` }}
                  title={`${st.title}: ${st.status}`}
                />
              );
            })}
          </div>
        </div>
      </div>

      {/* Flowchart — horizontal connected nodes */}
      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        {/* Recipe context banner — shows what knowledge feeds the flow */}
        {recipes && recipes.length > 0 && (
          <div className="px-4 py-3 bg-gradient-to-r from-indigo-50/80 via-purple-50/50 to-transparent border-b border-indigo-100">
            <div className="flex items-start gap-3">
              {/* Icon + label */}
              <div className="flex items-center gap-1.5 flex-shrink-0 mt-0.5">
                <div className="w-6 h-6 rounded-md bg-indigo-100 flex items-center justify-center">
                  <svg className="w-3.5 h-3.5 text-indigo-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
                  </svg>
                </div>
                <span className="text-[10px] font-semibold text-indigo-600 uppercase tracking-wider">Recipes</span>
              </div>
              {/* Recipe cards */}
              <div className="flex flex-wrap gap-2 flex-1">
                {recipes.map((recipe) => (
                  <div
                    key={recipe.id}
                    className="inline-flex flex-col gap-0.5 px-2.5 py-1.5 rounded-lg bg-white/80 ring-1 ring-indigo-200/60 shadow-sm"
                  >
                    <div className="flex items-center gap-1.5">
                      <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                        recipe.category === 'java' ? 'bg-red-400' :
                        recipe.category === 'dependencies' ? 'bg-purple-400' :
                        recipe.category === 'docker' ? 'bg-blue-400' :
                        recipe.category === 'custom' ? 'bg-indigo-400' :
                        'bg-gray-400'
                      }`} />
                      <span className="text-[11px] font-medium text-gray-800">{recipe.name}</span>
                    </div>
                    {recipe.tool_names.length > 0 && (
                      <div className="flex items-center gap-1 ml-3">
                        {recipe.tool_names.map((tn, ti) => (
                          <span key={ti} className="inline-flex items-center gap-0.5 text-[9px] text-indigo-600 bg-indigo-50 px-1.5 py-0.5 rounded-full font-medium">
                            <svg className="w-2 h-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M11 4a2 2 0 114 0v1a1 1 0 001 1h3a1 1 0 011 1v3a1 1 0 01-1 1h-1a2 2 0 100 4h1a1 1 0 011 1v3a1 1 0 01-1 1h-3a1 1 0 01-1-1v-1a2 2 0 10-4 0v1a1 1 0 01-1 1H7a1 1 0 01-1-1v-3a1 1 0 00-1-1H4a2 2 0 110-4h1a1 1 0 001-1V7a1 1 0 011-1h3a1 1 0 001-1V4z" />
                            </svg>
                            {tn}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
            {/* Downward arrow — recipes feed into the flow */}
            <div className="flex justify-center mt-2">
              <svg className="w-4 h-4 text-indigo-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 14l-7 7m0 0l-7-7m7 7V3" />
              </svg>
            </div>
          </div>
        )}

        {/* Horizontal flow (scrollable) */}
        <div className="p-4 overflow-x-auto">
          <div className="flex items-start gap-0 min-w-max">
            {/* Start node */}
            <div className="flex items-center">
              <div className="w-10 h-10 rounded-full bg-gray-800 text-white flex items-center justify-center text-xs font-bold shadow-sm">
                GO
              </div>
            </div>

            {subtasks.map((st, i) => {
              const typeMeta = getTypeMeta(st.type);
              const ss = getStatusStyle(st.status);
              const isActive = i === currentStep && st.status === 'running';
              const isExpanded = expandedStep === i;

              return (
                <div key={i} className="flex items-start">
                  {/* Connector arrow */}
                  <div className="flex items-center self-center">
                    <div className={`w-8 h-0.5 ${i <= currentStep && st.status !== 'pending' ? ss.line : 'bg-gray-200'}`} />
                    <svg className={`w-2.5 h-2.5 -ml-1 ${i <= currentStep && st.status !== 'pending' ? ss.text : 'text-gray-300'}`} fill="currentColor" viewBox="0 0 24 24">
                      <path d="M8 5v14l11-7z" />
                    </svg>
                  </div>

                  {/* Node */}
                  <button
                    type="button"
                    onClick={() => setExpandedStep(isExpanded ? null : i)}
                    className={`relative flex flex-col items-center w-32 group transition-all ${isExpanded ? 'w-56' : ''}`}
                  >
                    {/* Node circle */}
                    <div className={`relative w-14 h-14 rounded-2xl flex flex-col items-center justify-center border-2 transition-all shadow-sm ${
                      isActive
                        ? `${typeMeta.bg} border-blue-400 ring-4 ring-blue-100 shadow-blue-100`
                        : st.status === 'completed'
                        ? 'bg-green-50 border-green-400'
                        : st.status === 'failed'
                        ? 'bg-red-50 border-red-400'
                        : st.status === 'skipped'
                        ? 'bg-gray-50 border-gray-300'
                        : `${typeMeta.bg} border-gray-200 group-hover:border-gray-300`
                    }`}>
                      {/* Running spinner overlay */}
                      {isActive && (
                        <div className="absolute inset-0 rounded-2xl">
                          <div className="absolute inset-0 rounded-2xl border-2 border-blue-400 border-t-transparent animate-spin" />
                        </div>
                      )}
                      {/* Type icon */}
                      <span className="text-lg leading-none">{typeMeta.icon}</span>
                      {/* Step number */}
                      <span className="text-[9px] font-bold text-gray-500 mt-0.5">{i + 1}</span>

                      {/* Status indicator dot */}
                      <div className={`absolute -top-1 -right-1 w-4 h-4 rounded-full border-2 border-white flex items-center justify-center ${ss.dot}`}>
                        {st.status === 'completed' && (
                          <svg className="w-2.5 h-2.5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                          </svg>
                        )}
                        {st.status === 'failed' && (
                          <svg className="w-2.5 h-2.5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M6 18L18 6M6 6l12 12" />
                          </svg>
                        )}
                        {st.status === 'running' && (
                          <div className="w-2 h-2 bg-white rounded-full animate-pulse" />
                        )}
                      </div>

                      {/* Checkpoint flag */}
                      {st.checkpoint && (
                        <div className="absolute -bottom-1 -left-1 w-4 h-4 rounded-full bg-amber-400 border-2 border-white flex items-center justify-center">
                          <span className="text-[8px]">{'\u23F8'}</span>
                        </div>
                      )}
                    </div>

                    {/* Label */}
                    <div className="mt-2 text-center w-full px-1">
                      <p className={`text-[11px] font-medium leading-tight line-clamp-2 ${
                        isActive ? 'text-blue-700' :
                        st.status === 'completed' ? 'text-gray-800' :
                        st.status === 'failed' ? 'text-red-700' :
                        'text-gray-500'
                      }`}>
                        {st.title}
                      </p>
                      <div className="flex items-center justify-center gap-1 mt-1">
                        <span className={`text-[9px] font-medium px-1.5 py-0.5 rounded-full ${typeMeta.bg} ${typeMeta.color}`}>
                          {typeMeta.label}
                        </span>
                      </div>
                      {/* Duration & tokens (compact) */}
                      {(st.started_at || st.tokens_used > 0) && (
                        <div className="flex items-center justify-center gap-2 mt-1 text-[9px] text-gray-400">
                          {st.started_at && (
                            <span>{formatDuration(st.started_at, st.completed_at)}</span>
                          )}
                          {st.tokens_used > 0 && (
                            <span>{formatTokens(st.tokens_used)}t</span>
                          )}
                          {(st.attempts || 1) > 1 && (
                            <span className="text-orange-500">{st.attempts}x</span>
                          )}
                        </div>
                      )}
                    </div>

                    {/* Expanded detail card */}
                    {isExpanded && (
                      <div className="absolute top-full mt-2 left-1/2 -translate-x-1/2 w-64 bg-white border border-gray-200 rounded-lg shadow-lg p-3 z-20 text-left">
                        <div className="flex items-center justify-between mb-2">
                          <span className="text-xs font-semibold text-gray-900">Step {i + 1}</span>
                          <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${
                            st.status === 'completed' ? 'bg-green-100 text-green-700' :
                            st.status === 'running' ? 'bg-blue-100 text-blue-700' :
                            st.status === 'failed' ? 'bg-red-100 text-red-700' :
                            'bg-gray-100 text-gray-600'
                          }`}>{st.status}</span>
                        </div>
                        <p className="text-xs text-gray-700 font-medium mb-1">{st.title}</p>
                        <p className="text-[11px] text-gray-500 mb-2 line-clamp-3">{st.description}</p>

                        {/* Meta details */}
                        <div className="space-y-1 text-[10px] text-gray-500">
                          <div className="flex justify-between">
                            <span>Type</span>
                            <span className={`font-medium ${typeMeta.color}`}>{typeMeta.label}</span>
                          </div>
                          {st.model_used && (
                            <div className="flex justify-between">
                              <span>Model</span>
                              <span className="font-mono">{st.model_used}</span>
                            </div>
                          )}
                          {st.tokens_used > 0 && (
                            <div className="flex justify-between">
                              <span>Tokens</span>
                              <span>{st.tokens_used.toLocaleString()}</span>
                            </div>
                          )}
                          {st.started_at && (
                            <div className="flex justify-between">
                              <span>Duration</span>
                              <span>{formatDuration(st.started_at, st.completed_at)}</span>
                            </div>
                          )}
                          {(st.attempts || 1) > 1 && (
                            <div className="flex justify-between">
                              <span>Attempts</span>
                              <span className="text-orange-600">{st.attempts}</span>
                            </div>
                          )}
                          {st.checkpoint && (
                            <div className="flex justify-between">
                              <span>Checkpoint</span>
                              <span className="text-amber-600">Pauses for review</span>
                            </div>
                          )}
                        </div>

                        {/* Result */}
                        {st.result_summary && (
                          <div className="mt-2 p-2 rounded bg-gray-50 text-[10px] text-gray-600 line-clamp-3">
                            {st.result_summary}
                          </div>
                        )}
                        {st.error && (
                          <div className="mt-2 p-2 rounded bg-red-50 text-[10px] text-red-600 line-clamp-3">
                            {st.error}
                          </div>
                        )}

                        {/* Grant More Turns & Retry — shown on failed steps */}
                        {st.status === 'failed' && onRetryStep && (
                          <div className="mt-2 p-2 rounded bg-amber-50 border border-amber-200">
                            <p className="text-[10px] text-amber-700 font-medium mb-1.5">Grant more turns and retry?</p>
                            <div className="flex items-center gap-2">
                              <select
                                value={retryTurns[i] || 30}
                                onChange={e => setRetryTurns(prev => ({ ...prev, [i]: Number(e.target.value) }))}
                                className="text-[10px] px-1.5 py-1 border border-amber-300 rounded bg-white text-gray-700"
                                onClick={e => e.stopPropagation()}
                              >
                                <option value={20}>+20 turns</option>
                                <option value={30}>+30 turns</option>
                                <option value={50}>+50 turns</option>
                                <option value={75}>+75 turns</option>
                                <option value={100}>+100 turns</option>
                              </select>
                              <button
                                onClick={e => { e.stopPropagation(); onRetryStep(i, retryTurns[i] || 30); }}
                                className="px-2.5 py-1 bg-amber-600 text-white rounded text-[10px] font-medium hover:bg-amber-700 transition-colors"
                              >
                                Retry Step
                              </button>
                            </div>
                          </div>
                        )}

                        {/* Files changed */}
                        {st.files_changed && st.files_changed.length > 0 && (
                          <div className="mt-2">
                            <span className="text-[10px] text-gray-500">{st.files_changed.length} files changed</span>
                            <div className="mt-0.5 max-h-16 overflow-y-auto">
                              {st.files_changed.slice(0, 8).map((f, fi) => (
                                <div key={fi} className="text-[10px] font-mono text-gray-400 truncate">{f}</div>
                              ))}
                              {st.files_changed.length > 8 && (
                                <div className="text-[10px] text-gray-400">+{st.files_changed.length - 8} more</div>
                              )}
                            </div>
                          </div>
                        )}
                      </div>
                    )}
                  </button>
                </div>
              );
            })}

            {/* End node */}
            <div className="flex items-center self-center">
              <div className={`w-8 h-0.5 ${status === 'completed' ? 'bg-green-300' : 'bg-gray-200'}`} />
              <div className={`w-10 h-10 rounded-full flex items-center justify-center text-sm shadow-sm ${
                status === 'completed' ? 'bg-green-500 text-white' :
                status === 'failed' ? 'bg-red-500 text-white' :
                'bg-gray-200 text-gray-500'
              }`}>
                {status === 'completed' ? '\u2713' : status === 'failed' ? '\u2717' : '\u25CF'}
              </div>
            </div>
          </div>
        </div>

        {/* Legend */}
        <div className="px-4 py-2 bg-gray-50 border-t border-gray-100 flex items-center gap-4 text-[10px] text-gray-500 overflow-x-auto">
          <span className="font-medium text-gray-600 flex-shrink-0">Types:</span>
          {Object.entries(TYPE_META).map(([key, meta]) => (
            <span key={key} className="inline-flex items-center gap-1 flex-shrink-0">
              <span>{meta.icon}</span>
              <span>{meta.label}</span>
            </span>
          ))}
          <span className="mx-1 text-gray-300">|</span>
          <span className="inline-flex items-center gap-1 flex-shrink-0">
            <span>{'\u23F8'}</span>
            <span>Checkpoint</span>
          </span>
        </div>
      </div>

      {/* Vertical detailed timeline */}
      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
        <div className="px-4 py-3 bg-gray-50 border-b border-gray-200">
          <h4 className="text-sm font-semibold text-gray-700">Step Details</h4>
        </div>
        <div className="relative px-4 py-3">
          {/* Vertical line */}
          <div className="absolute left-8 top-3 bottom-3 w-0.5 bg-gray-200" />

          <div className="space-y-3">
            {subtasks.map((st, i) => {
              const typeMeta = getTypeMeta(st.type);
              const ss = getStatusStyle(st.status);
              const isActive = i === currentStep && st.status === 'running';

              return (
                <div key={i} className="relative flex items-start gap-3 pl-1">
                  {/* Timeline node */}
                  <div className={`relative z-10 w-7 h-7 rounded-lg flex items-center justify-center text-xs flex-shrink-0 transition-all ${
                    isActive ? `${typeMeta.bg} ring-2 ${typeMeta.ring} shadow-sm` :
                    st.status === 'completed' ? 'bg-green-50' :
                    st.status === 'failed' ? 'bg-red-50' :
                    'bg-gray-50'
                  }`}>
                    {st.status === 'completed' ? (
                      <svg className="w-3.5 h-3.5 text-green-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                      </svg>
                    ) : st.status === 'failed' ? (
                      <svg className="w-3.5 h-3.5 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    ) : isActive ? (
                      <div className="w-3 h-3 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
                    ) : (
                      <span className="text-xs text-gray-400 font-medium">{i + 1}</span>
                    )}
                  </div>

                  {/* Step content */}
                  <div className={`flex-1 min-w-0 pb-1 ${i < subtasks.length - 1 ? '' : ''}`}>
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className={`text-sm font-medium ${
                        isActive ? 'text-blue-700' :
                        st.status === 'completed' ? 'text-gray-900' :
                        st.status === 'failed' ? 'text-red-700' :
                        'text-gray-500'
                      }`}>{st.title}</span>
                      <span className={`text-[9px] font-semibold px-1.5 py-0.5 rounded-full ${typeMeta.bg} ${typeMeta.color}`}>
                        {typeMeta.icon} {typeMeta.label}
                      </span>
                      {st.checkpoint && (
                        <span className="text-[9px] font-medium px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-700">
                          {'\u23F8'} checkpoint
                        </span>
                      )}
                      {isActive && (
                        <span className="text-[10px] text-blue-500 font-medium animate-pulse">working...</span>
                      )}
                    </div>
                    <p className="text-[11px] text-gray-500 mt-0.5 line-clamp-1">{st.description}</p>
                    <div className="flex items-center gap-3 mt-1 text-[10px] text-gray-400">
                      {st.model_used && <span className="font-mono">{st.model_used}</span>}
                      {st.started_at && <span>{formatDuration(st.started_at, st.completed_at)}</span>}
                      {st.tokens_used > 0 && <span>{formatTokens(st.tokens_used)} tokens</span>}
                      {(st.attempts || 1) > 1 && <span className="text-orange-500">{st.attempts} attempts</span>}
                      {st.files_changed?.length > 0 && <span>{st.files_changed.length} files</span>}
                    </div>
                    {st.result_summary && (
                      <p className="text-[11px] text-gray-600 mt-1 bg-gray-50 rounded px-2 py-1 line-clamp-2">{st.result_summary}</p>
                    )}
                    {st.error && (
                      <p className="text-[11px] text-red-600 mt-1 bg-red-50 rounded px-2 py-1 line-clamp-2">{st.error}</p>
                    )}
                    {/* Grant More Turns — vertical timeline */}
                    {st.status === 'failed' && onRetryStep && (
                      <div className="mt-2 flex items-center gap-2 p-2 bg-amber-50 border border-amber-200 rounded-lg">
                        <span className="text-[11px] text-amber-700 font-medium">Turn limit reached.</span>
                        <select
                          value={retryTurns[i] || 30}
                          onChange={e => setRetryTurns(prev => ({ ...prev, [i]: Number(e.target.value) }))}
                          className="text-[11px] px-2 py-1 border border-amber-300 rounded bg-white text-gray-700"
                        >
                          <option value={20}>+20 turns</option>
                          <option value={30}>+30 turns</option>
                          <option value={50}>+50 turns</option>
                          <option value={75}>+75 turns</option>
                          <option value={100}>+100 turns</option>
                        </select>
                        <button
                          onClick={() => onRetryStep(i, retryTurns[i] || 30)}
                          className="px-3 py-1 bg-amber-600 text-white rounded text-[11px] font-medium hover:bg-amber-700 transition-colors"
                        >
                          Grant Turns & Retry
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
