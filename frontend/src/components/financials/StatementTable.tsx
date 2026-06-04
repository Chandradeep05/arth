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
}

/* ── Number Formatting ── */
function formatNumber(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  const num = typeof value === 'string' ? parseFloat(value) : (value as number);
  if (isNaN(num)) return String(value);

  const abs = Math.abs(num);
  const sign = num < 0 ? '-' : '';

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

function ChangeCell({ change }: { change: number | null }) {
  if (change === null) return <span className="text-[var(--text-dim)]">—</span>;
  const color = change > 0 ? 'var(--green)' : change < 0 ? 'var(--red)' : 'var(--text-muted)';
  const prefix = change > 0 ? '+' : '';
  return (
    <span className="font-mono text-xs" style={{ color }}>
      {prefix}{change.toFixed(1)}%
    </span>
  );
}

/* ── Component ── */
export default function StatementTable({ data, title, className = '' }: StatementTableProps) {
  if (!data || data.length === 0) {
    return (
      <div className={`card p-6 ${className}`}>
        <h3 className="font-heading text-sm font-bold text-[var(--text)] mb-2">{title}</h3>
        <p className="text-xs text-[var(--text-dim)] font-mono">No data available</p>
      </div>
    );
  }

  // Extract line item keys (everything except 'period')
  const lineItemKeys = Object.keys(data[0]).filter((k) => k !== 'period');
  // Periods are columns (most recent first)
  const periods = data.map((d) => d.period);

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
                periods.length >= 2
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
                      {formatNumber(period[key])}
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
