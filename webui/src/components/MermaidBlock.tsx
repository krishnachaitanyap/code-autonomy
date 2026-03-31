'use client';
import { useEffect, useRef, useState, useCallback } from 'react';
import mermaid from 'mermaid';

mermaid.initialize({
  startOnLoad: false,
  theme: 'default',
  securityLevel: 'loose',
  suppressErrorRendering: true,
});

let _id = 0;

function DiagramViewer({ svgContent, onClose, onCopy, onDownload, copied }: {
  svgContent: string;
  onClose: () => void;
  onCopy: () => void;
  onDownload: () => void;
  copied: boolean;
}) {
  const viewerRef = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [dragging, setDragging] = useState(false);
  const dragStart = useRef({ x: 0, y: 0 });
  const offsetStart = useRef({ x: 0, y: 0 });

  const handleWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? -0.1 : 0.1;
    setScale(s => Math.min(5, Math.max(0.2, s + delta)));
  }, []);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (e.button !== 0) return;
    setDragging(true);
    dragStart.current = { x: e.clientX, y: e.clientY };
    offsetStart.current = { ...offset };
  }, [offset]);

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (!dragging) return;
    setOffset({
      x: offsetStart.current.x + (e.clientX - dragStart.current.x),
      y: offsetStart.current.y + (e.clientY - dragStart.current.y),
    });
  }, [dragging]);

  const handleMouseUp = useCallback(() => {
    setDragging(false);
  }, []);

  const resetView = useCallback(() => {
    setScale(1);
    setOffset({ x: 0, y: 0 });
  }, []);

  const fitToView = useCallback(() => {
    setScale(1.5);
    setOffset({ x: 0, y: 0 });
  }, []);

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-xl shadow-2xl flex flex-col overflow-hidden"
        style={{ width: '92vw', height: '88vh' }}
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-200 bg-gray-50 shrink-0">
          <span className="text-sm font-semibold text-gray-700">Mermaid Diagram</span>
          <div className="flex items-center gap-1.5">
            {/* Zoom controls */}
            <button
              onClick={() => setScale(s => Math.min(5, s + 0.25))}
              className="px-2 py-1 text-xs font-medium text-gray-600 bg-gray-100 rounded hover:bg-gray-200 transition-colors"
              title="Zoom in"
            >
              +
            </button>
            <span className="text-[11px] text-gray-500 w-12 text-center font-mono">
              {Math.round(scale * 100)}%
            </span>
            <button
              onClick={() => setScale(s => Math.max(0.2, s - 0.25))}
              className="px-2 py-1 text-xs font-medium text-gray-600 bg-gray-100 rounded hover:bg-gray-200 transition-colors"
              title="Zoom out"
            >
              -
            </button>
            <div className="w-px h-4 bg-gray-300 mx-1" />
            <button
              onClick={fitToView}
              className="px-2.5 py-1 text-[11px] font-medium text-gray-600 bg-gray-100 rounded hover:bg-gray-200 transition-colors"
              title="Fit to view"
            >
              Fit
            </button>
            <button
              onClick={resetView}
              className="px-2.5 py-1 text-[11px] font-medium text-gray-600 bg-gray-100 rounded hover:bg-gray-200 transition-colors"
              title="Reset zoom and position"
            >
              Reset
            </button>
            <div className="w-px h-4 bg-gray-300 mx-1" />
            <button
              onClick={onDownload}
              className="px-2.5 py-1 text-[11px] font-medium text-gray-600 bg-gray-100 rounded hover:bg-gray-200 transition-colors"
            >
              Download SVG
            </button>
            <button
              onClick={onCopy}
              className="px-2.5 py-1 text-[11px] font-medium text-gray-600 bg-gray-100 rounded hover:bg-gray-200 transition-colors"
            >
              {copied ? 'Copied!' : 'Copy Source'}
            </button>
            <button
              onClick={onClose}
              className="ml-2 text-gray-400 hover:text-gray-600"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        {/* Diagram canvas — pannable & zoomable */}
        <div
          ref={viewerRef}
          className="flex-1 overflow-hidden bg-gray-50"
          style={{ cursor: dragging ? 'grabbing' : 'grab' }}
          onWheel={handleWheel}
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onMouseLeave={handleMouseUp}
        >
          <div
            className="w-full h-full flex items-center justify-center"
            style={{
              transform: `translate(${offset.x}px, ${offset.y}px) scale(${scale})`,
              transformOrigin: 'center center',
              transition: dragging ? 'none' : 'transform 0.15s ease-out',
            }}
            dangerouslySetInnerHTML={{ __html: svgContent }}
          />
        </div>

        {/* Footer hint */}
        <div className="px-5 py-2 border-t border-gray-200 bg-gray-50 text-[10px] text-gray-400 shrink-0">
          Scroll to zoom &middot; Drag to pan &middot; Esc to close
        </div>
      </div>
    </div>
  );
}

/**
 * Sanitize LLM-generated Mermaid code for Mermaid v11 compatibility.
 *
 * Handles three categories of problems LLMs introduce:
 *  1. Edge labels with parens:  -->|onMessage()| Node  (parens break parser)
 *  2. Node labels with special chars:  K[Kafka Topic(s)]  YML[app.yml & profiles]
 *  3. Raw & characters outside quoted strings
 *
 * Strategy: process edge labels first (strip parens from |...|), then
 * quote node labels that contain special characters.
 */
function sanitizeMermaidCode(raw: string): string {
  const SKIP_LINE = /^(\s*)(%%|graph\s|flowchart\s|sequenceDiagram|classDiagram|stateDiagram|erDiagram|gantt|pie|gitGraph|mindmap|timeline|style\s|linkStyle\s|class\s|click\s|title\s|section\s|participant\s|actor\s|Note\s|loop\s|alt\s|opt\s|rect\s|activate\s|deactivate\s|autonumber|direction\s)/;

  return raw
    .split('\n')
    .map(line => {
      const trimmed = line.trim();
      if (!trimmed || trimmed === 'end' || SKIP_LINE.test(trimmed)) return line;

      // Subgraph labels
      if (trimmed.startsWith('subgraph ')) {
        const rest = trimmed.slice(9).trim();
        // If label has special chars and isn't already quoted, quote it
        if (rest && /[()&<>|{}/\\]/.test(rest) && !rest.startsWith('"')) {
          const indent = line.match(/^(\s*)/)?.[1] || '';
          return `${indent}subgraph "${rest.replace(/"/g, "'")}"`;
        }
        return line;
      }

      let fixed = line;

      // STEP 1: Sanitize edge labels  -->|label with (parens)|
      // Remove parens and other shape-triggering chars from inside |...|
      fixed = fixed.replace(
        /(\-\->|\-\-\-|\-\.->|==>|~~>)\|([^|]*)\|/g,
        (_match, arrow, label) => {
          // Strip () {} [] <> from edge labels — they confuse the parser
          const clean = label.replace(/[(){}[\]<>]/g, '').replace(/\s+/g, ' ').trim();
          return `${arrow}|${clean}|`;
        }
      );

      // STEP 2: Quote node labels in [] that contain special chars
      // K[Kafka Topic(s)] → K["Kafka Topic(s)"]
      fixed = fixed.replace(
        /(\b\w+)\[([^\]]+)\]/g,
        (match, nodeId, label) => {
          if (label.startsWith('"') && label.endsWith('"')) return match;
          if (/[()&<>|{}/\\]/.test(label)) {
            return `${nodeId}["${label.replace(/"/g, "'")}"]`;
          }
          return match;
        }
      );

      // STEP 3: Quote node labels in () that contain special chars
      // But don't touch simple rounded nodes like: A(Simple Label)
      fixed = fixed.replace(
        /(\b\w+)\(([^)]+)\)/g,
        (match, nodeId, label) => {
          if (label.startsWith('"') && label.endsWith('"')) return match;
          if (/[&<>|{}/\\]/.test(label)) {
            return `${nodeId}("${label.replace(/"/g, "'")}")`;
          }
          return match;
        }
      );

      // STEP 4: Quote node labels in {} that contain special chars
      fixed = fixed.replace(
        /(\b\w+)\{([^}]+)\}/g,
        (match, nodeId, label) => {
          if (label.startsWith('"') && label.endsWith('"')) return match;
          if (/[()&<>|/\\]/.test(label)) {
            return `${nodeId}{"${label.replace(/"/g, "'")}"}`;
          }
          return match;
        }
      );

      // STEP 5: Escape raw & anywhere that survived
      fixed = fixed.replace(/&(?!amp;|lt;|gt;|quot;|#)/g, '&amp;');

      return fixed;
    })
    .join('\n');
}

export default function MermaidBlock({ code }: { code: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [svgContent, setSvgContent] = useState<string>('');
  const [showPopup, setShowPopup] = useState(false);

  useEffect(() => {
    const id = `mermaid-${++_id}`;
    let cancelled = false;

    const sanitized = sanitizeMermaidCode(code);

    // Render into a temporary off-screen container so mermaid's error SVGs
    // (bomb icons + "Syntax error in text") never appear in the visible DOM.
    const tempContainer = document.createElement('div');
    tempContainer.style.position = 'absolute';
    tempContainer.style.left = '-9999px';
    tempContainer.style.top = '-9999px';
    document.body.appendChild(tempContainer);

    mermaid.render(id, sanitized, tempContainer)
      .then(({ svg }) => {
        if (!cancelled) {
          setSvgContent(svg);
          if (containerRef.current) containerRef.current.innerHTML = svg;
        }
      })
      .catch((err) => {
        if (!cancelled) setError(String(err));
      })
      .finally(() => {
        // Clean up the temp container and any error elements mermaid injected.
        // Mermaid v11 injects error SVGs directly into document.body — remove them all.
        tempContainer.remove();
        document.getElementById(`d${id}`)?.remove();
        document.getElementById(id)?.remove();
        // Mermaid v11 also creates elements with id like "dmermaid-N"
        document.querySelectorAll(`[id^="d${id}"], [id="${id}"]`).forEach(el => el.remove());
        // Clean up any stray mermaid error SVGs that escaped containment
        document.querySelectorAll('svg[id^="mermaid-"] > g > text').forEach(el => {
          if (el.textContent?.includes('Syntax error')) {
            el.closest('svg')?.remove();
          }
        });
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
      <div className="my-2 rounded-lg overflow-hidden border border-amber-200 bg-amber-50">
        <div className="flex items-center justify-between px-3 py-1.5 bg-amber-100 border-b border-amber-200">
          <span className="text-[10px] font-mono text-amber-600">mermaid — could not render diagram</span>
          <button onClick={handleCopy} className="text-[10px] text-amber-500 hover:text-amber-700">
            {copied ? 'Copied!' : 'Copy Source'}
          </button>
        </div>
        <pre className="p-3 text-xs font-mono overflow-x-auto text-gray-700 whitespace-pre-wrap">{code}</pre>
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

      {showPopup && (
        <DiagramViewer
          svgContent={svgContent}
          onClose={() => setShowPopup(false)}
          onCopy={handleCopy}
          onDownload={handleDownloadSvg}
          copied={copied}
        />
      )}
    </>
  );
}
