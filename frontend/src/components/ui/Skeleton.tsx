import type { CSSProperties } from 'react';
import { cn } from './cn';

/** Placeholder block shown while data loads. Respects prefers-reduced-motion (global CSS). */
export function Skeleton({ className, style }: { className?: string; style?: CSSProperties }) {
  return <div aria-hidden className={cn('animate-pulse-soft rounded bg-border', className)} style={style} />;
}

export function SkeletonRows({ rows = 4, className }: { rows?: number; className?: string }) {
  return (
    <div role="status" aria-label="Loading" className={cn('space-y-2.5', className)}>
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className={cn('h-4', i % 3 === 2 ? 'w-2/3' : 'w-full')} />
      ))}
    </div>
  );
}
