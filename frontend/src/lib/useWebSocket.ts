'use client';

import { useState, useEffect, useRef, useCallback } from 'react';
import {
  WS_BASE_URL,
  WS_RECONNECT_BASE_DELAY,
  WS_RECONNECT_MAX_DELAY,
} from './constants';

/* ── Types ── */
export interface PriceUpdate {
  symbol: string;
  price: number;
  change: number;
  change_percent: number;
  volume: number;
  high: number;
  low: number;
  timestamp: string;
}

export type WSStatus = 'connecting' | 'connected' | 'disconnected' | 'reconnecting';

interface WSMessage {
  type: string;
  symbol?: string;
  data?: PriceUpdate;
  [key: string]: unknown;
}

/* ── Hook ── */
export function useWebSocket(initialSymbols?: string[]) {
  const [status, setStatus] = useState<WSStatus>('disconnected');
  const [prices, setPrices] = useState<Map<string, PriceUpdate>>(new Map());
  const [lastUpdate, setLastUpdate] = useState<Date | null>(null);

  // Refs for stable values across reconnects
  const wsRef = useRef<WebSocket | null>(null);
  const subscribedSymbolsRef = useRef<Set<string>>(new Set(initialSymbols ?? []));
  const reconnectAttemptRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const unmountedRef = useRef(false);

  /* ── Send a JSON message to the WebSocket ── */
  const sendMessage = useCallback((msg: Record<string, unknown>) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(msg));
    }
  }, []);

  /* ── Subscribe to symbols ── */
  const subscribe = useCallback(
    (symbols: string[]) => {
      const newSymbols = symbols.filter((s) => !subscribedSymbolsRef.current.has(s));
      if (newSymbols.length === 0) return;

      newSymbols.forEach((s) => subscribedSymbolsRef.current.add(s));
      sendMessage({ action: 'subscribe', symbols: newSymbols });
    },
    [sendMessage],
  );

  /* ── Unsubscribe from symbols ── */
  const unsubscribe = useCallback(
    (symbols: string[]) => {
      symbols.forEach((s) => subscribedSymbolsRef.current.delete(s));
      sendMessage({ action: 'unsubscribe', symbols });
    },
    [sendMessage],
  );

  /* ── Connect to WebSocket ── */
  const connect = useCallback(() => {
    if (unmountedRef.current) return;

    // Clean up any existing connection
    if (wsRef.current) {
      wsRef.current.onopen = null;
      wsRef.current.onclose = null;
      wsRef.current.onerror = null;
      wsRef.current.onmessage = null;
      wsRef.current.close();
      wsRef.current = null;
    }

    setStatus(reconnectAttemptRef.current > 0 ? 'reconnecting' : 'connecting');

    try {
      const ws = new WebSocket(`${WS_BASE_URL}/ws/prices`);
      wsRef.current = ws;

      ws.onopen = () => {
        if (unmountedRef.current) return;
        setStatus('connected');
        reconnectAttemptRef.current = 0;

        // Re-subscribe to all tracked symbols
        const symbols = Array.from(subscribedSymbolsRef.current);
        if (symbols.length > 0) {
          sendMessage({ action: 'subscribe', symbols });
        }
      };

      ws.onmessage = (event) => {
        if (unmountedRef.current) return;

        try {
          const msg: WSMessage = JSON.parse(event.data);

          if (msg.type === 'price_update' && msg.data) {
            const update = msg.data;
            setPrices((prev) => {
              const next = new Map(prev);
              next.set(update.symbol, update);
              return next;
            });
            setLastUpdate(new Date());
          }
        } catch {
          // Ignore malformed messages
        }
      };

      ws.onclose = () => {
        if (unmountedRef.current) return;
        wsRef.current = null;
        setStatus('disconnected');
        scheduleReconnect();
      };

      ws.onerror = () => {
        // onerror is always followed by onclose, so reconnect is handled there.
        // Just close to trigger the onclose handler cleanly.
        ws.close();
      };
    } catch {
      // Connection creation failed — schedule reconnect
      setStatus('disconnected');
      scheduleReconnect();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sendMessage]);

  /* ── Exponential backoff reconnect ── */
  const scheduleReconnect = useCallback(() => {
    if (unmountedRef.current) return;

    const attempt = reconnectAttemptRef.current;
    const delay = Math.min(
      WS_RECONNECT_BASE_DELAY * Math.pow(2, attempt),
      WS_RECONNECT_MAX_DELAY,
    );

    reconnectAttemptRef.current = attempt + 1;
    setStatus('reconnecting');

    reconnectTimerRef.current = setTimeout(() => {
      if (!unmountedRef.current) {
        connect();
      }
    }, delay);
  }, [connect]);

  /* ── Lifecycle ── */
  useEffect(() => {
    unmountedRef.current = false;
    connect();

    return () => {
      unmountedRef.current = true;

      // Clear reconnect timer
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }

      // Close WebSocket
      if (wsRef.current) {
        wsRef.current.onopen = null;
        wsRef.current.onclose = null;
        wsRef.current.onerror = null;
        wsRef.current.onmessage = null;
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [connect]);

  return {
    status,
    prices,
    subscribe,
    unsubscribe,
    lastUpdate,
  };
}
