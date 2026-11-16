import { act, render, screen } from '@testing-library/react';
import { api } from '@/api';
import { ApiError } from '@/api/errors';
import type { Health } from '@/api/types';
import { OfflineBanner } from '@/components/layout/OfflineBanner';
import { HealthProvider } from './HealthContext';
import { ToastProvider } from './ToastContext';

const HEALTH: Health = {
  status: 'ok',
  version: '0.1.0',
  time: '2026-11-16T17:21:29.043Z',
  uptime_s: 12.3,
  instruments_online: 3,
  instruments_total: 3,
  running_test: null,
  software: { backend: '0.1.0', simulator: '0.1.0', config_version: '1.0.0' },
  checks: [],
};

describe('offline state', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('shows a banner when the backend is unreachable, backs off, and recovers automatically', async () => {
    const health = vi.spyOn(api, 'health').mockResolvedValue(HEALTH);
    render(
      <ToastProvider>
        <HealthProvider>
          <OfflineBanner />
        </HealthProvider>
      </ToastProvider>,
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();

    health.mockRejectedValue(new ApiError('NETWORK_ERROR', 'Cannot reach the backend', 0));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3100);
    });
    expect(screen.getByRole('alert')).toHaveTextContent('Backend unreachable');
    expect(screen.getByRole('alert')).toHaveTextContent('last known state');

    // polling backs off: after the first failure the next try is ~6 s away, not 3 s
    const calls = health.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(health.mock.calls.length).toBe(calls);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3100);
    });
    expect(health.mock.calls.length).toBe(calls + 1);

    health.mockResolvedValue(HEALTH);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(13000);
    });
    expect(screen.queryByText('Backend unreachable.')).not.toBeInTheDocument();
    expect(screen.getByText('Connection restored')).toBeInTheDocument();
  });

  it('an instrument error from the backend (HTTP 502 with error body) is not treated as offline', async () => {
    vi.spyOn(api, 'health').mockRejectedValue(new ApiError('COMMUNICATION_ERROR', 'simulator not reachable', 502));
    render(
      <ToastProvider>
        <HealthProvider>
          <OfflineBanner />
        </HealthProvider>
      </ToastProvider>,
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(100);
    });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
