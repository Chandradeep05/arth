import { AI_DISCLAIMER } from '@/lib/constants';

interface DisclaimerProps {
  className?: string;
  compact?: boolean;
}

/**
 * Non-dismissible AI disclaimer banner.
 * Required on every page that displays AI-generated content.
 * Intentionally has NO close button — regulatory compliance.
 */
export default function Disclaimer({ className = '', compact = false }: DisclaimerProps) {
  return (
    <div
      role="alert"
      aria-live="polite"
      className={`
        border-l-2 border-[var(--gold)]
        bg-[var(--gold)]/5
        ${compact ? 'px-3 py-1.5' : 'px-4 py-2.5'}
        rounded-r
        select-none
        ${className}
      `}
    >
      <p
        className={`
          font-mono leading-relaxed
          text-[var(--gold)]/80
          ${compact ? 'text-[10px]' : 'text-xs'}
        `}
      >
        {AI_DISCLAIMER}
      </p>
    </div>
  );
}
