'use client';

import { useEffect, useRef } from 'react';

/**
 * Backend Keep-Alive Hook
 * 
 * Pings the backend /health endpoint every 4 minutes to prevent
 * Render free-tier cold starts. Only runs in production.
 * 
 * Uses a simple fetch with no-cors to avoid CORS issues.
 * The ping is fire-and-forget — failures are silently ignored.
 */

const PING_INTERVAL_MS = 4 * 60 * 1000; // 4 minutes

export function useBackendKeepAlive() {
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    // Only run in production (not localhost dev)
    if (typeof window === 'undefined') return;
    if (window.location.hostname === 'localhost') return;

    const backendUrl = process.env.NEXT_PUBLIC_API_URL || 'https://arth-rdd5.onrender.com';
    const healthUrl = `${backendUrl}/health`;

    const ping = () => {
      fetch(healthUrl, { method: 'GET', mode: 'no-cors' }).catch(() => {
        // Silently ignore — this is a best-effort keepalive
      });
    };

    // Initial ping on mount to warm up backend immediately
    ping();

    // Then ping every 4 minutes
    intervalRef.current = setInterval(ping, PING_INTERVAL_MS);

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, []);
}
