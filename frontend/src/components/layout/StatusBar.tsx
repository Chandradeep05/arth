'use client';

import { useState, useEffect, useCallback } from 'react';
import { apiClient } from '@/lib/api';

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

interface MarketHealthData {
  status: string;
  active_sources?: string[];
  markets?: {
    india?: { state: string; session: string; exchange: string };
    us?: { state: string; session: string; exchange: string };
  };
}

export default function StatusBar() {
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>('connected');
  const [lastUpdated, setLastUpdated] = useState<string>('');
  const [marketInfo, setMarketInfo] = useState<string>('Connecting to market feed...');

  const updateTime = useCallback(() => {
    setLastUpdated(formatTime(new Date()));
  }, []);

  const fetchHealth = useCallback(async () => {
    try {
      const data = await apiClient.get<MarketHealthData>('/api/v1/market/health');
      setConnectionStatus(data?.status === 'healthy' ? 'connected' : 'reconnecting');

      const sources = data?.active_sources?.length
        ? data.active_sources.join(' / ')
        : 'unavailable';
      const indiaState = data?.markets?.india?.state === 'open' ? 'NSE Open' : 'NSE Closed';
      const usState = data?.markets?.us?.state === 'open' ? 'US Open' : 'US Closed';

      setMarketInfo(`Sources: ${sources} \u00a0|\u00a0 ${indiaState} \u00a0|\u00a0 ${usState}`);
    } catch {
      setConnectionStatus('disconnected');
      setMarketInfo('Offline \u00a0|\u00a0 Retrying connection...');
    }
  }, []);

  useEffect(() => {
    updateTime();
    fetchHealth();
    const timeInterval = setInterval(updateTime, 1_000);
    const healthInterval = setInterval(fetchHealth, 30_000);
    return () => {
      clearInterval(timeInterval);
      clearInterval(healthInterval);
    };
  }, [updateTime, fetchHealth]);

  const { dot, label } = statusConfig[connectionStatus];

  return (
    <footer
      className="
        fixed bottom-0 right-0 z-30
        flex items-center justify-between
        h-7 px-6
        left-0 lg:left-16 xl:left-60
        bg-[#060908]/90 backdrop-blur-md
        border-t border-white/[0.05]
        font-mono text-[10px]
        select-none
        transition-all duration-200
      "
    >
      {/* Left: Connection status */}
      <div className="flex items-center gap-2">
        <span className={`inline-block h-1.5 w-1.5 rounded-full ${dot}`} />
        <span className="text-[var(--text-dim)]">{label}</span>
      </div>

      {/* Center: Dynamic market and provider info */}
      <div className="text-[var(--text-dim)] hidden sm:block truncate max-w-[60%] text-center">
        {marketInfo}
      </div>

      {/* Right: Last updated */}
      <div className="text-[var(--text-dim)]">
        Last updated: {lastUpdated}
      </div>
    </footer>
  );
}
