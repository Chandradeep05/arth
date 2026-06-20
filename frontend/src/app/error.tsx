'use client';

import { useEffect } from 'react';

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error('[ARTH Error Boundary]', error);
  }, [error]);

  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] gap-6 p-8">
      <div className="card p-8 max-w-lg w-full text-center space-y-4">
        <div className="text-4xl">⚠️</div>
        <h2 className="font-heading text-xl font-bold text-[var(--text)]">
          Something went wrong
        </h2>
        <p className="text-sm text-[var(--text-muted)] font-mono">
          {error.message || 'An unexpected error occurred'}
        </p>
        {error.digest && (
          <p className="text-xs text-[var(--text-dim)] font-mono">
            Error ID: {error.digest}
          </p>
        )}
        <button
          onClick={reset}
          className="px-6 py-2 rounded-lg bg-[var(--accent)] text-[var(--bg)] font-medium text-sm hover:opacity-90 transition-opacity cursor-pointer"
        >
          Try Again
        </button>
      </div>
    </div>
  );
}
