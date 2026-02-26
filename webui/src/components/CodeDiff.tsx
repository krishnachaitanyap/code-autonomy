'use client';

interface DiffLine {
  type: 'add' | 'remove' | 'context';
  content: string;
  oldLine?: number;
  newLine?: number;
}

interface CodeDiffProps {
  filename: string;
  lines: DiffLine[];
}

export default function CodeDiff({ filename, lines }: CodeDiffProps) {
  return (
    <div className="border border-gray-200 rounded-lg overflow-hidden">
      <div className="bg-gray-100 px-4 py-2 border-b border-gray-200">
        <span className="font-mono text-sm font-medium text-gray-700">
          {filename}
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm font-mono">
          <tbody>
            {lines.map((line, i) => {
              const bg =
                line.type === 'add'
                  ? 'bg-green-50'
                  : line.type === 'remove'
                  ? 'bg-red-50'
                  : '';
              const textColor =
                line.type === 'add'
                  ? 'text-green-800'
                  : line.type === 'remove'
                  ? 'text-red-800'
                  : 'text-gray-700';
              const prefix =
                line.type === 'add' ? '+' : line.type === 'remove' ? '-' : ' ';

              return (
                <tr key={i} className={bg}>
                  <td className="px-2 py-0.5 text-gray-400 text-right select-none w-12 border-r border-gray-200">
                    {line.oldLine ?? ''}
                  </td>
                  <td className="px-2 py-0.5 text-gray-400 text-right select-none w-12 border-r border-gray-200">
                    {line.newLine ?? ''}
                  </td>
                  <td className={`px-3 py-0.5 whitespace-pre ${textColor}`}>
                    {prefix} {line.content}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
