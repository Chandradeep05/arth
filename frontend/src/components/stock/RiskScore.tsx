'use client';

import { motion } from 'framer-motion';
import { ShieldAlert } from 'lucide-react';

interface RiskDimension {
  dimension: string;
  score: number;
  label: string;
  factors: string[];
}

interface RiskScoreProps {
  compositeScore: number;
  compositeLabel: string;
  dimensions: RiskDimension[];
  confidence: number;
  disclaimer: string;
  loading?: boolean;
}

function getRiskColor(score: number): string {
  if (score < 30) return '#10b981';
  if (score < 55) return '#f59e0b';
  return '#ef4444';
}

function DimensionBar({ dim }: { dim: RiskDimension }) {
  const color = getRiskColor(dim.score);

  return (
    <div className="space-y-1.5 p-2 rounded-xl bg-white/[0.02] border border-white/[0.04]">
      <div className="flex items-center justify-between text-xs font-mono">
        <span className="text-[var(--text-muted)] font-medium">
          {dim.dimension.replace('_', ' ')}
        </span>
        <span className="font-semibold" style={{ color }}>
          {dim.score.toFixed(0)}/100 · {dim.label}
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-white/[0.06] overflow-hidden">
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${dim.score}%` }}
          transition={{ duration: 0.8, ease: 'easeOut' }}
          className="h-full rounded-full"
          style={{ backgroundColor: color }}
        />
      </div>
      {dim.factors.length > 0 && (
        <ul className="space-y-0.5 pt-0.5">
          {dim.factors.slice(0, 2).map((f, i) => (
            <li key={i} className="text-[10px] text-[var(--text-dim)] pl-2 border-l border-white/[0.08] truncate">
              {f}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function RiskScore({
  compositeScore,
  compositeLabel,
  dimensions,
  confidence,
  disclaimer,
  loading,
}: RiskScoreProps) {
  if (loading) {
    return (
      <div className="card p-5 space-y-4">
        <div className="h-4 w-24 animate-shimmer rounded" />
        <div className="h-20 animate-shimmer rounded" />
        {[...Array(3)].map((_, i) => (
          <div key={i} className="h-8 animate-shimmer rounded" />
        ))}
      </div>
    );
  }

  const color = getRiskColor(compositeScore);

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.4 }}
      className="card p-6 flex flex-col justify-between"
    >
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-lg bg-white/[0.04] border border-white/[0.08] flex items-center justify-center">
            <ShieldAlert className="w-3.5 h-3.5 text-amber-400" />
          </div>
          <h3 className="font-heading text-xs font-bold uppercase tracking-wider text-white">
            Risk Assessment
          </h3>
        </div>
        <span className="text-[10px] font-mono text-[var(--text-dim)]">
          Confidence: {confidence.toFixed(0)}%
        </span>
      </div>

      {/* Composite Score Ring Display */}
      <div className="flex items-center gap-6 my-2">
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
              animate={{
                strokeDashoffset: 2 * Math.PI * 40 * (1 - compositeScore / 100),
              }}
              transition={{ duration: 1, ease: 'easeOut' }}
              style={{ filter: `drop-shadow(0 0 6px ${color}80)` }}
            />
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span className="font-heading text-xl font-extrabold text-white">
              {compositeScore.toFixed(0)}
            </span>
            <span className="text-[9px] font-mono text-[var(--text-dim)] uppercase">
              / 100
            </span>
          </div>
        </div>

        <div>
          <div className="text-lg font-heading font-bold text-white mb-0.5">
            {compositeLabel}
          </div>
          <p className="text-xs text-[var(--text-muted)] leading-relaxed">
            Composite quantitative risk evaluation across financial volatility, liquidity, and solvency metrics.
          </p>
        </div>
      </div>

      {/* Dimension Bars */}
      <div className="space-y-2 mt-4 pt-4 border-t border-white/[0.06]">
        {dimensions.map((dim) => (
          <DimensionBar key={dim.dimension} dim={dim} />
        ))}
      </div>

      {/* Disclaimer */}
      {disclaimer && (
        <div className="mt-4 pt-3 border-t border-white/[0.06]">
          <p className="text-[9px] font-mono text-[var(--text-dim)] leading-relaxed">
            {disclaimer}
          </p>
        </div>
      )}
    </motion.div>
  );
}
