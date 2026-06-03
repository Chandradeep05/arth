'use client';

import { useState, useEffect, useCallback } from 'react';

type ConnectionStatus = 'connected' | 'reconnecting' | 'disconnected';

const statusConfig: Record<ConnectionStatus, { dot: string; label: string }> = {
  connected: { dot: 'bg-[var(--green)]', label: 'Connected' },
  reconnecting: { dot: 'bg-[var(--gold)]', label: 'Reconnecting...' },
  disconnected: { dot: 'bg-[var(--red)]', label: 'Disconnected' },
};

function formatTime(date: Date): string {
  return date.toLocaleTimeString('en-IN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

export default function StatusBar() {
  const [connectionStatus] = useState<ConnectionStatus>('connected');
  const [lastUpdated, setLastUpdated] = useState<string>('');

  const updateTime = useCallback(() => {
    setLastUpdated(formatTime(new Date()));
  }, []);

  useEffect(() => {
    updateTime();
    const interval = setInterval(updateTime, 1_000);
    return () => clearInterval(interval);
  }, [updateTime]);

  const { dot, label } = statusConfig[connectionStatus];

  return (
    <footer
      className="
        fixed bottom-0 right-0 z-30
        flex items-center justify-between
        h-8 px-6
        left-16 lg:left-60
        bg-[var(--bg)]/90 backdrop-blur-sm
        border-t border-[var(--border)]
        font-mono text-[10px]
        select-none
        transition-all duration-250
      "
    >
      {/* Left: Connection status */}
      <div className="flex items-center gap-2">
        <span className={`inline-block h-1.5 w-1.5 rounded-full ${dot}`} />
        <span className="text-[var(--text-muted)]">{label}</span>
      </div>

      {/* Center: Data source info */}
      <div className="text-[var(--text-dim)]">
        Data delayed ~15s &nbsp;|&nbsp; Sources: Yahoo Finance
      </div>

      {/* Right: Last updated */}
      <div className="text-[var(--text-muted)]">
        Last updated: {lastUpdated}
      </div>
    </footer>
  );
}
