'use client';

import { motion } from 'framer-motion';
import { Activity, TrendingUp, TrendingDown, Minus } from 'lucide-react';
import type { TechnicalIndicators } from '@/types/market';

interface TechnicalPanelProps {
  indicators: TechnicalIndicators | null;
  loading?: boolean;
}

function SignalBadge({ signal, type }: { signal: string | null; type: 'rsi' | 'macd' | 'bb' }) {
  if (!signal) return <span className="badge badge-cyan">N/A</span>;

  const configs: Record<string, { class: string; icon: typeof TrendingUp }> = {
    overbought: { class: 'badge-red', icon: TrendingDown },
    oversold: { class: 'badge-green', icon: TrendingUp },
    bullish: { class: 'badge-green', icon: TrendingUp },
    bearish: { class: 'badge-red', icon: TrendingDown },
    above_upper: { class: 'badge-red', icon: TrendingUp },
    below_lower: { class: 'badge-green', icon: TrendingDown },
    neutral: { class: 'badge-yellow', icon: Minus },
    middle: { class: 'badge-yellow', icon: Minus },
  };

  const config = configs[signal] || configs.neutral;
  const Icon = config.icon;

  return (
    <span className={`badge ${config.class} gap-1`}>
      <Icon className="w-3 h-3" />
      {signal.replace('_', ' ')}
    </span>
  );
}

function IndicatorRow({
  label,
  value,
  signal,
  signalType,
}: {
  label: string;
  value: string | null;
  signal?: string | null;
  signalType?: 'rsi' | 'macd' | 'bb';
}) {
  return (
    <div className="flex items-center justify-between py-2.5 border-b border-[var(--border)] last:border-0">
      <span className="text-xs text-[var(--text-muted)] font-mono uppercase tracking-wider">
        {label}
      </span>
      <div className="flex items-center gap-3">
        <span className="text-sm font-mono text-[var(--text)] font-medium">
          {value ?? '—'}
        </span>
        {signal !== undefined && signalType && (
          <SignalBadge signal={signal} type={signalType} />
        )}
      </div>
    </div>
  );
}

export default function TechnicalPanel({ indicators, loading }: TechnicalPanelProps) {
  if (loading) {
    return (
      <div className="card p-5 space-y-3">
        <div className="h-4 w-40 animate-shimmer rounded" />
        {[...Array(6)].map((_, i) => (
          <div key={i} className="flex justify-between">
            <div className="h-3 w-16 animate-shimmer rounded" />
            <div className="h-3 w-20 animate-shimmer rounded" />
          </div>
        ))}
      </div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.3 }}
      className="card p-5"
    >
      <div className="flex items-center gap-2 mb-4">
        <Activity className="w-4 h-4 text-[var(--accent)]" />
        <h3 className="font-heading text-sm font-bold uppercase tracking-wider text-[var(--text-muted)]">
          Technical Indicators
        </h3>
      </div>

      <div className="space-y-0">
        <IndicatorRow
          label="RSI (14)"
          value={indicators?.rsi_14?.toFixed(2) ?? null}
          signal={indicators?.rsi_signal}
          signalType="rsi"
        />
        <IndicatorRow
          label="MACD"
          value={indicators?.macd?.value?.toFixed(4) ?? null}
          signal={indicators?.macd_signal_type}
          signalType="macd"
        />
        <IndicatorRow
          label="MACD Signal"
          value={indicators?.macd?.signal?.toFixed(4) ?? null}
        />
        <IndicatorRow
          label="MACD Histogram"
          value={indicators?.macd?.histogram?.toFixed(4) ?? null}
        />
        <IndicatorRow
          label="BB Position"
          value={
            indicators?.bollinger_bands
              ? `${indicators.bollinger_bands.lower.toFixed(2)} — ${indicators.bollinger_bands.upper.toFixed(2)}`
              : null
          }
          signal={indicators?.bb_position}
          signalType="bb"
        />
        <IndicatorRow
          label="VWAP"
          value={indicators?.vwap?.toFixed(2) ?? null}
        />
        <IndicatorRow
          label="SMA 20"
          value={indicators?.sma_20?.toFixed(2) ?? null}
        />
        <IndicatorRow
          label="SMA 50"
          value={indicators?.sma_50?.toFixed(2) ?? null}
        />
      </div>
    </motion.div>
  );
}
