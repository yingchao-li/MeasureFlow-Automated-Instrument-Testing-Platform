import { createContext, useContext, useEffect, useMemo, useRef, type ReactNode } from 'react';
import { api } from '@/api';
import { isApiError } from '@/api/errors';
import type { Health } from '@/api/types';
import { usePolling } from '@/hooks/usePolling';
import { useToast } from './ToastContext';

export const HEALTH_INTERVAL_MS = 3000;
export const HEALTH_MAX_BACKOFF_MS = 15000;

interface HealthValue {
  health: Health | undefined;
  error: Error | null;
  /** The backend cannot be reached (connection refused / timed out). Data elsewhere should be treated as stale. */
  offline: boolean;
  isLoading: boolean;
  isFetching: boolean;
  lastUpdated: number | null;
  failureCount: number;
  /** id of the run that currently owns the instruments, or null */
  runningTest: string | null;
  refresh: () => Promise<void>;
}

const HealthContext = createContext<HealthValue | null>(null);

export function HealthProvider({ children }: { children: ReactNode }) {
  const toast = useToast();
  const { data, error, isLoading, isFetching, lastUpdated, failureCount, refresh } = usePolling((signal) => api.health({ signal }), {
    intervalMs: HEALTH_INTERVAL_MS,
    maxBackoffMs: HEALTH_MAX_BACKOFF_MS,
  });

  const offline = error !== null && isApiError(error) && error.isUnreachable;

  // Announce recovery once (the banner itself disappears).
  const wasOffline = useRef(false);
  useEffect(() => {
    if (wasOffline.current && !offline && data) toast.success('Connection restored', 'The backend is reachable again.');
    wasOffline.current = offline;
  }, [offline, data, toast]);

  const value = useMemo<HealthValue>(
    () => ({
      health: data,
      error,
      offline,
      isLoading,
      isFetching,
      lastUpdated,
      failureCount,
      runningTest: data?.running_test ?? null,
      refresh,
    }),
    [data, error, offline, isLoading, isFetching, lastUpdated, failureCount, refresh],
  );
  return <HealthContext.Provider value={value}>{children}</HealthContext.Provider>;
}

export function useHealth(): HealthValue {
  const ctx = useContext(HealthContext);
  if (!ctx) throw new Error('useHealth must be used inside <HealthProvider>');
  return ctx;
}
