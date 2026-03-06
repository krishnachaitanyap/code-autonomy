'use client';

import SplunkTable from './SplunkTable';
import SplunkChart from './SplunkChart';

interface StructuredData {
  __structured: true;
  format: 'table' | 'chart';
  title: string;
  columns: string[];
  rows: Record<string, string | number>[];
  total: number;
  chart_type?: 'bar' | 'line' | 'pie';
}

/**
 * Try to parse a structured result from a tool result string.
 * Returns the parsed data or null if the string is not structured.
 */
export function tryParseStructured(text: string): StructuredData | null {
  if (!text) return null;
  // The structured envelope is always the first line (JSON)
  const firstLine = text.split('\n')[0];
  if (!firstLine.startsWith('{"__structured"')) return null;
  try {
    const data = JSON.parse(firstLine);
    if (data.__structured) return data as StructuredData;
  } catch {
    // Not valid JSON
  }
  return null;
}

interface StructuredResultProps {
  data: StructuredData;
}

export default function StructuredResult({ data }: StructuredResultProps) {
  if (data.format === 'chart') {
    return (
      <SplunkChart
        title={data.title}
        chartType={data.chart_type || 'bar'}
        columns={data.columns}
        rows={data.rows}
      />
    );
  }

  return (
    <SplunkTable
      title={data.title}
      columns={data.columns}
      rows={data.rows}
      total={data.total}
    />
  );
}
