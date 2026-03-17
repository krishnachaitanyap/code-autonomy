'use client';

import { useEffect, useState, useRef } from 'react';
import { models, type ModelConfig } from '@/lib/api';

const PROVIDER_COLORS: Record<string, { bg: string; text: string; dot: string }> = {
  openai:    { bg: 'bg-green-100', text: 'text-green-700', dot: 'bg-green-500' },
  anthropic: { bg: 'bg-orange-100', text: 'text-orange-700', dot: 'bg-orange-500' },
  gemini:    { bg: 'bg-blue-100', text: 'text-blue-700', dot: 'bg-blue-500' },
  google:    { bg: 'bg-blue-100', text: 'text-blue-700', dot: 'bg-blue-500' },
  azure:     { bg: 'bg-cyan-100', text: 'text-cyan-700', dot: 'bg-cyan-500' },
  bedrock:   { bg: 'bg-purple-100', text: 'text-purple-700', dot: 'bg-purple-500' },
  cdao:      { bg: 'bg-purple-100', text: 'text-purple-700', dot: 'bg-purple-500' },
};

function getProviderStyle(provider: string) {
  return PROVIDER_COLORS[provider] || { bg: 'bg-gray-100', text: 'text-gray-700', dot: 'bg-gray-500' };
}

interface ModelSelectorProps {
  selectedModelId: string;
  onChange: (modelId: string, configOverrides: Record<string, any>) => void;
  storageKey?: string;
}

export default function ModelSelector({ selectedModelId, onChange, storageKey }: ModelSelectorProps) {
  const [modelList, setModelList] = useState<ModelConfig[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    models.list()
      .then((r) => {
        setModelList(r.models || []);
        // Restore from localStorage
        if (storageKey && !selectedModelId) {
          const saved = localStorage.getItem(storageKey);
          if (saved && r.models.some(m => m.id === saved)) {
            const model = r.models.find(m => m.id === saved);
            if (model) {
              onChange(model.id, buildOverrides(model));
            }
          }
        }
      })
      .catch(() => setModelList([]))
      .finally(() => setLoading(false));
  }, []);

  // Close on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    if (open) document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [open]);

  function buildOverrides(model: ModelConfig): Record<string, any> {
    const ai: Record<string, any> = {
      provider: model.provider,
      model: model.model,
    };
    if (model.base_url) ai.base_url = model.base_url;
    // Spread extra_config (Bedrock: aws_account_number, aws_region, workspace_id, is_execution_role; Azure: endpoint, deployment_name)
    if (model.extra_config) {
      Object.assign(ai, model.extra_config);
    }
    return { ai };
  }

  function handleSelect(model: ModelConfig | null) {
    if (!model) {
      // "Default" selected
      onChange('', {});
      if (storageKey) localStorage.removeItem(storageKey);
    } else {
      onChange(model.id, buildOverrides(model));
      if (storageKey) localStorage.setItem(storageKey, model.id);
    }
    setOpen(false);
  }

  const selected = modelList.find(m => m.id === selectedModelId);

  if (loading) {
    return <div className="px-2 py-1 text-xs text-gray-400">...</div>;
  }

  if (modelList.length === 0) return null;

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 px-2.5 py-1.5 text-xs border border-gray-300 rounded-lg hover:bg-gray-50 transition-colors"
      >
        {selected ? (
          <>
            <span className={`w-2 h-2 rounded-full ${getProviderStyle(selected.provider).dot}`} />
            <span className="font-medium text-gray-700 max-w-[120px] truncate">{selected.label}</span>
          </>
        ) : (
          <>
            <span className="w-2 h-2 rounded-full bg-gray-400" />
            <span className="text-gray-500">Default Model</span>
          </>
        )}
        <svg className={`w-3 h-3 text-gray-400 transition-transform ${open ? 'rotate-180' : ''}`} fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open && (
        <div className="absolute z-50 mt-1 w-64 bg-white border border-gray-200 rounded-lg shadow-lg py-1 max-h-80 overflow-y-auto">
          {/* Default option */}
          <button
            onClick={() => handleSelect(null)}
            className={`w-full text-left px-3 py-2 text-sm hover:bg-gray-50 flex items-center gap-2 ${
              !selectedModelId ? 'bg-gray-50 font-medium' : ''
            }`}
          >
            <span className="w-2 h-2 rounded-full bg-gray-400" />
            <div>
              <div className="text-gray-700">Default (config.ini)</div>
              <div className="text-[10px] text-gray-400">Uses global configuration</div>
            </div>
          </button>

          <div className="border-t border-gray-100 my-1" />

          {/* Model list */}
          {modelList.map(m => {
            const style = getProviderStyle(m.provider);
            return (
              <button
                key={m.id}
                onClick={() => handleSelect(m)}
                className={`w-full text-left px-3 py-2 text-sm hover:bg-gray-50 flex items-center gap-2 ${
                  selectedModelId === m.id ? 'bg-indigo-50' : ''
                }`}
              >
                <span className={`w-2 h-2 rounded-full flex-shrink-0 ${style.dot}`} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-1.5">
                    <span className="font-medium text-gray-700 truncate">{m.label}</span>
                    {m.is_default && (
                      <span className="px-1 py-0.5 text-[9px] bg-yellow-100 text-yellow-700 rounded">default</span>
                    )}
                  </div>
                  <div className="flex items-center gap-1.5 mt-0.5">
                    <span className={`px-1.5 py-0.5 text-[10px] rounded ${style.bg} ${style.text}`}>
                      {m.provider}
                    </span>
                    <span className="text-[10px] text-gray-400 truncate">{m.model}</span>
                  </div>
                </div>
              </button>
            );
          })}

          <div className="border-t border-gray-100 my-1" />
          <a
            href="/config"
            className="block px-3 py-2 text-xs text-indigo-600 hover:bg-indigo-50"
          >
            Manage Models...
          </a>
        </div>
      )}
    </div>
  );
}
