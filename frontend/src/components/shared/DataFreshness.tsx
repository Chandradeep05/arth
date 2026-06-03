'use client';

import { useState, useEffect, useCallback } from 'react';

interface DataFreshnessProps {
  timestamp: Date | string | null;
  thresholdMs?: number;
  className?: string;
}

type FreshnessState = 'fresh' | 'delayed' | 'stale' | 'unknown';

function getAgeMs(timestamp: Date | string | null): number | null {
  if (!timestamp) return null;
  const ts = typeof timestamp === 'string' ? new Date(timestamp) : timestamp;
  return Date.now() - ts.getTime();
}

function getFreshnessState(ageMs: number | null, thresholdMs: number): FreshnessState {
  if (ageMs === null) return 'unknown';
  if (ageMs < thresholdMs) return 'fresh';
  if (ageMs < thresholdMs * 4) return 'delayed';
  return 'stale';
}

function formatAge(ageMs: number | null): string {
  if (ageMs === null) return 'No data';
  if (ageMs < 5_000) return 'Just now';
  if (ageMs < 60_000) return `~${Math.round(ageMs / 1000)}s delayed`;
  if (ageMs < 3_600_000) return `${Math.round(ageMs / 60_000)}m ago`;
  return 'Stale';
}

const stateStyles: Record<FreshnessState, { dot: string; text: string }> = {
  fresh: {
    dot: 'bg-[var(--green)]',
    text: 'text-[var(--green)]',
  },
  delayed: {
    dot: 'bg-[var(--gold)]',
    text: 'text-[var(--gold)]',
  },
  stale: {
    dot: 'bg-[var(--red)]',
    text: 'text-[var(--red)]',
  },
  unknown: {
    dot: 'bg-[var(--text-dim)]',
    text: 'text-[var(--text-dim)]',
  },
};

export default function DataFreshness({
  timestamp,
  thresholdMs = 15_000,
  className = '',
}: DataFreshnessProps) {
  const [now, setNow] = useState(Date.now());

  const tick = useCallback(() => setNow(Date.now()), []);

  useEffect(() => {
    const id = setInterval(tick, 1_000);
    return () => clearInterval(id);
  }, [tick]);

  // Use `now` to keep age reactive
  const ageMs = getAgeMs(timestamp);
  const adjustedAge = ageMs !== null ? ageMs + (Date.now() - now) : null;
  const state = getFreshnessState(adjustedAge ?? ageMs, thresholdMs);
  const label = formatAge(adjustedAge ?? ageMs);
  const styles = stateStyles[state];

  return (
    <span
      className={`inline-flex items-center gap-1.5 font-mono text-xs ${styles.text} ${className}`}
    >
      <span className={`inline-block h-1.5 w-1.5 rounded-full ${styles.dot}`} />
      {label}
    </span>
  );
}
