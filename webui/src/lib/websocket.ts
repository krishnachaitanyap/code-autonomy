/**
 * WebSocket hook for live session streaming.
 */

import { useEffect, useRef, useState, useCallback } from 'react';

export interface WSMessage {
  type: string;
  data: Record<string, any>;
}

function getWsBase(): string {
  if (process.env.NEXT_PUBLIC_WS_URL) return process.env.NEXT_PUBLIC_WS_URL;
  if (typeof window !== 'undefined') {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${proto}//${window.location.host}/api`;
  }
  return 'ws://localhost:8000/api';
}

export function useSessionStream(sessionId: string | null) {
  const [messages, setMessages] = useState<WSMessage[]>([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectAttemptRef = useRef(0);

  const clearMessages = useCallback(() => setMessages([]), []);

  const connect = useCallback(() => {
    if (!sessionId) return;
    // Don't reconnect if already connected
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) return;

    const ws = new WebSocket(`${getWsBase()}/sessions/${sessionId}/stream`);
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      reconnectAttemptRef.current = 0;
    };

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
      // Reconnect with exponential backoff (max 10s)
      if (sessionId) {
        const delay = Math.min(1000 * Math.pow(2, reconnectAttemptRef.current), 10000);
        reconnectAttemptRef.current += 1;
        reconnectTimerRef.current = setTimeout(() => {
          connect();
        }, delay);
      }
    };

    ws.onerror = () => {
      setConnected(false);
    };
  }, [sessionId]);

  const disconnect = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    reconnectAttemptRef.current = 0;
    wsRef.current?.close();
    wsRef.current = null;
    setConnected(false);
  }, []);

  useEffect(() => {
    connect();
    return () => disconnect();
  }, [connect, disconnect]);

  return { messages, connected, disconnect, clearMessages };
}
