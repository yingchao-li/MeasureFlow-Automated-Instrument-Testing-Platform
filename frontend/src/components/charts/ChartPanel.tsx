import type { ReactNode } from 'react';
import type { LucideIcon } from 'lucide-react';
import { cn, EmptyState, ErrorState, Panel, Skeleton } from '@/components/ui';

export type ChartStatus = 'loading' | 'ready' | 'empty' | 'error';

interface ChartPanelProps {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  height: number;
  status: ChartStatus;
  error?: unknown;
  onRetry?: () => void;
  emptyIcon?: LucideIcon;
  emptyTitle?: string;
  emptyDescription?: ReactNode;
  emptyAction?: ReactNode;
  /** Notice centred over the (dimmed) chart, e.g. "Paused - test running". */
  overlay?: ReactNode;
  /** Dim the chart (stale or paused data). */
  dimmed?: boolean;
  footer?: ReactNode;
  /** Screen-reader summary of what the chart shows. */
  summary?: string;
  className?: string;
  children: ReactNode;
}

/** Panel + the four chart states: loading skeleton, empty (instructive), error (with retry), ready. */
export function ChartPanel({
  title,
  description,
  actions,
  height,
  status,
  error,
  onRetry,
  emptyIcon,
  emptyTitle = 'No data yet',
  emptyDescription,
  emptyAction,
  overlay,
  dimmed,
  footer,
  summary,
  className,
  children,
}: ChartPanelProps) {
  return (
    <Panel title={title} description={description} actions={actions} flush className={className}>
      <div className="relative px-2 pb-1 pt-3" style={{ minHeight: height + 16 }}>
        {status === 'loading' && <Skeleton className="mx-2" style={{ height }} />}
        {status === 'error' && <ErrorState error={error} onRetry={onRetry} compact />}
        {status === 'empty' && <EmptyState icon={emptyIcon} title={emptyTitle} description={emptyDescription} action={emptyAction} compact />}
        {status === 'ready' && (
          <div role="group" aria-label={`${title} chart`} aria-busy={dimmed || undefined} className={cn('transition-opacity duration-150', dimmed && 'opacity-40')}>
            {summary && <p className="sr-only">{summary}</p>}
            {children}
          </div>
        )}
        {overlay && status === 'ready' && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
            <div role="status" className="pointer-events-auto rounded-md border border-border-strong bg-surface px-3 py-1.5 text-xs font-medium text-ink shadow-pop">
              {overlay}
            </div>
          </div>
        )}
      </div>
      {footer && <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border px-4 py-1.5">{footer}</div>}
    </Panel>
  );
}
