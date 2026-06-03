'use client';

import { useMemo } from 'react';

interface ConfidenceScoreProps {
  score: number;  // 0–100
  label?: string;
  showBar?: boolean;
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}

function getConfidenceColor(score: number): string {
  if (score < 40) return 'var(--red)';
  if (score < 60) return 'var(--accent-orange)';
  if (score < 80) return 'var(--gold)';
  return 'var(--accent-green)';
}

function getConfidenceLabel(score: number): string {
  if (score < 40) return 'Low';
  if (score < 60) return 'Moderate';
  if (score < 80) return 'Good';
  return 'High';
}

const sizeMap = {
  sm: { text: 'text-xs', barH: 'h-1', width: 'w-16' },
  md: { text: 'text-sm', barH: 'h-1.5', width: 'w-24' },
  lg: { text: 'text-base', barH: 'h-2', width: 'w-32' },
} as const;

export default function ConfidenceScore({
  score,
  label,
  showBar = true,
  size = 'sm',
  className = '',
}: ConfidenceScoreProps) {
  const clampedScore = Math.max(0, Math.min(100, score));
  const color = useMemo(() => getConfidenceColor(clampedScore), [clampedScore]);
  const confidenceLabel = useMemo(() => getConfidenceLabel(clampedScore), [clampedScore]);
  const sizeConfig = sizeMap[size];

  return (
    <div
      className={`inline-flex items-center gap-2 ${className}`}
      title={`Confidence: ${clampedScore}% — ${confidenceLabel}${label ? ` (${label})` : ''}`}
    >
      {showBar && (
        <div
          className={`${sizeConfig.width} ${sizeConfig.barH} rounded-full overflow-hidden bg-[var(--surface-2)]`}
        >
          <div
            className={`${sizeConfig.barH} rounded-full transition-all duration-500 ease-out`}
            style={{
              width: `${clampedScore}%`,
              backgroundColor: color,
            }}
          />
        </div>
      )}
      <span
        className={`font-mono ${sizeConfig.text} font-medium`}
        style={{ color }}
      >
        {clampedScore}%
      </span>
      {label && (
        <span className={`${sizeConfig.text} text-[var(--text-muted)]`}>
          {label}
        </span>
      )}
    </div>
  );
}
