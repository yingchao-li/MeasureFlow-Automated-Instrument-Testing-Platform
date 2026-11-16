import type { ReactNode } from 'react';
import { RefreshCw, TriangleAlert, WifiOff, type LucideIcon } from 'lucide-react';
import { ApiError, errorMessage, errorTitle } from '@/api/errors';
import { cn } from './cn';
import { Button } from './Button';

interface EmptyStateProps {
  icon?: LucideIcon;
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  className?: string;
  compact?: boolean;
}

/** Empty list / no data. Always says what to do next. */
export function EmptyState({ icon: Icon, title, description, action, className, compact }: EmptyStateProps) {
  return (
    <div className={cn('flex flex-col items-center justify-center text-center', compact ? 'px-4 py-6' : 'px-6 py-12', className)}>
      {Icon && (
        <div className="mb-3 flex h-8 w-8 items-center justify-center rounded-md border border-border bg-sunken text-ink-3">
          <Icon aria-hidden className="h-4 w-4" />
        </div>
      )}
      <p className="text-sm font-medium text-ink">{title}</p>
      {description && <p className="mt-1 max-w-sm text-xs leading-5 text-ink-2">{description}</p>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}

interface ErrorStateProps {
  error: unknown;
  onRetry?: () => void;
  className?: string;
  compact?: boolean;
  title?: string;
}

/** Error with the backend message (from the unified error body), a code chip and a Retry button. */
export function ErrorState({ error, onRetry, className, compact, title }: ErrorStateProps) {
  const api = error instanceof ApiError ? error : null;
  const Icon = api?.isOffline ? WifiOff : TriangleAlert;
  return (
    <div role="alert" className={cn('flex flex-col items-center justify-center text-center', compact ? 'px-4 py-6' : 'px-6 py-12', className)}>
      <div className="mb-3 flex h-8 w-8 items-center justify-center rounded-md border border-border bg-danger-soft text-danger-text">
        <Icon aria-hidden className="h-4 w-4" />
      </div>
      <p className="text-sm font-medium text-ink">{title ?? errorTitle(error)}</p>
      <p className="mt-1 max-w-md break-words text-xs leading-5 text-ink-2">{errorMessage(error)}</p>
      {api && api.code !== 'NETWORK_ERROR' && (
        <p className="mono mt-2 rounded bg-sunken px-1.5 py-0.5 text-[11px] text-ink-3">
          {api.code}
          {api.status ? ` · HTTP ${api.status}` : ''}
        </p>
      )}
      {onRetry && (
        <Button size="sm" className="mt-3" icon={<RefreshCw aria-hidden className="h-3.5 w-3.5" />} onClick={onRetry}>
          Retry
        </Button>
      )}
    </div>
  );
}
