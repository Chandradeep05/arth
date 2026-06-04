'use client';

import { motion } from 'framer-motion';
import { HeartPulse } from 'lucide-react';

/* ── Types ── */
export interface HealthCategory {
  name: string;
  score: number;    // 0-25
  maxScore?: number; // defaults to 25
}

export interface HealthScoreData {
  overall_score: number;  // 0-100
  categories: HealthCategory[];
  symbol?: string;
  summary?: string;
}

export interface HealthScoreCardProps {
  data: HealthScoreData;
  className?: string;
}

/* ── Helpers ── */
function getCategoryColor(score: number): string {
  if (score > 18) return 'var(--green)';
  if (score >= 12) return 'var(--gold)';
  return 'var(--red)';
}

function getOverallColor(score: number): string {
  if (score >= 75) return 'var(--green)';
  if (score >= 50) return 'var(--gold)';
  if (score >= 25) return 'var(--accent-orange)';
  return 'var(--red)';
}

function getOverallLabel(score: number): string {
  if (score >= 75) return 'Excellent';
  if (score >= 50) return 'Good';
  if (score >= 25) return 'Fair';
  return 'Poor';
}

/* ── Category Bar ── */
function CategoryBar({ category, index }: { category: HealthCategory; index: number }) {
  const max = category.maxScore ?? 25;
  const pct = Math.min((category.score / max) * 100, 100);
  const color = getCategoryColor(category.score);

  return (
    <motion.div
      initial={{ opacity: 0, x: -12 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ delay: 0.2 + index * 0.08 }}
      className="space-y-1.5"
    >
      <div className="flex justify-between text-xs font-mono">
        <span className="text-[var(--text-muted)]">{category.name}</span>
        <span style={{ color }}>
          {category.score.toFixed(1)}/{max}
        </span>
      </div>
      <div className="h-2 rounded-full bg-[var(--surface-2)] overflow-hidden">
        <motion.div
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.8, ease: 'easeOut', delay: 0.3 + index * 0.08 }}
          className="h-full rounded-full"
          style={{ background: color }}
        />
      </div>
    </motion.div>
  );
}

/* ── Component ── */
export default function HealthScoreCard({ data, className = '' }: HealthScoreCardProps) {
  const overallColor = getOverallColor(data.overall_score);
  const overallLabel = getOverallLabel(data.overall_score);

  // Default categories if none provided
  const categories: HealthCategory[] =
    data.categories && data.categories.length > 0
      ? data.categories
      : [
          { name: 'Profitability', score: 0 },
          { name: 'Solvency', score: 0 },
          { name: 'Efficiency', score: 0 },
          { name: 'Growth', score: 0 },
        ];

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className={`card p-6 ${className}`}
    >
      {/* Header */}
      <div className="flex items-center gap-2 mb-5">
        <HeartPulse className="w-5 h-5 text-[var(--accent)]" />
        <h3 className="font-heading text-sm font-bold text-[var(--text)]">
          Financial Health Score
        </h3>
      </div>

      {/* Overall Score */}
      <div className="flex items-center justify-center mb-6">
        <motion.div
          initial={{ scale: 0.5, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ duration: 0.4, type: 'spring', stiffness: 200 }}
          className="text-center"
        >
          <div
            className="font-heading text-6xl font-extrabold leading-none"
            style={{ color: overallColor }}
          >
            {Math.round(data.overall_score)}
          </div>
          <div className="text-xs font-mono mt-1" style={{ color: overallColor }}>
            {overallLabel}
          </div>
          <div className="text-[10px] text-[var(--text-dim)] font-mono mt-0.5">
            out of 100
          </div>
        </motion.div>
      </div>

      {/* Category Bars */}
      <div className="space-y-4">
        {categories.map((cat, i) => (
          <CategoryBar key={cat.name} category={cat} index={i} />
        ))}
      </div>

      {/* Summary */}
      {data.summary && (
        <p className="text-xs text-[var(--text-dim)] font-mono mt-5 leading-relaxed">
          {data.summary}
        </p>
      )}
    </motion.div>
  );
}
