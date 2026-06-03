interface LoadingSkeletonProps {
  variant?: 'card' | 'chart' | 'text' | 'table';
  lines?: number;
  className?: string;
}

function TextSkeleton({ lines = 3 }: { lines: number }) {
  const widths = ['w-full', 'w-5/6', 'w-4/6', 'w-3/4', 'w-2/3', 'w-5/6'];
  return (
    <div className="space-y-2.5">
      {Array.from({ length: lines }).map((_, i) => (
        <div
          key={i}
          className={`h-3 rounded ${widths[i % widths.length]} skeleton-shimmer`}
        />
      ))}
    </div>
  );
}

function ChartSkeleton() {
  return (
    <div className="space-y-3">
      <div className="flex items-end gap-1 h-32">
        {Array.from({ length: 20 }).map((_, i) => (
          <div
            key={i}
            className="flex-1 rounded-t skeleton-shimmer"
            style={{ height: `${20 + Math.random() * 80}%` }}
          />
        ))}
      </div>
      <div className="h-2 w-full rounded skeleton-shimmer" />
    </div>
  );
}

function CardSkeleton() {
  return (
    <div className="space-y-3 p-4">
      <div className="flex items-center justify-between">
        <div className="h-4 w-24 rounded skeleton-shimmer" />
        <div className="h-3 w-16 rounded skeleton-shimmer" />
      </div>
      <div className="h-8 w-32 rounded skeleton-shimmer" />
      <div className="flex gap-2">
        <div className="h-3 w-16 rounded skeleton-shimmer" />
        <div className="h-3 w-20 rounded skeleton-shimmer" />
      </div>
    </div>
  );
}

function TableSkeleton({ lines = 5 }: { lines: number }) {
  return (
    <div className="space-y-2">
      {/* Header */}
      <div className="flex gap-4 pb-2 border-b border-[var(--border)]">
        <div className="h-3 w-20 rounded skeleton-shimmer" />
        <div className="h-3 w-32 rounded skeleton-shimmer" />
        <div className="h-3 w-16 rounded skeleton-shimmer" />
        <div className="h-3 w-20 rounded skeleton-shimmer" />
      </div>
      {/* Rows */}
      {Array.from({ length: lines }).map((_, i) => (
        <div key={i} className="flex gap-4 py-1.5">
          <div className="h-3 w-20 rounded skeleton-shimmer" />
          <div className="h-3 w-32 rounded skeleton-shimmer" />
          <div className="h-3 w-16 rounded skeleton-shimmer" />
          <div className="h-3 w-20 rounded skeleton-shimmer" />
        </div>
      ))}
    </div>
  );
}

export default function LoadingSkeleton({
  variant = 'card',
  lines = 3,
  className = '',
}: LoadingSkeletonProps) {
  return (
    <div className={`animate-pulse ${className}`} role="status" aria-label="Loading">
      {variant === 'text' && <TextSkeleton lines={lines} />}
      {variant === 'chart' && <ChartSkeleton />}
      {variant === 'card' && <CardSkeleton />}
      {variant === 'table' && <TableSkeleton lines={lines} />}
      <span className="sr-only">Loading...</span>
    </div>
  );
}
