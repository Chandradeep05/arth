'use client';

import { motion } from 'framer-motion';

/* ── Types ── */
export interface StatementPeriod {
  period: string;          // e.g. "FY2024", "Q3 2024"
  [lineItem: string]: string | number | null | undefined;
}

export interface StatementTableProps {
  data: StatementPeriod[];
  title: string;
  className?: string;
  /** Defaults to 'INR' to preserve existing behavior for existing callers. */
  currency?: 'INR' | 'USD';
  /** 'statement' formats values as currency amounts; 'ratio' formats as % or multiples. */
  mode?: 'statement' | 'ratio';
}

/* ── Number Formatting ── */
function formatRatio(key: string, value: unknown, currency: 'INR' | 'USD' = 'INR'): string {
  if (value === null || value === undefined || value === '') return '—';
  const num = typeof value === 'string' ? parseFloat(value) : Number(value);
  if (isNaN(num)) return String(value);

  const k = key.toLowerCase();

  // Currency amounts inside ratio tables (e.g. Free Cash Flow)
  if (k.includes('cash flow') || k.includes('fcf') || Math.abs(num) >= 1e6) {
    return formatNumber(num, currency);
  }

  // Percentage ratios (margins, growth, returns, yield)
  if (
    k.includes('margin') ||
    k.includes('growth') ||
    k.includes('roe') ||
    k.includes('roa') ||
    k.includes('roic') ||
    k.includes('yield') ||
    k.includes('payout') ||
    k.includes('return')
  ) {
    // If represented as decimal fraction (0.65 for 65%), convert to percent
    const pct = Math.abs(num) <= 2.0 && num !== 0 ? num * 100 : num;
    const sign = pct > 0 ? '+' : '';
    return `${sign}${pct.toFixed(1)}%`;
  }

  // Multiples (current ratio, quick ratio, debt/equity, turnover)
  return `${num.toFixed(2)}x`;
}

function formatNumber(value: unknown, currency: 'INR' | 'USD' = 'INR'): string {
  if (value === null || value === undefined || value === '') return '—';
  const num = typeof value === 'string' ? parseFloat(value) : (value as number);
  if (isNaN(num)) return String(value);

  const abs = Math.abs(num);
  const sign = num < 0 ? '-' : '';

  if (currency === 'USD') {
    if (abs >= 1e12) return `${sign}$${(abs / 1e12).toFixed(2)}T`;
    if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(2)}B`;
    if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(2)}M`;
    if (abs >= 1e3) return `${sign}$${(abs / 1e3).toFixed(1)}K`;
    return `${sign}$${abs.toFixed(2)}`;
  }

  // Indian numbering: Cr (10M), L (100K)
  if (abs >= 1e9) return `${sign}${(abs / 1e7).toFixed(1)} Cr`;
  if (abs >= 1e7) return `${sign}${(abs / 1e7).toFixed(2)} Cr`;
  if (abs >= 1e5) return `${sign}${(abs / 1e5).toFixed(2)} L`;
  if (abs >= 1e3) return `${sign}${(abs / 1e3).toFixed(1)}K`;
  return `${sign}${abs.toFixed(2)}`;
}

function computeYoYChange(current: unknown, previous: unknown): number | null {
  if (current == null || previous == null) return null;
  const cur = typeof current === 'string' ? parseFloat(current) : (current as number);
  const prev = typeof previous === 'string' ? parseFloat(previous) : (previous as number);
  if (isNaN(cur) || isNaN(prev) || prev === 0) return null;
  return ((cur - prev) / Math.abs(prev)) * 100;
}

function ChangeCell({ change }: { change: number | null | undefined }) {
  if (change == null || isNaN(change)) return <span className="text-[var(--text-dim)]">—</span>;
  const num = Number(change);
  const color = num > 0 ? 'var(--green)' : num < 0 ? 'var(--red)' : 'var(--text-muted)';
  const prefix = num > 0 ? '+' : '';
  return (
    <span className="font-mono text-xs" style={{ color }}>
      {prefix}{num.toFixed(1)}%
    </span>
  );
}

/* ── Component ── */
export default function StatementTable({ data, title, className = '', currency = 'INR', mode = 'statement' }: StatementTableProps) {
  if (!data || data.length === 0) {
    return (
      <div className={`card p-6 ${className}`}>
        <h3 className="font-heading text-sm font-bold text-[var(--text)] mb-2">{title}</h3>
        <p className="text-xs text-[var(--text-dim)] font-mono">No data available</p>
      </div>
    );
  }

  // Extract line item keys (everything except 'period')
  const firstRow = data.find((d) => d && typeof d === 'object');
  const lineItemKeys = firstRow ? Object.keys(firstRow).filter((k) => k !== 'period') : [];
  // Periods are columns (most recent first)
  const periods = data.filter((d) => d && d.period).map((d) => d.period);

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className={`card overflow-hidden ${className}`}
    >
      <div className="px-5 py-4 border-b border-[var(--border)]">
        <h3 className="font-heading text-sm font-bold text-[var(--text)]">{title}</h3>
      </div>

      <div className="overflow-x-auto">
        <table className="data-table w-full">
          <thead>
            <tr>
              <th className="sticky left-0 bg-[var(--surface)] z-10 min-w-[180px]">
                Line Item
              </th>
              {periods.map((p) => (
                <th key={p} className="text-right min-w-[100px]">
                  {p}
                </th>
              ))}
              {periods.length >= 2 && (
                <th className="text-right min-w-[80px]">YoY Δ</th>
              )}
            </tr>
          </thead>
          <tbody>
            {lineItemKeys.map((key, rowIdx) => {
              // Latest two periods for YoY
              const yoyChange =
                periods.length >= 2 && data[0] && data[1]
                  ? computeYoYChange(data[0][key], data[1][key])
                  : null;

              return (
                <tr
                  key={key}
                  className={rowIdx % 2 === 1 ? 'bg-[var(--surface-2)]/30' : ''}
                >
                  <td className="sticky left-0 bg-[var(--surface)] z-10 text-xs text-[var(--text-muted)] font-mono whitespace-nowrap">
                    {formatLabel(key)}
                  </td>
                  {data.map((period) => (
                    <td
                      key={period.period}
                      className="text-right font-mono text-xs text-[var(--text)]"
                    >
                      {mode === 'ratio'
                        ? formatRatio(key, period[key], currency)
                        : formatNumber(period[key], currency)}
                    </td>
                  ))}
                  {periods.length >= 2 && (
                    <td className="text-right">
                      <ChangeCell change={yoyChange} />
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </motion.div>
  );
}

/** Convert snake_case / camelCase keys to readable labels */
function formatLabel(key: string): string {
  return key
    .replace(/_/g, ' ')
    .replace(/([a-z])([A-Z])/g, '$1 $2')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}
