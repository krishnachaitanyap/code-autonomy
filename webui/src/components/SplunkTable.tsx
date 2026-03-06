'use client';

import { useState, useMemo } from 'react';

interface SplunkTableProps {
  title: string;
  columns: string[];
  rows: Record<string, string | number>[];
  total: number;
}

type SortDir = 'asc' | 'desc';

export default function SplunkTable({ title, columns, rows, total }: SplunkTableProps) {
  const [sortCol, setSortCol] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>('asc');

  const sorted = useMemo(() => {
    if (!sortCol) return rows;
    return [...rows].sort((a, b) => {
      const av = a[sortCol] ?? '';
      const bv = b[sortCol] ?? '';
      // Try numeric comparison
      const an = Number(av);
      const bn = Number(bv);
      if (!isNaN(an) && !isNaN(bn)) {
        return sortDir === 'asc' ? an - bn : bn - an;
      }
      const cmp = String(av).localeCompare(String(bv));
      return sortDir === 'asc' ? cmp : -cmp;
    });
  }, [rows, sortCol, sortDir]);

  function handleSort(col: string) {
    if (sortCol === col) {
      setSortDir(d => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortCol(col);
      setSortDir('asc');
    }
  }

  const sortIcon = (col: string) => {
    if (sortCol !== col) return '\u2195';
    return sortDir === 'asc' ? '\u2191' : '\u2193';
  };

  return (
    <div className="my-2 rounded-lg border border-teal-200 bg-white overflow-hidden">
      <div className="px-3 py-2 bg-teal-50 border-b border-teal-200 flex items-center justify-between">
        <span className="text-sm font-semibold text-teal-800">{title}</span>
        <span className="text-xs text-teal-600">{total} row{total !== 1 ? 's' : ''}</span>
      </div>
      <div className="overflow-auto max-h-80">
        <table className="w-full text-xs">
          <thead className="bg-gray-50 sticky top-0">
            <tr>
              {columns.map(col => (
                <th
                  key={col}
                  className="px-3 py-1.5 text-left font-medium text-gray-600 cursor-pointer hover:bg-gray-100 select-none whitespace-nowrap"
                  onClick={() => handleSort(col)}
                >
                  {col} <span className="text-gray-400 ml-0.5">{sortIcon(col)}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {sorted.map((row, i) => (
              <tr key={i} className="hover:bg-gray-50">
                {columns.map(col => (
                  <td key={col} className="px-3 py-1.5 text-gray-700 whitespace-nowrap max-w-[300px] truncate">
                    {String(row[col] ?? '')}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
