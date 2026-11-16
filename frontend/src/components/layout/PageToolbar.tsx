import type { ReactNode } from 'react';
import { RefreshCw } from 'lucide-react';
import { useNow } from '@/hooks/useNow';
import { relativeTime } from '@/lib/format';
import { cn, IconButton } from '@/components/ui';

interface RefreshIndicatorProps {
  lastUpdated: number | null;
  fetching?: boolean;
  stale?: boolean;
  onRefresh?: () => void;
}

/** "Updated 3 s ago" + manual refresh. The label is aria-hidden; changes are not announced (too chatty). */
export function RefreshIndicator({ lastUpdated, fetching, stale, onRefresh }: RefreshIndicatorProps) {
  const now = useNow(1000);
  return (
    <div className="flex items-center gap-1.5">
      <span className={cn('mono text-[11px]', stale ? 'text-warn-text' : 'text-ink-3')} title={lastUpdated ? new Date(lastUpdated).toLocaleString() : undefined}>
        {lastUpdated ? (stale ? `Stale · ${relativeTime(lastUpdated, now)}` : `Updated ${relativeTime(lastUpdated, now)}`) : 'Waiting for data'}
      </span>
      {onRefresh && (
        <IconButton label="Refresh now" onClick={onRefresh}>
          <RefreshCw aria-hidden className={cn('h-3.5 w-3.5', fetching && 'animate-spin')} />
        </IconButton>
      )}
    </div>
  );
}

interface PageToolbarProps {
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
  /** Optional 0..1 progress shown as a hairline under the toolbar. */
  progress?: number | null;
}

/** Slim sticky toolbar: page title on the left, contextual actions on the right. */
export function PageToolbar({ title, subtitle, actions, progress }: PageToolbarProps) {
  return (
    <header className="sticky top-0 z-20 border-b border-border bg-canvas/95 backdrop-blur-0">
      <div className="flex h-12 items-center justify-between gap-4 px-6">
        <div className="flex min-w-0 items-baseline gap-3">
          <h1 className="truncate text-lg font-semibold tracking-[-0.01em] text-ink">{title}</h1>
          {subtitle && <div className="truncate text-xs text-ink-3">{subtitle}</div>}
        </div>
        <div className="flex shrink-0 items-center gap-3">{actions}</div>
      </div>
      {progress !== undefined && progress !== null && (
        <div aria-hidden className="absolute inset-x-0 bottom-[-1px] h-px bg-transparent">
          <div className="h-[2px] bg-primary transition-[width] duration-150" style={{ width: `${Math.max(0, Math.min(1, progress)) * 100}%` }} />
        </div>
      )}
    </header>
  );
}

export function PageBody({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn('page-fade mx-auto w-full max-w-[1680px] px-6 pb-10 pt-5', className)}>{children}</div>;
}
