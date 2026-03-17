'use client';
import { useEffect, useRef, useState } from 'react';
import mermaid from 'mermaid';

mermaid.initialize({ startOnLoad: false, theme: 'default' });

let _id = 0;

export default function MermaidBlock({ code }: { code: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [svgContent, setSvgContent] = useState<string>('');
  const [showPopup, setShowPopup] = useState(false);

  useEffect(() => {
    const id = `mermaid-${++_id}`;
    let cancelled = false;
    mermaid.render(id, code)
      .then(({ svg }) => {
        if (!cancelled) {
          setSvgContent(svg);
          if (containerRef.current) containerRef.current.innerHTML = svg;
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

  const handleDownloadSvg = () => {
    if (!svgContent) return;
    const blob = new Blob([svgContent], { type: 'image/svg+xml' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'diagram.svg';
    a.click();
    URL.revokeObjectURL(url);
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
    <>
      <div className="my-2 rounded-lg overflow-hidden border border-gray-200 bg-white">
        <div className="flex items-center justify-between px-3 py-1.5 bg-gray-100 border-b border-gray-200">
          <span className="text-[10px] font-mono text-gray-500">mermaid</span>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setShowPopup(true)}
              className="text-[10px] text-gray-400 hover:text-gray-600"
              title="Expand diagram"
            >
              <svg className="w-3.5 h-3.5 inline" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5v-4m0 4h-4m4 0l-5-5" />
              </svg>
            </button>
            <button onClick={handleCopy} className="text-[10px] text-gray-400 hover:text-gray-600">
              {copied ? 'Copied!' : 'Copy'}
            </button>
          </div>
        </div>
        <div
          ref={containerRef}
          className="p-3 flex justify-center overflow-x-auto cursor-pointer"
          onClick={() => setShowPopup(true)}
        />
      </div>

      {/* Fullscreen popup */}
      {showPopup && (
        <div
          className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-6"
          onClick={() => setShowPopup(false)}
        >
          <div
            className="bg-white rounded-xl shadow-2xl max-w-[90vw] max-h-[90vh] flex flex-col overflow-hidden"
            onClick={e => e.stopPropagation()}
          >
            {/* Popup header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200 bg-gray-50">
              <span className="text-sm font-medium text-gray-700">Mermaid Diagram</span>
              <div className="flex items-center gap-2">
                <button
                  onClick={handleDownloadSvg}
                  className="px-2.5 py-1 text-[11px] font-medium text-gray-600 bg-gray-100 rounded hover:bg-gray-200 transition-colors"
                >
                  Download SVG
                </button>
                <button
                  onClick={handleCopy}
                  className="px-2.5 py-1 text-[11px] font-medium text-gray-600 bg-gray-100 rounded hover:bg-gray-200 transition-colors"
                >
                  {copied ? 'Copied!' : 'Copy Source'}
                </button>
                <button
                  onClick={() => setShowPopup(false)}
                  className="ml-1 text-gray-400 hover:text-gray-600"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
            </div>

            {/* Popup body — rendered SVG */}
            <div
              className="flex-1 overflow-auto p-6 flex items-center justify-center min-h-[300px]"
              dangerouslySetInnerHTML={{ __html: svgContent }}
            />
          </div>
        </div>
      )}
    </>
  );
}
