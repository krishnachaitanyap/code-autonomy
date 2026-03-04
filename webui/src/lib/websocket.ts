/**
 * WebSocket hook for live session streaming with auto-reconnect.
 */

import { useEffect, useRef, useState, useCallback } from 'react';

const MAX_RECONNECT_ATTEMPTS = 20;
const MAX_BACKOFF_MS = 15_000;
const INITIAL_BACKOFF_MS = 1_000;

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
  const [reconnecting, setReconnecting] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectAttemptRef = useRef(0);
  // Track whether the hook is still mounted / active for this sessionId
  const activeRef = useRef(true);

  const clearMessages = useCallback(() => setMessages([]), []);

  const scheduleReconnect = useCallback(() => {
    if (!activeRef.current) return;
    if (reconnectAttemptRef.current >= MAX_RECONNECT_ATTEMPTS) {
      setReconnecting(false);
      console.warn(`[ws] Gave up reconnecting after ${MAX_RECONNECT_ATTEMPTS} attempts`);
      return;
    }
    const delay = Math.min(
      INITIAL_BACKOFF_MS * Math.pow(2, reconnectAttemptRef.current),
      MAX_BACKOFF_MS,
    );
    reconnectAttemptRef.current += 1;
    setReconnecting(true);
    console.info(`[ws] Reconnecting in ${delay}ms (attempt ${reconnectAttemptRef.current}/${MAX_RECONNECT_ATTEMPTS})`);
    reconnectTimerRef.current = setTimeout(() => {
      if (activeRef.current) connect();
    }, delay);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const connect = useCallback(() => {
    if (!sessionId) return;
    // Don't reconnect if already open or connecting
    if (
      wsRef.current &&
      (wsRef.current.readyState === WebSocket.OPEN ||
       wsRef.current.readyState === WebSocket.CONNECTING)
    ) return;

    let ws: WebSocket;
    try {
      ws = new WebSocket(`${getWsBase()}/sessions/${sessionId}/stream`);
    } catch {
      // Constructor can throw on invalid URL / blocked connections
      scheduleReconnect();
      return;
    }
    wsRef.current = ws;

    ws.onopen = () => {
      setConnected(true);
      setReconnecting(false);
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
      if (activeRef.current && sessionId) {
        scheduleReconnect();
      }
    };

    ws.onerror = () => {
      // onerror is always followed by onclose in browsers, but close the
      // socket explicitly to be safe and let onclose handle the reconnect.
      setConnected(false);
      ws.close();
    };
  }, [sessionId, scheduleReconnect]);

  const disconnect = useCallback(() => {
    activeRef.current = false;
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    reconnectAttemptRef.current = 0;
    setReconnecting(false);
    wsRef.current?.close();
    wsRef.current = null;
    setConnected(false);
  }, []);

  useEffect(() => {
    activeRef.current = true;
    connect();
    return () => disconnect();
  }, [connect, disconnect]);

  return { messages, connected, reconnecting, disconnect, clearMessages };
}
