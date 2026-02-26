'use client';

import { useEffect, useRef } from 'react';
import type { WSMessage } from '@/lib/websocket';

interface SessionLogProps {
  messages: WSMessage[];
  connected: boolean;
}

function MessageEntry({ msg }: { msg: WSMessage }) {
  const typeColors: Record<string, string> = {
    turn: 'text-blue-600',
    llm_response: 'text-gray-800',
    file_changed: 'text-amber-600',
    complete: 'text-green-600',
    error: 'text-red-600',
  };

  const color = typeColors[msg.type] || 'text-gray-600';

  if (msg.type === 'turn') {
    return (
      <div className={`${color} font-mono text-sm`}>
        <span className="font-bold">Turn {msg.data.turn}</span>
        {msg.data.tool && (
          <span className="ml-2 text-gray-500">
            [{msg.data.tool}]
          </span>
        )}
      </div>
    );
  }

  if (msg.type === 'file_changed') {
    return (
      <div className={`${color} font-mono text-sm`}>
        <span className="font-bold">{msg.data.action}</span>{' '}
        {msg.data.path}
      </div>
    );
  }

  if (msg.type === 'llm_response') {
    return (
      <div className={`${color} text-sm whitespace-pre-wrap`}>
        {msg.data.content}
      </div>
    );
  }

  if (msg.type === 'complete') {
    return (
      <div className={`${color} font-bold text-sm border-t border-green-200 pt-2 mt-2`}>
        Session complete
        {msg.data.result?.summary && (
          <p className="font-normal mt-1">{msg.data.result.summary}</p>
        )}
      </div>
    );
  }

  if (msg.type === 'error') {
    return (
      <div className={`${color} text-sm`}>
        Error: {msg.data.message || JSON.stringify(msg.data)}
      </div>
    );
  }

  return (
    <div className="text-gray-500 text-sm font-mono">
      [{msg.type}] {JSON.stringify(msg.data)}
    </div>
  );
}

export default function SessionLog({ messages, connected }: SessionLogProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  return (
    <div className="bg-gray-900 rounded-lg p-4 h-[500px] overflow-y-auto">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-white text-sm font-semibold">Live Session Log</h3>
        <span
          className={`px-2 py-0.5 rounded-full text-xs font-medium ${
            connected
              ? 'bg-green-100 text-green-700'
              : 'bg-gray-200 text-gray-600'
          }`}
        >
          {connected ? 'Connected' : 'Disconnected'}
        </span>
      </div>
      <div className="space-y-2 bg-gray-800 rounded p-3">
        {messages.length === 0 ? (
          <p className="text-gray-400 text-sm italic">
            {connected ? 'Waiting for events...' : 'Not connected'}
          </p>
        ) : (
          messages.map((msg, i) => (
            <div key={i} className="bg-gray-700 rounded px-3 py-2">
              <MessageEntry msg={msg} />
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
