'use client';

import {
  BarChart, Bar, LineChart, Line, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from 'recharts';

interface SplunkChartProps {
  title: string;
  chartType: 'bar' | 'line' | 'pie';
  columns: string[];
  rows: Record<string, string | number>[];
}

const COLORS = [
  '#0d9488', '#0284c7', '#7c3aed', '#db2777', '#ea580c',
  '#65a30d', '#0891b2', '#6366f1', '#e11d48', '#d97706',
];

export default function SplunkChart({ title, chartType, columns, rows }: SplunkChartProps) {
  if (!rows.length || columns.length < 2) {
    return (
      <div className="my-2 p-4 rounded-lg border border-teal-200 bg-white text-sm text-gray-500">
        No data to chart.
      </div>
    );
  }

  // First column = category/time axis, rest = value columns
  const categoryCol = columns[0];
  const valueCols = columns.slice(1);

  // Convert string values to numbers for charting
  const data = rows.map(row => {
    const point: Record<string, any> = { [categoryCol]: row[categoryCol] };
    for (const vc of valueCols) {
      const v = row[vc];
      point[vc] = typeof v === 'number' ? v : Number(v) || 0;
    }
    return point;
  });

  const renderChart = () => {
    if (chartType === 'pie') {
      const valueCol = valueCols[0];
      return (
        <PieChart>
          <Pie
            data={data}
            dataKey={valueCol}
            nameKey={categoryCol}
            cx="50%"
            cy="50%"
            outerRadius={80}
            label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
          >
            {data.map((_, idx) => (
              <Cell key={idx} fill={COLORS[idx % COLORS.length]} />
            ))}
          </Pie>
          <Tooltip />
          <Legend />
        </PieChart>
      );
    }

    if (chartType === 'line') {
      return (
        <LineChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
          <XAxis dataKey={categoryCol} tick={{ fontSize: 11 }} />
          <YAxis tick={{ fontSize: 11 }} />
          <Tooltip />
          <Legend />
          {valueCols.map((vc, i) => (
            <Line
              key={vc}
              type="monotone"
              dataKey={vc}
              stroke={COLORS[i % COLORS.length]}
              strokeWidth={2}
              dot={{ r: 2 }}
            />
          ))}
        </LineChart>
      );
    }

    // Default: bar
    return (
      <BarChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
        <XAxis dataKey={categoryCol} tick={{ fontSize: 11 }} />
        <YAxis tick={{ fontSize: 11 }} />
        <Tooltip />
        <Legend />
        {valueCols.map((vc, i) => (
          <Bar key={vc} dataKey={vc} fill={COLORS[i % COLORS.length]} />
        ))}
      </BarChart>
    );
  };

  return (
    <div className="my-2 rounded-lg border border-teal-200 bg-white overflow-hidden">
      <div className="px-3 py-2 bg-teal-50 border-b border-teal-200">
        <span className="text-sm font-semibold text-teal-800">{title}</span>
        <span className="text-xs text-teal-600 ml-2">({rows.length} points)</span>
      </div>
      <div className="p-3">
        <ResponsiveContainer width="100%" height={250}>
          {renderChart()}
        </ResponsiveContainer>
      </div>
    </div>
  );
}
