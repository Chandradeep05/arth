'use client';

import { motion } from 'framer-motion';
import { Gauge } from 'lucide-react';

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
  if (score > 0.2) return 'var(--green)';
  if (score < -0.2) return 'var(--red)';
  return 'var(--gold)';
}

function getGradient(score: number): string {
  if (score > 0.2) return 'from-green-500/20 to-transparent';
  if (score < -0.2) return 'from-red-500/20 to-transparent';
  return 'from-yellow-500/20 to-transparent';
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
  // Map -1..+1 to 0..100 for the bar position
  const barPosition = ((score + 1) / 2) * 100;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.5 }}
      className="card p-5"
    >
      <div className="flex items-center gap-2 mb-4">
        <Gauge className="w-4 h-4 text-[var(--accent-orange)]" />
        <h3 className="font-heading text-sm font-bold uppercase tracking-wider text-[var(--text-muted)]">
          Sentiment
        </h3>
      </div>

      {/* Main Score */}
      <div className="text-center mb-4">
        <div
          className="font-heading text-3xl font-extrabold"
          style={{ color }}
        >
          {label}
        </div>
        <div className="text-xs font-mono text-[var(--text-dim)] mt-1">
          Score: {score > 0 ? '+' : ''}{score.toFixed(3)} · Confidence: {confidence.toFixed(0)}%
        </div>
      </div>

      {/* Sentiment Bar */}
      <div className="relative h-2 rounded-full bg-[var(--surface-2)] mb-4 overflow-hidden">
        {/* Background gradient: red → yellow → green */}
        <div className="absolute inset-0 flex">
          <div className="flex-1 bg-gradient-to-r from-[var(--red)]/30 to-[var(--gold)]/30" />
          <div className="flex-1 bg-gradient-to-r from-[var(--gold)]/30 to-[var(--green)]/30" />
        </div>
        {/* Position indicator */}
        <motion.div
          initial={{ left: '50%' }}
          animate={{ left: `${barPosition}%` }}
          transition={{ type: 'spring', stiffness: 200, damping: 20 }}
          className="absolute top-1/2 -translate-y-1/2 w-3 h-3 rounded-full border-2"
          style={{
            backgroundColor: color,
            borderColor: color,
            boxShadow: `0 0 8px ${color}`,
          }}
        />
      </div>

      {/* Distribution */}
      <div className="grid grid-cols-3 gap-2 text-center">
        <div>
          <div className="text-lg font-mono font-bold text-[var(--green)]">
            {bullishPct.toFixed(0)}%
          </div>
          <div className="text-[10px] font-mono text-[var(--text-dim)] uppercase">Bullish</div>
        </div>
        <div>
          <div className="text-lg font-mono font-bold text-[var(--gold)]">
            {neutralPct.toFixed(0)}%
          </div>
          <div className="text-[10px] font-mono text-[var(--text-dim)] uppercase">Neutral</div>
        </div>
        <div>
          <div className="text-lg font-mono font-bold text-[var(--red)]">
            {bearishPct.toFixed(0)}%
          </div>
          <div className="text-[10px] font-mono text-[var(--text-dim)] uppercase">Bearish</div>
        </div>
      </div>

      {/* Sources */}
      <div className="mt-3 pt-3 border-t border-[var(--border)] text-center space-y-1">
        <span className="text-[10px] font-mono text-[var(--text-dim)] block">
          Based on {totalSources} source{totalSources !== 1 ? 's' : ''} · Phase 1 keyword analysis
        </span>
        <span className="text-[9px] font-mono text-[var(--text-dim)] block opacity-70">
          News &amp; fundamentals only — does not reflect price action
        </span>
      </div>
    </motion.div>
  );
}
