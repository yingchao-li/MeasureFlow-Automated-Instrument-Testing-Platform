import { useRef } from 'react';
import { api } from '@/api';
import { isApiError } from '@/api/errors';
import type { LiveMeasurement } from '@/api/types';
import { usePolling } from '@/hooks/usePolling';

export const LIVE_INTERVAL_MS = 500; // ~2 Hz
const PAUSED_INTERVAL_MS = 2000;

type LiveResult = { kind: 'frame'; frame: LiveMeasurement } | { kind: 'paused'; reason: 'INSTRUMENT_BUSY' | 'NOT_CONNECTED'; message: string };

async function fetchLive(signal: AbortSignal): Promise<LiveResult> {
  try {
    const frame = await api.live({ points: 1024, bins: 1024 }, { signal });
    return { kind: 'frame', frame };
  } catch (e) {
    // These two are expected states, not failures: do not back off, just show "paused".
    if (isApiError(e) && (e.code === 'INSTRUMENT_BUSY' || e.code === 'NOT_CONNECTED')) {
      return { kind: 'paused', reason: e.code, message: e.message };
    }
    throw e;
  }
}

export type LiveStatus = 'live' | 'test-running' | 'disconnected' | 'offline' | 'error' | 'loading';

interface Options {
  /** all three instruments connected */
  connected: boolean;
  /** id of the run that leases the instruments, or null */
  runningTest: string | null;
  offline: boolean;
}

/**
 * Live acquisition at ~2 Hz. Stops while a test runs (INSTRUMENT_BUSY), while instruments are
 * disconnected, while offline and while the tab is hidden. The last frame is kept for display (dimmed).
 */
export function useLiveMeasurement({ connected, runningTest, offline }: Options) {
  const enabled = connected && !runningTest && !offline;
  const poll = usePolling(fetchLive, {
    enabled,
    intervalMs: (d) => (d?.kind === 'paused' ? PAUSED_INTERVAL_MS : LIVE_INTERVAL_MS),
  });

  const lastFrame = useRef<LiveMeasurement | undefined>(undefined);
  if (poll.data?.kind === 'frame') lastFrame.current = poll.data.frame;

  const pausedByBackend = poll.data?.kind === 'paused' && poll.data.reason === 'INSTRUMENT_BUSY';
  let status: LiveStatus;
  if (offline) status = 'offline';
  else if (runningTest || pausedByBackend) status = 'test-running';
  else if (!connected) status = 'disconnected';
  else if (poll.error && poll.failureCount > 0) status = 'error';
  else if (!lastFrame.current && poll.isLoading) status = 'loading';
  else status = 'live';

  return {
    frame: lastFrame.current,
    status,
    error: poll.error,
    isFetching: poll.isFetching,
    lastUpdated: poll.lastUpdated,
    refresh: poll.refresh,
    isLoading: poll.isLoading && !lastFrame.current,
  };
}
