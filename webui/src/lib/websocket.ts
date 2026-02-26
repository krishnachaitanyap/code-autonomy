/**
 * WebSocket hook for live session streaming.
 */

import { useEffect, useRef, useState, useCallback } from 'react';

export interface WSMessage {
  type: string;
  data: Record<string, any>;
}

const WS_BASE = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000/api';

export function useSessionStream(sessionId: string | null) {
  const [messages, setMessages] = useState<WSMessage[]>([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  const connect = useCallback(() => {
    if (!sessionId) return;

    const ws = new WebSocket(`${WS_BASE}/sessions/${sessionId}/stream`);
    wsRef.current = ws;

    ws.onopen = () => setConnected(true);

    ws.onmessage = (event) => {
      try {
        const msg: WSMessage = JSON.parse(event.data);
        setMessages((prev) => [...prev, msg]);
      } catch {
        // Ignore malformed messages
      }
    };

    ws.onclose = () => {
      setConnected(false);
      wsRef.current = null;
    };

    ws.onerror = () => {
      setConnected(false);
    };
  }, [sessionId]);

  const disconnect = useCallback(() => {
    wsRef.current?.close();
    wsRef.current = null;
    setConnected(false);
  }, []);

  useEffect(() => {
    connect();
    return () => disconnect();
  }, [connect, disconnect]);

  return { messages, connected, disconnect };
}
