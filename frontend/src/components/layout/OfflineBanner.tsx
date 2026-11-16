import { RefreshCw, WifiOff } from 'lucide-react';
import { useHealth, HEALTH_INTERVAL_MS, HEALTH_MAX_BACKOFF_MS } from '@/context/HealthContext';
import { backoffDelay } from '@/hooks/usePolling';
import { relativeTime } from '@/lib/format';
import { useNow } from '@/hooks/useNow';
import { Button } from '@/components/ui';

/** Shown while the backend is unreachable. Polling backs off automatically; data below stays visible but dimmed. */
export function OfflineBanner() {
  const { offline, lastUpdated, failureCount, refresh, isFetching } = useHealth();
  const now = useNow(1000);
  if (!offline) return null;
  const retryS = Math.round(backoffDelay(HEALTH_INTERVAL_MS, failureCount, HEALTH_MAX_BACKOFF_MS) / 1000);
  return (
    <div role="alert" className="flex items-center gap-3 border-b border-danger/40 bg-danger-soft px-6 py-2 text-danger-text">
      <WifiOff aria-hidden className="h-4 w-4 shrink-0" />
      <p className="min-w-0 flex-1 text-sm">
        <span className="font-semibold">Backend unreachable.</span>{' '}
        <span className="text-ink-2">
          Retrying about every {retryS} s{lastUpdated ? ` · last contact ${relativeTime(lastUpdated, now)}` : ''}. Values shown below are the last known state.
        </span>
      </p>
      <Button size="sm" variant="secondary" loading={isFetching} icon={<RefreshCw aria-hidden className="h-3.5 w-3.5" />} onClick={() => void refresh()}>
        Retry now
      </Button>
    </div>
  );
}
