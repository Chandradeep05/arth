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
import { useStockAtmosphere } from '@/lib/atmosphere';

/* ── Stocks to scan for gainers/losers (US market — reliable via Twelve Data) ── */
/* 8 stocks = exactly 8 credits/min on free tier (one batch call) */
const MARKET_STOCKS = [
  'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'META',
  'NVDA', 'TSLA', 'JPM',
];

interface StockMover {
  symbol: string;
  name: string;
  price: number;
  change: number;
  change_percent: number;
  volume: number;
}

/* ── Stock Mover Card with Dynamic Atmospheric Subsurface ── */
function StockMoverCard({ stock, index }: { stock: StockMover; index: number }) {
  const atmosphere = useStockAtmosphere(stock.symbol);
  const isPositive = (stock.change_percent ?? 0) >= 0;
  const cleanSymbol = stock.symbol.replace('.NS', '').replace('.BO', '');
  const isINR = stock.symbol.endsWith('.NS') || stock.symbol.endsWith('.BO');
  const currencySymbol = isINR ? '₹' : '$';

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.06, duration: 0.3 }}
    >
      <Link
        href={`/markets/${encodeURIComponent(stock.symbol)}`}
        className="card p-3 sm:p-3.5 group block hover:border-white/[0.14] transition-all relative overflow-hidden"
      >
        <div className={`card-atmosphere ${atmosphere}`} aria-hidden="true" />
        <div className="relative z-10">
          <div className="flex items-center justify-between mb-1.5">
            <div className="flex items-center gap-1.5 min-w-0">
              <span className="font-mono text-xs font-bold text-white group-hover:text-emerald-400 transition-colors">
                {cleanSymbol}
              </span>
              <span className="text-[10px] text-[var(--text-dim)] font-mono truncate max-w-[80px] sm:max-w-[110px]">
                {stock.name}
              </span>
            </div>
            {isPositive ? (
              <TrendingUp className="w-3 h-3 text-emerald-400 shrink-0" />
            ) : (
              <TrendingDown className="w-3 h-3 text-red-400 shrink-0" />
            )}
          </div>

          <div className="text-lg sm:text-xl font-heading font-bold text-white mb-1">
            {currencySymbol}{formatNumber(stock.price)}
          </div>

          <div className="flex items-center gap-1.5">
            <span
              className={`inline-flex items-center gap-0.5 text-[11px] font-mono font-medium px-1.5 py-0.5 rounded-md ${
                isPositive
                  ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                  : 'bg-red-500/10 text-red-400 border border-red-500/20'
              }`}
            >
              {isPositive ? '+' : ''}{stock.change.toFixed(2)} ({isPositive ? '+' : ''}{stock.change_percent.toFixed(2)}%)
            </span>
          </div>
        </div>
      </Link>
    </motion.div>
  );
}

/* ── Helper: format number with commas ── */
function formatNumber(n: number): string {
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 }).format(n);
}

function formatVolume(v: number): string {
  if (v >= 1_000_000_000) return `${(v / 1_000_000_000).toFixed(1)}B`;
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (v >= 1_000) return `${(v / 1_000).toFixed(1)}K`;
  return v.toString();
}

/* ── Sector heatmap: US sectors mapped to tracked stocks ── */
const SECTOR_MAP: Record<string, string[]> = {
  Tech: ['AAPL', 'MSFT', 'GOOGL', 'META', 'NVDA'],
  'E-Commerce': ['AMZN'],
  Auto: ['TSLA'],
  Finance: ['JPM'],
};

/* ── Index Card Component ── */
function IndexCard({ index, delay }: { index: MarketIndex; delay: number }) {
  const change = index.change ?? 0;
  const changePct = index.change_percent ?? 0;
  const isPositive = change >= 0;
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: delay * 0.08, duration: 0.35 }}
      className="card p-5 group cursor-pointer hover:border-white/[0.12] transition-all"
    >
      <div className="flex items-center justify-between mb-3">
        <span className="text-[11px] font-mono text-[var(--text-muted)] uppercase tracking-wider">
          {index.name}
        </span>
        <div className={`w-1.5 h-1.5 rounded-full ${isPositive ? 'bg-emerald-400 shadow-[0_0_6px_rgba(52,211,153,0.8)]' : 'bg-red-400 shadow-[0_0_6px_rgba(248,113,113,0.8)]'}`} />
      </div>

      <div className="font-heading text-2xl font-bold tracking-tight text-white mb-2">
        {formatNumber(index.value ?? 0)}
      </div>

      <div className="flex items-center gap-2">
        <span className={`inline-flex items-center gap-1 text-xs font-mono font-medium px-2 py-0.5 rounded-md ${
          isPositive
            ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
            : 'bg-red-500/10 text-red-400 border border-red-500/20'
        }`}>
          {isPositive ? <TrendingUp className="w-3 h-3" /> : <TrendingDown className="w-3 h-3" />}
          {isPositive ? '+' : ''}{formatNumber(change)} ({isPositive ? '+' : ''}{changePct.toFixed(2)}%)
        </span>
      </div>
    </motion.div>
  );
}

/* ── Sector Heatmap ── */
function SectorHeatmap({ sectors }: { sectors: { name: string; change: number }[] }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.3, duration: 0.3 }}
      className="card p-3 sm:p-4"
    >
      <div className="flex items-center justify-between mb-2.5">
        <div>
          <h3 className="font-heading text-[11px] font-bold uppercase tracking-wider text-white">
            Sector Performance
          </h3>
          <p className="text-[10px] text-[var(--text-dim)] font-mono">Market breadth across tracked sectors</p>
        </div>
        <BarChart3 className="w-3.5 h-3.5 text-[var(--text-dim)]" />
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {sectors.map((sector) => {
          const sectorChange = sector.change ?? 0;
          const isPositive = sectorChange >= 0;

          return (
            <div
              key={sector.name}
              className={`rounded-lg p-2.5 text-left transition-all border ${
                isPositive
                  ? 'bg-emerald-500/[0.04] border-emerald-500/15 hover:border-emerald-500/30'
                  : 'bg-red-500/[0.04] border-red-500/15 hover:border-red-500/30'
              }`}
            >
              <div className="text-[10px] text-[var(--text-muted)] font-medium mb-0.5 truncate">
                {sector.name}
              </div>
              <div className={`text-xs font-mono font-semibold ${isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
                {isPositive ? '+' : ''}{sectorChange.toFixed(2)}%
              </div>
            </div>
          );
        })}
      </div>
    </motion.div>
  );
}

/* ── Movers Table: Exact Reference Styling ── */
function MoversTable({
  title,
  movers,
  type,
}: {
  title: string;
  movers: StockMover[];
  type: 'gainers' | 'losers';
}) {
  const isGainers = type === 'gainers';

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: isGainers ? 0.35 : 0.45, duration: 0.3 }}
      className="card overflow-hidden"
    >
      <div className="flex items-center justify-between px-4 py-2.5 border-b border-white/[0.06]">
        <h3 className="font-heading text-[11px] font-bold uppercase tracking-wider text-white">
          {title}
        </h3>
        <span className={`badge ${isGainers ? 'badge-green' : 'badge-red'}`}>
          {isGainers ? '▲ Top 5' : '▼ Top 5'}
        </span>
      </div>

      <div className="overflow-x-auto no-scrollbar">
        <table className="data-table data-table-compact">
          <thead>
            <tr>
              <th>Asset</th>
              <th className="text-right">Price</th>
              <th className="text-right">Change</th>
              <th className="text-right hidden sm:table-cell">Volume</th>
            </tr>
          </thead>
          <tbody>
            {movers.length === 0 ? (
              <tr>
                <td colSpan={4} className="text-center text-[var(--text-dim)] py-5 font-mono text-xs">
                  {isGainers ? 'No gainers recorded in session' : 'No losers recorded in session'}
                </td>
              </tr>
            ) : (
              movers.map((stock) => {
                const isPositive = (stock.change ?? 0) >= 0;
                const cleanSymbol = stock.symbol.replace('.NS', '').replace('.BO', '');
                return (
                  <tr key={stock.symbol} className="cursor-pointer group">
                    <td>
                      <Link href={`/markets/${encodeURIComponent(stock.symbol)}`} className="flex items-center gap-2">
                        <div className="w-5.5 h-5.5 rounded-full bg-white/[0.04] border border-white/[0.08] flex items-center justify-center text-[9px] font-bold text-white shrink-0 group-hover:border-emerald-500/30 transition-colors">
                          {cleanSymbol.charAt(0)}
                        </div>
                        <div className="min-w-0">
                          <div className="font-mono text-xs font-semibold text-white group-hover:text-emerald-400 transition-colors truncate">
                            {cleanSymbol}
                          </div>
                          <div className="text-[10px] text-[var(--text-dim)] truncate max-w-[100px] sm:max-w-[140px]">
                            {stock.name}
                          </div>
                        </div>
                      </Link>
                    </td>
                    <td className="text-right font-mono text-xs text-white">
                      ${formatNumber(stock.price ?? 0)}
                    </td>
                    <td className="text-right">
                      <span className={`inline-block font-mono text-[11px] font-medium px-1.5 py-0.5 rounded-md ${
                        isPositive
                          ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                          : 'bg-red-500/10 text-red-400 border border-red-500/20'
                      }`}>
                        {isPositive ? '+' : ''}{(stock.change_percent ?? 0).toFixed(2)}%
                      </span>
                    </td>
                    <td className="text-right hidden sm:table-cell text-[var(--text-dim)] font-mono text-xs">
                      {formatVolume(stock.volume ?? 0)}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
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
  const [quotesLoaded, setQuotesLoaded] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date>(new Date());
  const [apiConnected, setApiConnected] = useState(false);

  // WebSocket connection for real-time price streaming
  const { status: wsStatus } = useWebSocket();

  const fetchDashboard = useCallback(async () => {
    try {
      // 1. Fetch live indices
      const indicesRes = await apiClient.get<{ indices: MarketIndex[] }>('/api/v1/market/indices');
      if (indicesRes.indices && indicesRes.indices.length > 0) {
        setIndices(indicesRes.indices);
        setApiConnected(true);
      }
      setLoading(false);

      // 2. Batch-fetch all live stock quotes via original API
      const batchRes = await apiClient.post<{ success: boolean; data: any[] }>(
        '/api/v1/market/batch-quotes',
        { symbols: MARKET_STOCKS }
      );

      const quotes = (batchRes.data || []) as StockMover[];

      if (quotes.length > 0) {
        const sorted = [...quotes].sort((a, b) => b.change_percent - a.change_percent);
        setGainers(sorted.filter(s => s.change_percent >= 0).slice(0, 5));
        setLosers(sorted.filter(s => s.change_percent < 0).reverse().slice(0, 5));

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
      setQuotesLoaded(true);
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
    <div className="space-y-3 sm:space-y-3.5 lg:space-y-4 animate-fadeIn pb-4">
      {/* Reference Hero Banner: Discipline Quote + Market Overview */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 sm:gap-3.5">
        {/* Left: Philosophy Card (Reference Panel 01) */}
        <div className="card p-3.5 sm:p-4.5 lg:col-span-2 relative overflow-hidden flex flex-col justify-between">
          <div className="card-atmosphere card-atmosphere-globe" aria-hidden="true" />
          <div className="relative z-10">
            <div className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-[10px] font-mono text-emerald-400 uppercase tracking-wider mb-2 sm:mb-2.5">
              <Activity className="w-3 h-3" />
              Intelligence Feed
            </div>
            <h2 className="font-heading text-lg sm:text-xl lg:text-[22px] font-bold tracking-tight text-white max-w-lg leading-tight mb-1">
              The market rewards discipline, not emotion.
            </h2>
            <p className="text-xs text-[var(--text-muted)] font-mono">
              Better data. Deeper insights. Smarter decisions.
            </p>
          </div>

          <div className="relative z-10 mt-2.5 pt-2 sm:mt-3 sm:pt-2.5 border-t border-white/[0.06] flex items-center justify-between text-[10px] sm:text-[11px] font-mono text-[var(--text-dim)]">
            <span>Market Session: Open</span>
            <span>Real-time Quote Pipeline</span>
          </div>
        </div>

        {/* Right: Quick Controls & Session Status */}
        <div className="card p-3.5 sm:p-4.5 flex flex-col justify-between relative overflow-hidden">
          <div className="card-atmosphere card-atmosphere-intelligence" style={{ opacity: 0.045 }} aria-hidden="true" />
          <div className="relative z-10">
            <div className="flex items-center justify-between mb-2">
              <span className="text-[10px] font-mono uppercase tracking-wider text-[var(--text-muted)]">
                Network Stream
              </span>
              {(wsStatus === 'connected' || wsStatus === 'reconnecting' || wsStatus === 'connecting') && (
                <span
                  className="badge text-[9px] px-2 py-0.5 flex items-center gap-1"
                  style={{ background: WS_BADGE[wsStatus].bg, color: WS_BADGE[wsStatus].color }}
                >
                  <span className="text-[7px] leading-none">{WS_BADGE[wsStatus].dot}</span>
                  {WS_BADGE[wsStatus].label}
                </span>
              )}
            </div>
            <div className="text-base sm:text-lg font-heading font-bold text-white mb-0.5">
              Active Feeds
            </div>
            <p className="text-xs text-[var(--text-dim)] font-mono">
              Live market quotes via Twelve Data &amp; NSE
            </p>
          </div>

          <div className="relative z-10 mt-2.5 pt-2 sm:mt-3 sm:pt-2.5 border-t border-white/[0.06] flex items-center justify-between">
            <DataFreshness timestamp={lastUpdated} thresholdMs={60000} />
            <button
              onClick={fetchDashboard}
              className="p-1.5 rounded-lg bg-white/[0.03] hover:bg-white/[0.08] text-[var(--text-muted)] hover:text-white border border-white/[0.06] transition-all cursor-pointer"
              aria-label="Refresh data"
            >
              <RefreshCw className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </div>

      {/* Top Stocks / Indices Grid */}
      {loading ? (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-2.5 sm:gap-3">
          {[...Array(4)].map((_, i) => (
            <LoadingSkeleton key={i} variant="card" />
          ))}
        </div>
      ) : gainers.length > 0 || losers.length > 0 ? (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-2.5 sm:gap-3">
          {[...gainers.slice(0, 2), ...losers.slice(0, 2)].map((stock, i) => (
            <StockMoverCard key={stock.symbol} stock={stock} index={i} />
          ))}
        </div>
      ) : (
        <div className="card p-4">
          <div className="text-xs font-mono text-[var(--text-dim)] text-center py-2">
            {quotesLoaded ? 'Market Closed — No trading data available right now' : 'Loading market data...'}
          </div>
        </div>
      )}

      {/* Sector Performance */}
      {sectors.length > 0 && <SectorHeatmap sectors={sectors} />}

      {/* Top Gainers & Losers Tables */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 sm:gap-3.5">
        <MoversTable title="Top Gainers" movers={gainers} type="gainers" />
        <MoversTable title="Top Losers" movers={losers} type="losers" />
    </div>
  );
}
