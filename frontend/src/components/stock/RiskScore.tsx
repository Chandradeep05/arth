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
  if (score < 25) return 'var(--green)';
  if (score < 50) return 'var(--gold)';
  if (score < 75) return 'var(--accent-orange)';
  return 'var(--red)';
}

function DimensionBar({ dim }: { dim: RiskDimension }) {
  const color = getRiskColor(dim.score);

  return (
    <div className="space-y-1.5">
      <div className="flex items-center justify-between">
        <span className="text-xs font-mono uppercase tracking-wider text-[var(--text-muted)]">
          {dim.dimension.replace('_', ' ')}
        </span>
        <span className="text-xs font-mono font-medium" style={{ color }}>
          {dim.score.toFixed(0)} — {dim.label}
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-[var(--surface-2)] overflow-hidden">
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${dim.score}%` }}
          transition={{ duration: 0.8, ease: 'easeOut' }}
          className="h-full rounded-full"
          style={{ backgroundColor: color }}
        />
      </div>
      {dim.factors.length > 0 && (
        <ul className="space-y-0.5">
          {dim.factors.slice(0, 2).map((f, i) => (
            <li key={i} className="text-[10px] text-[var(--text-dim)] pl-2 border-l border-[var(--border)]">
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
      transition={{ delay: 0.6 }}
      className="card p-5"
    >
      <div className="flex items-center gap-2 mb-4">
        <ShieldAlert className="w-4 h-4 text-[var(--accent-orange)]" />
        <h3 className="font-heading text-sm font-bold uppercase tracking-wider text-[var(--text-muted)]">
          Risk Assessment
        </h3>
      </div>

      {/* Composite Score */}
      <div className="text-center mb-5">
        <div className="relative inline-flex items-center justify-center">
          {/* Circular progress */}
          <svg className="w-24 h-24 -rotate-90" viewBox="0 0 100 100">
            <circle
              cx="50" cy="50" r="42"
              fill="none"
              stroke="var(--surface-2)"
              strokeWidth="6"
            />
            <motion.circle
              cx="50" cy="50" r="42"
              fill="none"
              stroke={color}
              strokeWidth="6"
              strokeLinecap="round"
              strokeDasharray={`${2 * Math.PI * 42}`}
              initial={{ strokeDashoffset: 2 * Math.PI * 42 }}
              animate={{
                strokeDashoffset: 2 * Math.PI * 42 * (1 - compositeScore / 100),
              }}
              transition={{ duration: 1, ease: 'easeOut' }}
              style={{ filter: `drop-shadow(0 0 6px ${color})` }}
            />
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span className="text-xl font-heading font-extrabold" style={{ color }}>
              {compositeScore.toFixed(0)}
            </span>
            <span className="text-[9px] font-mono text-[var(--text-dim)] uppercase">
              / 100
            </span>
          </div>
        </div>
        <div className="text-sm font-heading font-bold mt-2" style={{ color }}>
          {compositeLabel}
        </div>
        <div className="text-[10px] font-mono text-[var(--text-dim)] mt-0.5">
          Confidence: {confidence.toFixed(0)}%
        </div>
      </div>

      {/* Dimension Bars */}
      <div className="space-y-4">
        {dimensions.map((dim) => (
          <DimensionBar key={dim.dimension} dim={dim} />
        ))}
      </div>

      {/* Disclaimer */}
      <div className="mt-4 pt-3 border-t border-[var(--border)]">
        <p className="text-[9px] font-mono text-[var(--text-dim)] leading-relaxed">
          {disclaimer}
        </p>
      </div>
    </motion.div>
  );
}
