'use client';
import { useEffect, useRef, useState } from 'react';
import mermaid from 'mermaid';

mermaid.initialize({ startOnLoad: false, theme: 'default' });

let _id = 0;

export default function MermaidBlock({ code }: { code: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    const id = `mermaid-${++_id}`;
    let cancelled = false;
    mermaid.render(id, code)
      .then(({ svg }) => {
        if (!cancelled && containerRef.current) {
          containerRef.current.innerHTML = svg;
        }
      })
      .catch((err) => {
        if (!cancelled) setError(String(err));
      });
    return () => { cancelled = true; };
  }, [code]);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch { /* clipboard not available */ }
  };

  if (error) {
    return (
      <div className="my-2 rounded-lg overflow-hidden border border-red-200 bg-red-50">
        <div className="flex items-center justify-between px-3 py-1.5 bg-red-100 border-b border-red-200">
          <span className="text-[10px] font-mono text-red-500">mermaid (render error)</span>
          <button onClick={handleCopy} className="text-[10px] text-red-400 hover:text-red-600">
            {copied ? 'Copied!' : 'Copy'}
          </button>
        </div>
        <pre className="p-3 text-xs font-mono overflow-x-auto text-red-700 whitespace-pre-wrap">{code}</pre>
      </div>
    );
  }

  return (
    <div className="my-2 rounded-lg overflow-hidden border border-gray-200 bg-white">
      <div className="flex items-center justify-between px-3 py-1.5 bg-gray-100 border-b border-gray-200">
        <span className="text-[10px] font-mono text-gray-500">mermaid</span>
        <button onClick={handleCopy} className="text-[10px] text-gray-400 hover:text-gray-600">
          {copied ? 'Copied!' : 'Copy'}
        </button>
      </div>
      <div ref={containerRef} className="p-3 flex justify-center overflow-x-auto" />
    </div>
  );
}
