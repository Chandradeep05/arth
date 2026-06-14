'use client';

import { useState, useEffect, useCallback } from 'react';
import { motion } from 'framer-motion';
import { Activity, Database, Server, Wifi, RefreshCw, CheckCircle, XCircle, AlertTriangle } from 'lucide-react';
import { apiClient } from '@/lib/api';

interface ServiceHealth {
  status: string;
  service: string;
  latency_ms?: number;
  message?: string;
  timestamp: string;
}

interface SystemHealthData {
  status: string;
  version: string;
  environment: string;
  services: Record<string, ServiceHealth>;
  timestamp: string;
}

function StatusDot({ status }: { status: string }) {
  const color =
    status === 'healthy' || status === 'operational' ? 'bg-[var(--green)]' :
    status === 'degraded' ? 'bg-[var(--gold)]' :
    status === 'not_provisioned' ? 'bg-[var(--text-dim)]' :
    'bg-[var(--red)]';
  return <div className={`w-2.5 h-2.5 rounded-full ${color} ${status === 'not_provisioned' ? '' : 'animate-pulse-dot'}`} />;
}

function StatusIcon({ status }: { status: string }) {
  if (status === 'healthy' || status === 'operational') return <CheckCircle className="w-5 h-5 text-[var(--green)]" />;
  if (status === 'degraded') return <AlertTriangle className="w-5 h-5 text-[var(--gold)]" />;
  return <XCircle className="w-5 h-5 text-[var(--red)]" />;
}

export default function SystemPage() {
  const [health, setHealth] = useState<SystemHealthData | null>(null);
  const [adapterHealth, setAdapterHealth] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [lastFetched, setLastFetched] = useState<Date>(new Date());

  const fetchHealth = useCallback(async () => {
    try {
      const [sysRes, adapterRes] = await Promise.allSettled([
        apiClient.get<SystemHealthData>('/api/v1/system/health'),
        apiClient.get<any>('/api/v1/market/health'),
      ]);
      if (sysRes.status === 'fulfilled') setHealth(sysRes.value);
      if (adapterRes.status === 'fulfilled') setAdapterHealth(adapterRes.value);
    } catch {
      // graceful
    } finally {
      setLoading(false);
      setLastFetched(new Date());
    }
  }, []);

  useEffect(() => {
    fetchHealth();
    const interval = setInterval(fetchHealth, 30_000);
    return () => clearInterval(interval);
  }, [fetchHealth]);

  return (
    <div className="space-y-8 animate-fadeIn">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-heading text-xl font-extrabold tracking-tight text-[var(--text)]">
            System Health
          </h1>
          <p className="text-sm text-[var(--text-muted)] mt-1 font-mono">
            Infrastructure monitoring · Auto-refresh 30s
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-[11px] font-mono text-[var(--text-dim)]">
            {lastFetched.toLocaleTimeString()}
          </span>
          <button
            onClick={fetchHealth}
            className="p-2 rounded hover:bg-[var(--surface-2)] text-[var(--text-muted)] hover:text-[var(--accent)] transition-colors cursor-pointer"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Overall Status */}
      {health && (
        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="card p-5"
        >
          <div className="flex items-center gap-4">
            <StatusIcon status={health.status} />
            <div>
              <div className="font-heading text-lg font-bold text-[var(--text)] capitalize">
                {health.status === 'operational' ? 'System Operational (Lite Mode)' : `System ${health.status}`}
              </div>
              <div className="text-xs font-mono text-[var(--text-dim)]">
                v{health.version} · {health.environment}
              </div>
            </div>
          </div>
        </motion.div>
      )}

      {/* Service Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
        {/* Database */}
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }} className="card p-5">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <Database className="w-4 h-4 text-[var(--accent-purple)]" />
              <span className="font-heading text-sm font-bold text-[var(--text)]">TimescaleDB</span>
            </div>
            <StatusDot status={
              health?.services?.database?.status === 'healthy' ? 'healthy' :
              health?.services?.database?.message === 'Engine not initialized' ? 'not_provisioned' : 'unhealthy'
            } />
          </div>
          <div className="space-y-1 text-xs font-mono">
            <div className="flex justify-between">
              <span className="text-[var(--text-dim)]">Status</span>
              <span className="text-[var(--text-muted)] capitalize">
                {health?.services?.database?.message === 'Engine not initialized'
                  ? 'Not provisioned'
                  : (health?.services?.database?.status ?? 'offline')}
              </span>
            </div>
            {health?.services?.database?.latency_ms && (
              <div className="flex justify-between">
                <span className="text-[var(--text-dim)]">Latency</span>
                <span className="text-[var(--text-muted)]">{health.services.database.latency_ms}ms</span>
              </div>
            )}
            {health?.services?.database?.message && health.services.database.message !== 'Engine not initialized' && (
              <p className="text-[var(--red)] text-[10px] mt-2 break-all">{health.services.database.message}</p>
            )}
            {health?.services?.database?.message === 'Engine not initialized' && (
              <p className="text-[var(--text-dim)] text-[10px] mt-2">Optional — system operates without DB in lite mode</p>
            )}
          </div>
        </motion.div>

        {/* Redis */}
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.2 }} className="card p-5">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <Server className="w-4 h-4 text-[var(--accent-orange)]" />
              <span className="font-heading text-sm font-bold text-[var(--text)]">Redis Cache</span>
            </div>
            <StatusDot status={
              health?.services?.redis?.status === 'healthy' ? 'healthy' :
              health?.services?.redis?.message === 'Client not initialized' ? 'not_provisioned' : 'unhealthy'
            } />
          </div>
          <div className="space-y-1 text-xs font-mono">
            <div className="flex justify-between">
              <span className="text-[var(--text-dim)]">Status</span>
              <span className="text-[var(--text-muted)] capitalize">
                {health?.services?.redis?.message === 'Client not initialized'
                  ? 'Not provisioned'
                  : (health?.services?.redis?.status ?? 'offline')}
              </span>
            </div>
            {health?.services?.redis?.latency_ms && (
              <div className="flex justify-between">
                <span className="text-[var(--text-dim)]">Latency</span>
                <span className="text-[var(--text-muted)]">{health.services.redis.latency_ms}ms</span>
              </div>
            )}
            {health?.services?.redis?.message === 'Client not initialized' && (
              <p className="text-[var(--text-dim)] text-[10px] mt-2">Optional — serving fresh data without cache</p>
            )}
          </div>
        </motion.div>

        {/* Yahoo Finance */}
        <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.3 }} className="card p-5">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <Wifi className="w-4 h-4 text-[var(--green)]" />
              <span className="font-heading text-sm font-bold text-[var(--text)]">Yahoo Finance</span>
            </div>
            <StatusDot status={adapterHealth?.status === 'healthy' ? 'healthy' : 'degraded'} />
          </div>
          <div className="space-y-1 text-xs font-mono">
            <div className="flex justify-between">
              <span className="text-[var(--text-dim)]">Status</span>
              <span className="text-[var(--text-muted)] capitalize">{adapterHealth?.status ?? 'checking...'}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-[var(--text-dim)]">Circuit</span>
              <span className="text-[var(--text-muted)]">{adapterHealth?.adapter?.circuit_state ?? '—'}</span>
            </div>
            {adapterHealth?.adapter?.avg_latency_ms > 0 && (
              <div className="flex justify-between">
                <span className="text-[var(--text-dim)]">Avg Latency</span>
                <span className="text-[var(--text-muted)]">{adapterHealth.adapter.avg_latency_ms}ms</span>
              </div>
            )}
            <div className="flex justify-between">
              <span className="text-[var(--text-dim)]">Requests</span>
              <span className="text-[var(--text-muted)]">{adapterHealth?.adapter?.total_requests ?? 0}</span>
            </div>
          </div>
        </motion.div>
      </div>

      {/* Platform Info */}
      <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.5 }} className="card p-5 max-w-xl">
        <h3 className="font-heading text-sm font-bold uppercase tracking-wider text-[var(--text-muted)] mb-3">
          Platform Info
        </h3>
        <div className="space-y-2 text-xs font-mono">
          {[
            ['Application', 'ARTH v2.0.0'],
            ['Backend', 'FastAPI + Uvicorn'],
            ['Frontend', 'Next.js 16 (Turbopack)'],
            ['LLM Provider', 'Groq (Llama 3.3 70B)'],
            ['Data Source', 'Yahoo Finance (~15s delay)'],
            ['Phase', '2 — Intelligence Expansion'],
          ].map(([label, value]) => (
            <div key={label} className="flex justify-between">
              <span className="text-[var(--text-dim)]">{label}</span>
              <span className="text-[var(--text-muted)]">{value}</span>
            </div>
          ))}
        </div>
      </motion.div>
    </div>
  );
}
