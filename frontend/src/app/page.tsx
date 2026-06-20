'use client';

import { useState, useEffect, useCallback } from 'react';
import { motion } from 'framer-motion';
import {
  TrendingUp,
  TrendingDown,
  Activity,
  BarChart3,
  RefreshCw,
} from 'lucide-react';
import Link from 'next/link';
import { apiClient } from '@/lib/api';
import { REFRESH_INTERVALS } from '@/lib/constants';
import { useWebSocket } from '@/lib/useWebSocket';
import type { WSStatus } from '@/lib/useWebSocket';
import DataFreshness from '@/components/shared/DataFreshness';
import LoadingSkeleton from '@/components/shared/LoadingSkeleton';
import type { MarketIndex } from '@/types/market';

/* ── Stocks to scan for gainers/losers ── */
const NIFTY_STOCKS = [
  'RELIANCE.NS', 'TCS.NS', 'HDFCBANK.NS', 'INFY.NS', 'ICICIBANK.NS',
  'SBIN.NS', 'BAJFINANCE.NS', 'WIPRO.NS', 'EICHERMOT.NS', 'ADANIENT.NS',
  'ITC.NS', 'KOTAKBANK.NS', 'LT.NS', 'HCLTECH.NS', 'AXISBANK.NS',
  'SUNPHARMA.NS', 'MARUTI.NS', 'TATASTEEL.NS', 'BHARTIARTL.NS', 'NTPC.NS',
  'POWERGRID.NS', 'HINDALCO.NS', 'DRREDDY.NS', 'CIPLA.NS', 'TECHM.NS',
  'ONGC.NS', 'JSWSTEEL.NS', 'DLF.NS', 'ZEEL.NS', 'BAJAJFINSV.NS',
];

interface StockMover {
  symbol: string;
  name: string;
  price: number;
  change: number;
  change_percent: number;
  volume: number;
}

/* ── Helper: format number with commas ── */
function formatNumber(n: number): string {
  return new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2 }).format(n);
}

function formatVolume(v: number): string {
  if (v >= 1_00_00_000) return `${(v / 1_00_00_000).toFixed(1)}Cr`;
  if (v >= 1_00_000) return `${(v / 1_00_000).toFixed(1)}L`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return v.toString();
}

/* ── Sector heatmap: 12 sectors mapped to stocks ── */
const SECTOR_MAP: Record<string, string[]> = {
  IT: ['TCS.NS', 'INFY.NS', 'WIPRO.NS', 'HCLTECH.NS', 'TECHM.NS'],
  Banking: ['HDFCBANK.NS', 'ICICIBANK.NS', 'SBIN.NS', 'KOTAKBANK.NS', 'AXISBANK.NS'],
  Auto: ['EICHERMOT.NS', 'MARUTI.NS'],
  Pharma: ['SUNPHARMA.NS', 'DRREDDY.NS', 'CIPLA.NS'],
  Energy: ['RELIANCE.NS', 'NTPC.NS', 'POWERGRID.NS', 'ONGC.NS'],
  FMCG: ['ITC.NS'],
  Metals: ['TATASTEEL.NS', 'HINDALCO.NS', 'JSWSTEEL.NS'],
  Realty: ['DLF.NS'],
  Infra: ['LT.NS', 'ADANIENT.NS'],
  Finance: ['BAJFINANCE.NS', 'BAJAJFINSV.NS'],
  Media: ['ZEEL.NS'],
  Telecom: ['BHARTIARTL.NS'],
};

/* ── Index Card Component ── */
function IndexCard({ index, delay }: { index: MarketIndex; delay: number }) {
  const change = index.change ?? 0;
  const changePct = index.change_percent ?? 0;
  const isPositive = change >= 0;
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: delay * 0.1, duration: 0.4 }}
      className="card p-5 group cursor-pointer"
    >
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-mono text-[var(--text-dim)] uppercase tracking-widest">
          {index.name}
        </span>
        <div className={`w-2 h-2 rounded-full animate-pulse-dot ${isPositive ? 'bg-[var(--green)]' : 'bg-[var(--red)]'}`} />
      </div>

      <div className="font-heading text-2xl font-extrabold tracking-tight text-[var(--text)] mb-1">
        {formatNumber(index.value ?? 0)}
      </div>

      <div className="flex items-center gap-2">
        {isPositive ? (
          <TrendingUp className="w-4 h-4 text-[var(--green)]" />
        ) : (
          <TrendingDown className="w-4 h-4 text-[var(--red)]" />
        )}
        <span className={`text-sm font-mono font-medium ${isPositive ? 'text-[var(--green)]' : 'text-[var(--red)]'}`}>
          {isPositive ? '+' : ''}{formatNumber(change)}
        </span>
        <span className={`text-xs font-mono ${isPositive ? 'text-[var(--green)]' : 'text-[var(--red)]'}`}>
          ({isPositive ? '+' : ''}{changePct.toFixed(2)}%)
        </span>
      </div>
    </motion.div>
  );
}

/* ── Sector Heatmap ── */
function SectorHeatmap({ sectors }: { sectors: { name: string; change: number }[] }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.5, duration: 0.4 }}
      className="card p-5"
    >
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-heading text-sm font-bold uppercase tracking-wider text-[var(--text-muted)]">
          Sector Heatmap
        </h3>
        <BarChart3 className="w-4 h-4 text-[var(--text-dim)]" />
      </div>

      <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-6 gap-1.5">
        {sectors.map((sector) => {
          const sectorChange = sector.change ?? 0;
          const isPositive = sectorChange >= 0;
          const intensity = Math.min(Math.abs(sectorChange) / 4, 1);
          const bg = isPositive
            ? `rgba(0, 212, 160, ${0.08 + intensity * 0.25})`
            : `rgba(255, 68, 68, ${0.08 + intensity * 0.25})`;

          return (
            <div
              key={sector.name}
              className="rounded px-3 py-2.5 text-center transition-all hover:scale-105 cursor-pointer"
              style={{ background: bg }}
            >
              <div className="text-[10px] font-mono uppercase tracking-wider text-[var(--text-muted)] mb-0.5">
                {sector.name}
              </div>
              <div className={`text-xs font-mono font-semibold ${isPositive ? 'text-[var(--green)]' : 'text-[var(--red)]'}`}>
                {isPositive ? '+' : ''}{sectorChange.toFixed(2)}%
              </div>
            </div>
          );
        })}
      </div>
    </motion.div>
  );
}

/* ── Movers Table ── */
function MoversTable({
  title,
  movers,
  type,
}: {
  title: string;
  movers: StockMover[];
  type: 'gainers' | 'losers';
}) {
  const color = type === 'gainers' ? 'var(--green)' : 'var(--red)';

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: type === 'gainers' ? 0.6 : 0.7, duration: 0.4 }}
      className="card overflow-hidden"
    >
      <div className="flex items-center justify-between px-5 py-3 border-b border-[var(--border)]">
        <h3 className="font-heading text-sm font-bold uppercase tracking-wider text-[var(--text-muted)]">
          {title}
        </h3>
        <span className="badge" style={{ background: `${color}15`, color }}>
          {type === 'gainers' ? '▲' : '▼'} Top 5
        </span>
      </div>

      <table className="data-table">
        <thead>
          <tr>
            <th>Symbol</th>
            <th className="text-right">Price</th>
            <th className="text-right">Change</th>
            <th className="text-right hidden sm:table-cell">Volume</th>
          </tr>
        </thead>
        <tbody>
          {movers.length === 0 ? (
            <tr>
              <td colSpan={4} className="text-center text-[var(--text-dim)] py-8 font-mono text-xs">
                Loading market data...
              </td>
            </tr>
          ) : (
            movers.map((stock) => (
              <tr key={stock.symbol} className="cursor-pointer">
                <td>
                  <Link href={`/markets/${encodeURIComponent(stock.symbol)}`} className="block">
                    <div className="font-mono text-[var(--accent)] text-sm font-medium">
                      {stock.symbol.replace('.NS', '').replace('.BO', '')}
                    </div>
                    <div className="text-[11px] text-[var(--text-dim)] truncate max-w-[140px]">
                      {stock.name}
                    </div>
                  </Link>
                </td>
                <td className="text-right font-mono text-sm">
                  ₹{formatNumber(stock.price ?? 0)}
                </td>
                <td className="text-right">
                  <div className={`font-mono text-sm font-medium ${(stock.change ?? 0) >= 0 ? 'text-[var(--green)]' : 'text-[var(--red)]'}`}>
                    {(stock.change ?? 0) >= 0 ? '+' : ''}{(stock.change_percent ?? 0).toFixed(2)}%
                  </div>
                </td>
                <td className="text-right hidden sm:table-cell text-[var(--text-dim)] font-mono text-xs">
                  {formatVolume(stock.volume ?? 0)}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </motion.div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   Dashboard Home Page
   ═══════════════════════════════════════════════════════════════ */
/* ── WebSocket status badge ── */
const WS_BADGE: Record<WSStatus, { dot: string; label: string; bg: string; color: string }> = {
  connected:     { dot: '🟢', label: 'Live',         bg: 'rgba(0,212,160,0.15)', color: 'var(--green)' },
  reconnecting:  { dot: '🟡', label: 'Reconnecting', bg: 'rgba(255,180,0,0.15)', color: 'var(--accent-orange)' },
  connecting:    { dot: '🟡', label: 'Connecting',   bg: 'rgba(255,180,0,0.15)', color: 'var(--accent-orange)' },
  disconnected:  { dot: '🔴', label: 'Offline',      bg: 'rgba(255,68,68,0.15)', color: 'var(--red)' },
};

export default function DashboardPage() {
  const [indices, setIndices] = useState<MarketIndex[]>([]);
  const [gainers, setGainers] = useState<StockMover[]>([]);
  const [losers, setLosers] = useState<StockMover[]>([]);
  const [sectors, setSectors] = useState<{ name: string; change: number }[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date>(new Date());
  const [apiConnected, setApiConnected] = useState(false);

  // WebSocket connection for real-time price streaming
  const { status: wsStatus } = useWebSocket();

  const fetchDashboard = useCallback(async () => {
    try {
      // 1. Fetch indices
      const indicesRes = await apiClient.get<{ indices: MarketIndex[] }>('/api/v1/market/indices');
      if (indicesRes.indices && indicesRes.indices.length > 0) {
        setIndices(indicesRes.indices);
        setApiConnected(true);
      }
      // Set loading to false once indices are loaded so cards and system status display immediately
      setLoading(false);

      // 2. Batch-fetch all stock quotes in ONE call (instead of 30 individual calls)
      const batchRes = await apiClient.post<{ success: boolean; data: any[] }>(
        '/api/v1/market/batch-quotes',
        { symbols: NIFTY_STOCKS }
      );

      const quotes = (batchRes.data || []) as StockMover[];

      if (quotes.length > 0) {
        // Sort by change_percent descending for gainers
        const sorted = [...quotes].sort((a, b) => b.change_percent - a.change_percent);
        setGainers(sorted.filter(s => s.change_percent >= 0).slice(0, 5));
        setLosers(sorted.filter(s => s.change_percent < 0).reverse().slice(0, 5));

        // Compute sector averages
        const sectorData: { name: string; change: number }[] = [];
        for (const [sector, symbols] of Object.entries(SECTOR_MAP)) {
          const sectorQuotes = quotes.filter(q => symbols.includes(q.symbol));
          if (sectorQuotes.length > 0) {
            const avgChange = sectorQuotes.reduce((sum, q) => sum + q.change_percent, 0) / sectorQuotes.length;
            sectorData.push({ name: sector, change: avgChange });
          }
        }
        setSectors(sectorData);
      }
    } catch {
      setApiConnected(false);
    } finally {
      setLoading(false);
      setLastUpdated(new Date());
    }
  }, []);

  useEffect(() => {
    fetchDashboard();
    const interval = setInterval(fetchDashboard, REFRESH_INTERVALS.tick);
    return () => clearInterval(interval);
  }, [fetchDashboard]);

  return (
    <div className="space-y-6 animate-fadeIn">
      {/* Page Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-heading text-xl font-extrabold tracking-tight text-[var(--text)]">
            Intelligence Dashboard
          </h1>
          <p className="text-sm text-[var(--text-muted)] mt-0.5 font-mono">
            Real-time market overview · India + US
          </p>
        </div>

        <div className="flex items-center gap-3">
          {/* WebSocket status badge — only show when connected or actively reconnecting */}
          {(wsStatus === 'connected' || wsStatus === 'reconnecting' || wsStatus === 'connecting') && (
            <span
              className="badge text-[10px] flex items-center gap-1"
              style={{ background: WS_BADGE[wsStatus].bg, color: WS_BADGE[wsStatus].color }}
              title={`WebSocket: ${wsStatus}`}
            >
              <span className="text-[8px] leading-none">{WS_BADGE[wsStatus].dot}</span>
              {WS_BADGE[wsStatus].label}
            </span>
          )}

          {!apiConnected && !loading && (
            <span className="badge badge-yellow text-[10px]">API Connecting...</span>
          )}
          {apiConnected && (
            <span className="badge text-[10px]" style={{ background: 'rgba(0,212,160,0.15)', color: 'var(--green)' }}>API Live</span>
          )}
          <DataFreshness timestamp={lastUpdated} thresholdMs={60000} />
          <button
            onClick={fetchDashboard}
            className="p-2 rounded hover:bg-[var(--surface-2)] text-[var(--text-muted)] hover:text-[var(--accent)] transition-colors cursor-pointer"
            aria-label="Refresh data"
          >
            <RefreshCw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Market Indices Grid */}
      {loading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {[...Array(4)].map((_, i) => (
            <LoadingSkeleton key={i} variant="card" />
          ))}
        </div>
      ) : indices.length > 0 ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {indices.map((index, i) => (
            <IndexCard key={index.symbol} index={index} delay={i} />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="card p-5">
              <div className="text-xs font-mono text-[var(--text-dim)] text-center py-4">
                Loading index data...
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Sector Heatmap */}
      {sectors.length > 0 && <SectorHeatmap sectors={sectors} />}

      {/* Top Gainers & Losers */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <MoversTable title="Top Gainers" movers={gainers} type="gainers" />
        <MoversTable title="Top Losers" movers={losers} type="losers" />
      </div>

      {/* Market Status Info Bar */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.8 }}
        className="flex items-center justify-center gap-6 py-3 text-[11px] font-mono text-[var(--text-dim)]"
      >
        <span className="flex items-center gap-1.5">
          <Activity className="w-3 h-3" />
          Data: ~15s delayed via Yahoo Finance
        </span>
        <span>•</span>
        <span>NSE/BSE + NYSE/NASDAQ</span>
        <span>•</span>
        <span>Auto-refresh: 60s</span>
      </motion.div>
    </div>
  );
}
