'use client';

interface Span {
  name: string;
  type: string;
  start_time: number;
  end_time: number;
  metadata?: Record<string, any>;
}

interface TraceTimelineProps {
  spans: Span[];
  totalDuration: number;
}

const TYPE_COLORS: Record<string, string> = {
  llm_call: 'bg-indigo-400',
  tool_call: 'bg-amber-400',
  retrieval: 'bg-green-400',
  planning: 'bg-purple-400',
  default: 'bg-gray-400',
};

export default function TraceTimeline({ spans, totalDuration }: TraceTimelineProps) {
  if (!spans.length || totalDuration <= 0) {
    return <p className="text-gray-500 text-sm">No spans to display.</p>;
  }

  const minStart = Math.min(...spans.map((s) => s.start_time));

  return (
    <div className="space-y-4">
      {/* Legend */}
      <div className="flex flex-wrap gap-3 text-xs">
        {Object.entries(TYPE_COLORS).map(([type, color]) =>
          type !== 'default' ? (
            <div key={type} className="flex items-center gap-1">
              <div className={`w-3 h-3 rounded ${color}`} />
              <span className="text-gray-600">{type.replace('_', ' ')}</span>
            </div>
          ) : null,
        )}
      </div>

      {/* Timeline */}
      <div className="relative bg-gray-100 rounded-lg p-4 space-y-2">
        {spans.map((span, i) => {
          const left = ((span.start_time - minStart) / totalDuration) * 100;
          const width =
            Math.max(((span.end_time - span.start_time) / totalDuration) * 100, 0.5);
          const color = TYPE_COLORS[span.type] || TYPE_COLORS.default;
          const durationMs = Math.round((span.end_time - span.start_time) * 1000);

          return (
            <div key={i} className="flex items-center gap-3 group">
              <span className="text-xs text-gray-500 w-28 truncate flex-shrink-0">
                {span.name}
              </span>
              <div className="flex-1 relative h-6">
                <div
                  className={`absolute top-0 h-full rounded ${color} opacity-80 hover:opacity-100 transition-opacity cursor-pointer`}
                  style={{ left: `${left}%`, width: `${width}%`, minWidth: '4px' }}
                  title={`${span.name} (${span.type}): ${durationMs}ms`}
                />
              </div>
              <span className="text-xs text-gray-400 w-16 text-right flex-shrink-0">
                {durationMs}ms
              </span>
            </div>
          );
        })}
      </div>

      {/* Time axis */}
      <div className="flex justify-between text-xs text-gray-400 px-32">
        <span>0s</span>
        <span>{(totalDuration / 2).toFixed(1)}s</span>
        <span>{totalDuration.toFixed(1)}s</span>
      </div>
    </div>
  );
}
