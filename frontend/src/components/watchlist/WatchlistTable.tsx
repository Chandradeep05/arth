'use client';

import { useRouter } from 'next/navigation';
import { motion } from 'framer-motion';
import { X, ArrowUpDown, TrendingUp, TrendingDown, Minus } from 'lucide-react';

/* ── Types ── */
export interface WatchlistItem {
  symbol: string;
  name: string;
  price: number;
  change_percent: number;
  risk_score?: number;
  risk_label?: string;     // "Low" | "Medium" | "High" | "Critical"
  sentiment?: string;      // "bullish" | "neutral" | "bearish"
}

export type SortField = 'symbol' | 'name' | 'price' | 'change_percent' | 'risk_score' | 'sentiment';
export type SortDir = 'asc' | 'desc';

export interface WatchlistTableProps {
  items: WatchlistItem[];
  onRemove: (symbol: string) => void;
  sortBy: SortField;
  sortDir: SortDir;
  onSort: (field: SortField) => void;
}

/* ── Helpers ── */
function getRiskBadgeClass(label?: string): string {
  switch (label?.toLowerCase()) {
    case 'low':
      return 'badge-green';
    case 'medium':
      return 'badge-yellow';
    case 'high':
      return 'bg-[var(--accent-orange)]/12 text-[var(--accent-orange)]';
    case 'critical':
      return 'badge-red';
    default:
      return 'bg-[var(--surface-2)] text-[var(--text-dim)]';
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
  onSort: (field: SortField) => void;
  align?: 'left' | 'right' | 'center';
}) {
  const isActive = sortBy === field;
  return (
    <th
      className={`cursor-pointer select-none hover:text-[var(--accent)] transition-colors ${
        align === 'right' ? 'text-right' : align === 'center' ? 'text-center' : 'text-left'
      }`}
      onClick={() => onSort(field)}
    >
      <span className="inline-flex items-center gap-1">
        {label}
        {isActive && (
          <span className="text-[var(--accent)] text-[9px]">
            {sortDir === 'asc' ? '▲' : '▼'}
          </span>
        )}
        {!isActive && <ArrowUpDown className="w-2.5 h-2.5 opacity-40" />}
      </span>
    </th>
  );
}

/* ── Component ── */
export default function WatchlistTable({
  items,
  onRemove,
  sortBy,
  sortDir,
  onSort,
}: WatchlistTableProps) {
  const router = useRouter();

  if (items.length === 0) {
    return null; // Empty state handled by parent
  }

  return (
    <div className="card overflow-hidden">
      <div className="overflow-x-auto">
        <table className="data-table w-full">
          <thead>
            <tr>
              <SortHeader label="Symbol" field="symbol" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
              <SortHeader label="Name" field="name" sortBy={sortBy} sortDir={sortDir} onSort={onSort} />
              <SortHeader label="Price" field="price" sortBy={sortBy} sortDir={sortDir} onSort={onSort} align="right" />
              <SortHeader label="Change %" field="change_percent" sortBy={sortBy} sortDir={sortDir} onSort={onSort} align="right" />
              <SortHeader label="Risk" field="risk_score" sortBy={sortBy} sortDir={sortDir} onSort={onSort} align="center" />
              <SortHeader label="Sentiment" field="sentiment" sortBy={sortBy} sortDir={sortDir} onSort={onSort} align="center" />
              <th className="text-center w-12"></th>
            </tr>
          </thead>
          <tbody>
            {items.map((item, idx) => (
              <motion.tr
                key={item.symbol}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: idx * 0.03 }}
                className="cursor-pointer"
                onClick={() => router.push(`/markets/${encodeURIComponent(item.symbol)}`)}
              >
                <td className="font-mono text-xs font-bold text-[var(--accent)]">
                  {item.symbol}
                </td>
                <td className="text-xs text-[var(--text-muted)] max-w-[200px] truncate">
                  {item.name || '—'}
                </td>
                <td className="text-right font-mono text-xs text-[var(--text)]">
                  {item.price != null ? item.price.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—'}
                </td>
                <td className="text-right font-mono text-xs">
                  <span
                    style={{
                      color:
                        item.change_percent > 0
                          ? 'var(--green)'
                          : item.change_percent < 0
                          ? 'var(--red)'
                          : 'var(--text-muted)',
                    }}
                  >
                    {item.change_percent > 0 ? '+' : ''}
                    {item.change_percent?.toFixed(2) ?? '—'}%
                  </span>
                </td>
                <td className="text-center">
                  <span className={`badge ${getRiskBadgeClass(item.risk_label)}`}>
                    {item.risk_label ?? '—'}
                  </span>
                </td>
                <td className="text-center">
                  <span className="inline-flex items-center gap-1">
                    <SentimentIcon sentiment={item.sentiment} />
                    <span className="text-[10px] font-mono text-[var(--text-dim)] capitalize">
                      {item.sentiment ?? '—'}
                    </span>
                  </span>
                </td>
                <td className="text-center">
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onRemove(item.symbol);
                    }}
                    className="p-1.5 rounded hover:bg-[var(--red)]/10 text-[var(--text-dim)]
                               hover:text-[var(--red)] transition-colors cursor-pointer"
                    aria-label={`Remove ${item.symbol}`}
                    title="Remove from watchlist"
                  >
                    <X className="w-3.5 h-3.5" />
                  </button>
                </td>
              </motion.tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
