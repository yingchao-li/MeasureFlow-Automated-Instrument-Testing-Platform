import { useCallback, useEffect, useRef, useState } from 'react';
import { isApiError } from '@/api/errors';

export interface UsePollingOptions<T> {
  /** Delay between the END of one request and the start of the next. May depend on the latest data. */
  intervalMs: number | ((data: T | undefined) => number);
  /** Set to false to stop polling (data is kept). Default true. */
  enabled?: boolean;
  /** Stop while the tab is hidden and refetch immediately when it becomes visible. Default true. */
  pauseWhenHidden?: boolean;
  /** Upper bound for exponential back-off after failures. Default 15 000 ms. */
  maxBackoffMs?: number;
  /** Changing this value clears the data and refetches immediately (e.g. when a query parameter changes). */
  resetKey?: string | number;
}

/** Delay before the next attempt after `failures` consecutive failures: base * 2^failures, capped. */
export function backoffDelay(baseMs: number, failures: number, maxMs = 15000): number {
  if (failures <= 0) return baseMs;
  return Math.min(maxMs, baseMs * 2 ** Math.min(failures, 8));
}

export interface PollingState<T> {
  data: T | undefined;
  error: Error | null;
  /** true until the first response (success or failure) for the current resetKey */
  isLoading: boolean;
  /** true while a request is in flight */
  isFetching: boolean;
  /** epoch ms of the last successful response */
  lastUpdated: number | null;
  /** consecutive failures */
  failureCount: number;
  /** Fetch now (cancels a pending timer and any in-flight request). */
  refresh: () => Promise<void>;
}

/**
 * Generic polling hook.
 *  - schedules the next request after the previous one finished (no overlapping requests)
 *  - exponential back-off on failures (interval * 2^n, capped), reset on success
 *  - stops while the tab is hidden, refetches on return
 *  - keeps the last good data on error (callers can dim it as stale)
 *  - aborts in-flight requests on unmount / disable / resetKey change
 */
export function usePolling<T>(fetcher: (signal: AbortSignal) => Promise<T>, options: UsePollingOptions<T>): PollingState<T> {
  const { enabled = true, pauseWhenHidden = true, maxBackoffMs = 15000, resetKey = 0 } = options;

  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const intervalRef = useRef(options.intervalMs);
  intervalRef.current = options.intervalMs;
  const dataRef = useRef<T | undefined>(undefined);
  const refreshRef = useRef<() => Promise<void>>(() => Promise.resolve());

  const [data, setData] = useState<T | undefined>(undefined);
  const [error, setError] = useState<Error | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isFetching, setIsFetching] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);
  const [failureCount, setFailureCount] = useState(0);

  // New query: drop data that belongs to the previous one.
  const lastKey = useRef(resetKey);
  useEffect(() => {
    if (lastKey.current !== resetKey) {
      lastKey.current = resetKey;
      dataRef.current = undefined;
      setData(undefined);
      setError(null);
      setIsLoading(true);
      setLastUpdated(null);
      setFailureCount(0);
    }
  }, [resetKey]);

  useEffect(() => {
    if (!enabled) {
      refreshRef.current = async () => {};
      return;
    }
    let disposed = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let controller: AbortController | null = null;
    let failures = 0;
    let generation = 0;

    const isHidden = () => pauseWhenHidden && typeof document !== 'undefined' && document.hidden;

    const nextDelay = () => {
      const iv = intervalRef.current;
      const base = typeof iv === 'function' ? iv(dataRef.current) : iv;
      return backoffDelay(base, failures, maxBackoffMs);
    };

    const schedule = () => {
      if (disposed) return;
      clearTimeout(timer);
      if (isHidden()) return;
      timer = setTimeout(() => void run(), nextDelay());
    };

    const run = async (): Promise<void> => {
      if (disposed) return;
      clearTimeout(timer);
      controller?.abort();
      const mine = ++generation;
      const ctl = new AbortController();
      controller = ctl;
      setIsFetching(true);
      try {
        const result = await fetcherRef.current(ctl.signal);
        if (disposed || mine !== generation) return;
        failures = 0;
        dataRef.current = result;
        setData(result);
        setError(null);
        setFailureCount(0);
        setLastUpdated(Date.now());
      } catch (e) {
        if (disposed || mine !== generation) return;
        if (ctl.signal.aborted || (isApiError(e) && e.isAbort)) return;
        failures += 1;
        setError(e instanceof Error ? e : new Error(String(e)));
        setFailureCount(failures);
      }
      if (disposed || mine !== generation) return;
      setIsLoading(false);
      setIsFetching(false);
      schedule();
    };

    const onVisibility = () => {
      if (document.hidden) {
        clearTimeout(timer);
        if (pauseWhenHidden) {
          controller?.abort();
          generation += 1;
          setIsFetching(false);
        }
      } else {
        void run();
      }
    };

    refreshRef.current = run;
    if (pauseWhenHidden) document.addEventListener('visibilitychange', onVisibility);
    if (!isHidden()) void run();

    return () => {
      disposed = true;
      clearTimeout(timer);
      controller?.abort();
      document.removeEventListener('visibilitychange', onVisibility);
      refreshRef.current = async () => {};
    };
  }, [enabled, pauseWhenHidden, maxBackoffMs, resetKey]);

  const refresh = useCallback(() => refreshRef.current(), []);

  return { data, error, isLoading, isFetching, lastUpdated, failureCount, refresh };
}
