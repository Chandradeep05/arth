'use client';

import { motion } from 'framer-motion';
import { Gauge, ArrowRight } from 'lucide-react';

interface SentimentGaugeProps {
  score: number; // -1 to +1
  label: string; // "Bullish", "Bearish", "Neutral"
  confidence: number; // 0-100
  bullishPct: number;
  bearishPct: number;
  neutralPct: number;
  totalSources: number;
  loading?: boolean;
}

function getColor(score: number): string {
  if (score > 0.2) return '#10b981';
  if (score < -0.2) return '#ef4444';
  return '#f59e0b';
}

export default function SentimentGauge({
  score,
  label,
  confidence,
  bullishPct,
  bearishPct,
  neutralPct,
  totalSources,
  loading,
}: SentimentGaugeProps) {
  if (loading) {
    return (
      <div className="card p-5 space-y-4">
        <div className="h-4 w-32 animate-shimmer rounded" />
        <div className="h-24 animate-shimmer rounded" />
      </div>
    );
  }

  const color = getColor(score);
  // Calculate percentage 0-100 from score (-1 to +1)
  const displayPct = Math.round(((score + 1) / 2) * 100);
  const strokeDashoffset = 2 * Math.PI * 40 * (1 - displayPct / 100);

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.35 }}
      className="card p-6 flex flex-col justify-between"
    >
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-lg bg-white/[0.04] border border-white/[0.08] flex items-center justify-center">
            <Gauge className="w-3.5 h-3.5 text-emerald-400" />
          </div>
          <h3 className="font-heading text-xs font-bold uppercase tracking-wider text-white">
            Market Sentiment
          </h3>
        </div>
        <span className="text-[10px] font-mono text-[var(--text-dim)]">
          {totalSources} sources analyzed
        </span>
      </div>

      {/* Main Circular Gauge Display (Reference 01 & 03) */}
      <div className="flex items-center gap-6 my-2">
        {/* Circular Progress Meter */}
        <div className="relative w-24 h-24 shrink-0 flex items-center justify-center">
          <svg className="w-24 h-24 -rotate-90" viewBox="0 0 100 100">
            <circle
              cx="50"
              cy="50"
              r="40"
              fill="none"
              stroke="rgba(255, 255, 255, 0.06)"
              strokeWidth="6"
            />
            <motion.circle
              cx="50"
              cy="50"
              r="40"
              fill="none"
              stroke={color}
              strokeWidth="6"
              strokeLinecap="round"
              strokeDasharray={`${2 * Math.PI * 40}`}
              initial={{ strokeDashoffset: 2 * Math.PI * 40 }}
              animate={{ strokeDashoffset }}
              transition={{ duration: 1, ease: 'easeOut' }}
              style={{ filter: `drop-shadow(0 0 6px ${color}80)` }}
            />
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span className="font-heading text-xl font-extrabold text-white">
              {displayPct}%
            </span>
            <span className="text-[9px] font-mono text-[var(--text-dim)] uppercase">
              Sentiment
            </span>
          </div>
        </div>

        {/* Status & Confidence */}
        <div className="flex-1 min-w-0">
          <div
            className="font-heading text-xl font-bold tracking-tight"
            style={{ color }}
          >
            {label}
          </div>
          <p className="text-xs text-[var(--text-muted)] mt-0.5 leading-relaxed">
            Confidence score: <span className="text-white font-mono">{confidence.toFixed(0)}%</span>
          </p>
          <div className="mt-2 text-[11px] text-[var(--text-dim)] font-mono">
            Index: {score > 0 ? '+' : ''}{score.toFixed(3)} (-1.0 to +1.0)
          </div>
        </div>
      </div>

      {/* Distribution Mini Pills */}
      <div className="grid grid-cols-3 gap-2 text-center pt-4 border-t border-white/[0.06] mt-4">
        <div className="p-2 rounded-xl bg-white/[0.02] border border-white/[0.04]">
          <div className="text-sm font-mono font-bold text-emerald-400">
            {bullishPct.toFixed(0)}%
          </div>
          <div className="text-[9px] font-mono uppercase tracking-wider text-[var(--text-dim)] mt-0.5">Bullish</div>
        </div>
        <div className="p-2 rounded-xl bg-white/[0.02] border border-white/[0.04]">
          <div className="text-sm font-mono font-bold text-amber-400">
            {neutralPct.toFixed(0)}%
          </div>
          <div className="text-[9px] font-mono uppercase tracking-wider text-[var(--text-dim)] mt-0.5">Neutral</div>
        </div>
        <div className="p-2 rounded-xl bg-white/[0.02] border border-white/[0.04]">
          <div className="text-sm font-mono font-bold text-red-400">
            {bearishPct.toFixed(0)}%
          </div>
          <div className="text-[9px] font-mono uppercase tracking-wider text-[var(--text-dim)] mt-0.5">Bearish</div>
        </div>
      </div>
    </motion.div>
  );
}
