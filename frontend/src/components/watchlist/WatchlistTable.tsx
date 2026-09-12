'use client';

import { useRouter } from 'next/navigation';
import { motion } from 'framer-motion';
import { X, ArrowUpDown, TrendingUp, TrendingDown, Minus } from 'lucide-react';

/* ── Types ── */
export interface WatchlistItem {
  symbol: string;
  name?: string;
  price: number;
  change?: number;
  change_percent?: number;
  changePct?: number;
  volume?: number;
  marketCap?: number;
  dayHigh?: number;
  dayLow?: number;
  prevClose?: number;
  risk_score?: number;
  risk_label?: string;     // "Low" | "Medium" | "High" | "Critical"
  sentiment?: string;      // "bullish" | "neutral" | "bearish"
}

export type SortField = 'symbol' | 'name' | 'price' | 'change_percent' | 'risk_score' | 'sentiment' | 'volume';
export type SortDir = 'asc' | 'desc';

export interface WatchlistTableProps {
  items?: WatchlistItem[];
  data?: WatchlistItem[];
  onRemove: (symbol: string) => void;
  sortBy?: SortField;
  sortField?: SortField;
  sortDir?: SortDir;
  onSort?: (field: SortField) => void;
}

/* ── Helpers ── */
function getRiskBadgeClass(label?: string): string {
  switch (label?.toLowerCase()) {
    case 'low':
      return 'badge-green';
    case 'medium':
      return 'badge-yellow';
    case 'high':
    case 'critical':
      return 'badge-red';
    default:
      return 'bg-[rgba(255,255,255,0.04)] text-[var(--text-dim)] border border-[rgba(255,255,255,0.06)]';
  }
}

function SentimentIcon({ sentiment }: { sentiment?: string }) {
  switch (sentiment?.toLowerCase()) {
    case 'bullish':
      return <TrendingUp className="w-3.5 h-3.5 text-[var(--green)]" />;
    case 'bearish':
      return <TrendingDown className="w-3.5 h-3.5 text-[var(--red)]" />;
    default:
      return <Minus className="w-3.5 h-3.5 text-[var(--text-dim)]" />;
  }
}

function formatVolume(val?: number): string {
  if (!val || isNaN(val)) return '—';
  if (val >= 1e7) return `${(val / 1e7).toFixed(2)} Cr`;
  if (val >= 1e6) return `${(val / 1e6).toFixed(1)}M`;
  if (val >= 1e3) return `${(val / 1e3).toFixed(1)}K`;
  return val.toLocaleString('en-IN');
}

/* ── Sortable Header ── */
function SortHeader({
  label,
  field,
  sortBy,
  sortDir,
  onSort,
  align = 'left',
}: {
  label: string;
  field: SortField;
  sortBy: SortField;
  sortDir: SortDir;
  onSort?: (field: SortField) => void;
  align?: 'left' | 'right' | 'center';
}) {
  const isActive = sortBy === field;
  return (
    <th
      className={`cursor-pointer select-none hover:text-[var(--green)] transition-colors py-3 px-4 text-[11px] font-medium tracking-wider uppercase text-[var(--text-dim)] ${
        align === 'right' ? 'text-right' : align === 'center' ? 'text-center' : 'text-left'
      }`}
      onClick={() => onSort && onSort(field)}
    >
      <span className={`inline-flex items-center gap-1.5 ${align === 'right' ? 'justify-end' : align === 'center' ? 'justify-center' : 'justify-start'}`}>
        {label}
        {isActive && (
          <span className="text-[var(--green)] text-[9px]">
            {sortDir === 'asc' ? '▲' : '▼'}
          </span>
        )}
        {!isActive && <ArrowUpDown className="w-2.5 h-2.5 opacity-30 hover:opacity-70" />}
      </span>
    </th>
  );
}

/* ── Component ── */
export default function WatchlistTable({
  items,
  data,
  onRemove,
  sortBy,
  sortField,
  sortDir = 'desc',
  onSort,
}: WatchlistTableProps) {
  const router = useRouter();
  const listItems = items || data || [];
  const currentSort = sortBy || sortField || 'symbol';

  if (listItems.length === 0) {
    return null; // Empty state handled by parent
  }

  return (
    <div className="card overflow-hidden">
      <div className="overflow-x-auto">
        <table className="data-table w-full">
          <thead>
            <tr className="border-b border-[var(--border)]">
              <SortHeader label="Asset" field="symbol" sortBy={currentSort} sortDir={sortDir} onSort={onSort} />
              <SortHeader label="Price" field="price" sortBy={currentSort} sortDir={sortDir} onSort={onSort} align="right" />
              <SortHeader label="24h Change" field="change_percent" sortBy={currentSort} sortDir={sortDir} onSort={onSort} align="right" />
              <SortHeader label="Volume" field="volume" sortBy={currentSort} sortDir={sortDir} onSort={onSort} align="right" />
              <SortHeader label="Risk" field="risk_score" sortBy={currentSort} sortDir={sortDir} onSort={onSort} align="center" />
              <SortHeader label="Sentiment" field="sentiment" sortBy={currentSort} sortDir={sortDir} onSort={onSort} align="center" />
              <th className="text-center w-12 py-3 px-3 text-[11px] text-[var(--text-dim)] uppercase"></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[rgba(255,255,255,0.03)]">
            {listItems.map((item, idx) => {
              const chg = item.change_percent ?? item.changePct ?? 0;
              const isPositive = chg > 0;
              const isNegative = chg < 0;
              const tickerClean = item.symbol.replace('.NS', '').replace('.BO', '');
              const avatarInitials = tickerClean.slice(0, 2).toUpperCase();

              return (
                <motion.tr
                  key={item.symbol}
                  initial={{ opacity: 0, y: 6 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: idx * 0.02 }}
                  className="cursor-pointer hover:bg-[rgba(255,255,255,0.025)] transition-colors group"
                  onClick={() => router.push(`/markets/${encodeURIComponent(item.symbol)}`)}
                >
                  {/* Asset Column: Avatar + Ticker + Name */}
                  <td className="py-3.5 px-4">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 rounded-full bg-[rgba(255,255,255,0.05)] border border-[rgba(255,255,255,0.08)] flex items-center justify-center shrink-0 shadow-inner group-hover:border-[var(--green)]/40 transition-colors">
                        <span className="font-mono text-[11px] font-bold text-[var(--text)] tracking-wider">
                          {avatarInitials}
                        </span>
                      </div>
                      <div className="min-w-0">
                        <div className="font-mono text-xs font-bold text-white tracking-wide flex items-center gap-1.5">
                          {item.symbol}
                        </div>
                        <div className="text-[11px] text-[var(--text-dim)] truncate max-w-[160px] md:max-w-[220px]">
                          {item.name || tickerClean}
                        </div>
                      </div>
                    </div>
                  </td>

                  {/* Price */}
                  <td className="py-3.5 px-4 text-right font-mono text-xs font-semibold text-[var(--text)] tabular-nums">
                    {item.price != null && item.price > 0
                      ? item.symbol.endsWith('.NS') || item.symbol.endsWith('.BO')
                        ? `₹${item.price.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                        : `$${item.price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
                      : <span className="text-[var(--text-dim)]">—</span>}
                  </td>

                  {/* 24h Change capsule pill */}
                  <td className="py-3.5 px-4 text-right">
                    <span
                      className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] font-mono font-medium tracking-tight ${
                        isPositive
                          ? 'bg-[rgba(16,185,129,0.12)] text-[var(--green)] border border-[rgba(16,185,129,0.22)]'
                          : isNegative
                          ? 'bg-[rgba(239,68,68,0.12)] text-[var(--red)] border border-[rgba(239,68,68,0.22)]'
                          : 'bg-[rgba(255,255,255,0.04)] text-[var(--text-muted)] border border-[rgba(255,255,255,0.06)]'
                      }`}
                    >
                      {isPositive ? '+' : ''}
                      {chg.toFixed(2)}%
                    </span>
                  </td>

                  {/* Volume */}
                  <td className="py-3.5 px-4 text-right font-mono text-xs text-[var(--text-dim)] tabular-nums">
                    {formatVolume(item.volume)}
                  </td>

                  {/* Risk Badge */}
                  <td className="py-3.5 px-4 text-center">
                    <span className={`badge ${getRiskBadgeClass(item.risk_label)} text-[10px]`}>
                      {item.risk_label ?? (item.risk_score ? `${item.risk_score.toFixed(0)}` : '—')}
                    </span>
                  </td>

                  {/* Sentiment */}
                  <td className="py-3.5 px-4 text-center">
                    <span className="inline-flex items-center gap-1">
                      <SentimentIcon sentiment={item.sentiment} />
                      <span className="text-[10px] font-mono text-[var(--text-dim)] capitalize">
                        {item.sentiment ?? '—'}
                      </span>
                    </span>
                  </td>

                  {/* Remove Button */}
                  <td className="py-3.5 px-3 text-center">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        onRemove(item.symbol);
                      }}
                      className="p-1.5 rounded-md hover:bg-[rgba(239,68,68,0.15)] text-[var(--text-dim)]
                                 hover:text-[var(--red)] transition-colors cursor-pointer"
                      aria-label={`Remove ${item.symbol}`}
                      title="Remove from watchlist"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  </td>
                </motion.tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
