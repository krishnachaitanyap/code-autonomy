'use client';

import type { MigrationRoadmapStep } from '@/lib/api';
import MigrationStatusBadge from './MigrationStatusBadge';

const CATEGORY_ICONS: Record<string, string> = {
  java: '\u2615',
  dependencies: '\ud83d\udce6',
  docker: '\ud83d\udc33',
  k8s: '\u2638\ufe0f',
  cicd: '\ud83d\ude80',
  config: '\u2699\ufe0f',
  observability: '\ud83d\udcca',
  security: '\ud83d\udd12',
  testing: '\ud83e\uddea',
  quality: '\u2728',
  database: '\ud83d\uddc4\ufe0f',
};

interface RoadmapTimelineProps {
  steps: MigrationRoadmapStep[];
  currentStep: number;
  onExecuteStep?: (stepIndex: number) => void;
  executing?: boolean;
}

export default function RoadmapTimeline({ steps, currentStep, onExecuteStep, executing }: RoadmapTimelineProps) {
  if (!steps || steps.length === 0) {
    return (
      <p className="text-sm text-gray-400 text-center py-8">
        No roadmap generated yet. Select recipes and generate a roadmap.
      </p>
    );
  }

  return (
    <div className="relative">
      {/* Vertical line */}
      <div className="absolute left-6 top-0 bottom-0 w-0.5 bg-gray-200" />

      <div className="space-y-4">
        {steps.map((step, i) => {
          const isCurrent = i === currentStep;
          const isDone = step.status === 'completed';
          const isFailed = step.status === 'failed';
          const isRunning = step.status === 'running';

          return (
            <div key={i} className="relative flex items-start gap-4 pl-2">
              {/* Timeline dot */}
              <div className={`relative z-10 w-8 h-8 rounded-full flex items-center justify-center text-sm shrink-0 ${
                isDone ? 'bg-green-100 text-green-600' :
                isFailed ? 'bg-red-100 text-red-600' :
                isRunning ? 'bg-amber-100 text-amber-600 ring-2 ring-amber-400 animate-pulse' :
                isCurrent ? 'bg-indigo-100 text-indigo-600 ring-2 ring-indigo-400' :
                'bg-gray-100 text-gray-500'
              }`}>
                {isDone ? '\u2713' : isFailed ? '\u2717' : isRunning ? (
                  <div className="w-4 h-4 border-2 border-amber-600 border-t-transparent rounded-full animate-spin" />
                ) : i + 1}
              </div>

              {/* Step content */}
              <div className={`flex-1 bg-white border rounded-lg p-3 ${
                isRunning ? 'border-amber-300 shadow-sm' :
                isCurrent ? 'border-indigo-300 shadow-sm' : 'border-gray-200'
              }`}>
                <div className="flex items-start justify-between gap-2">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-sm">{CATEGORY_ICONS[step.category] || '\ud83d\udccc'}</span>
                      <span className="text-sm font-medium text-gray-900">{step.title}</span>
                      <MigrationStatusBadge status={step.status} />
                      {isRunning && (
                        <span className="text-[10px] text-amber-600 font-medium">AI agent working...</span>
                      )}
                    </div>
                    <p className="text-xs text-gray-500 mt-1">{step.description}</p>
                  </div>
                  {onExecuteStep && step.status === 'pending' && (
                    <button
                      onClick={() => onExecuteStep(i)}
                      disabled={executing}
                      className="px-2.5 py-1 bg-indigo-600 text-white text-xs rounded hover:bg-indigo-700 disabled:opacity-50 shrink-0"
                    >
                      Execute
                    </button>
                  )}
                </div>

                {/* Running indicator */}
                {isRunning && (
                  <div className="mt-2 flex items-center gap-2 text-xs text-amber-700 bg-amber-50 rounded p-2">
                    <div className="w-3 h-3 border-2 border-amber-600 border-t-transparent rounded-full animate-spin shrink-0" />
                    Executing migration step with AI agent...
                  </div>
                )}

                {/* Step result */}
                {step.result_summary && (
                  <div className="mt-2 text-xs text-gray-600 bg-gray-50 rounded p-2">
                    {step.result_summary}
                  </div>
                )}
                {step.error && (
                  <div className="mt-2 text-xs text-red-600 bg-red-50 rounded p-2">
                    {step.error}
                  </div>
                )}

                {/* Files changed */}
                {step.files_affected && step.files_affected.length > 0 && (isDone || isFailed) && (
                  <div className="mt-2">
                    <details className="text-xs">
                      <summary className="text-gray-500 cursor-pointer hover:text-gray-700">
                        {step.files_affected.length} file{step.files_affected.length !== 1 ? 's' : ''} changed
                      </summary>
                      <ul className="mt-1 space-y-0.5 text-gray-500 pl-4">
                        {step.files_affected.map((f: string, fi: number) => (
                          <li key={fi} className="font-mono text-[11px]">{f}</li>
                        ))}
                      </ul>
                    </details>
                  </div>
                )}

                {/* Meta */}
                <div className="flex items-center gap-3 mt-2">
                  <span className="text-[10px] text-gray-400">Priority: {step.priority}</span>
                  <span className="text-[10px] text-gray-400 capitalize">{step.category}</span>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
