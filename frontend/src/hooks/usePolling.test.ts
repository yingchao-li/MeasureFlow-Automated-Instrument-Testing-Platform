import { act, renderHook } from '@testing-library/react';
import { ApiError } from '@/api/errors';
import { backoffDelay, usePolling } from './usePolling';

function setHidden(hidden: boolean) {
  Object.defineProperty(document, 'hidden', { configurable: true, get: () => hidden });
  document.dispatchEvent(new Event('visibilitychange'));
}

describe('usePolling', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    setHidden(false);
  });
  afterEach(() => {
    setHidden(false);
    vi.useRealTimers();
  });

  it('fetches immediately, then every interval after the previous request finished', async () => {
    const fetcher = vi.fn(async () => 'x');
    const { result } = renderHook(() => usePolling(fetcher, { intervalMs: 1000 }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(result.current.data).toBe('x');
    expect(result.current.isLoading).toBe(false);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    expect(fetcher).toHaveBeenCalledTimes(3);
  });

  it('never overlaps requests: a slow response delays the next poll', async () => {
    let resolve: ((v: string) => void) | undefined;
    const fetcher = vi.fn(() => new Promise<string>((r) => (resolve = r)));
    renderHook(() => usePolling(fetcher, { intervalMs: 100 }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(fetcher).toHaveBeenCalledTimes(1); // still waiting for the first response
    await act(async () => {
      resolve?.('done');
      await vi.advanceTimersByTimeAsync(150);
    });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it('backs off exponentially on failures, keeps stale data, and recovers', async () => {
    let fail = false;
    const fetcher = vi.fn(async () => {
      if (fail) throw new ApiError('NETWORK_ERROR', 'down', 0);
      return 'good';
    });
    const { result } = renderHook(() => usePolling(fetcher, { intervalMs: 1000, maxBackoffMs: 8000 }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.data).toBe('good');

    fail = true;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000); // poll #2 fails
    });
    expect(result.current.error).toBeInstanceOf(ApiError);
    expect(result.current.failureCount).toBe(1);
    expect(result.current.data).toBe('good'); // stale data is kept

    const callsAfterFirstFailure = fetcher.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1900); // next retry is due after 2 s (1 s * 2^1)
    });
    expect(fetcher).toHaveBeenCalledTimes(callsAfterFirstFailure);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });
    expect(fetcher).toHaveBeenCalledTimes(callsAfterFirstFailure + 1);
    expect(result.current.failureCount).toBe(2);

    fail = false;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(4100); // 1 s * 2^2
    });
    expect(result.current.error).toBeNull();
    expect(result.current.failureCount).toBe(0);
  });

  it('computes the back-off delay with a cap', () => {
    expect(backoffDelay(1000, 0)).toBe(1000);
    expect(backoffDelay(1000, 1)).toBe(2000);
    expect(backoffDelay(1000, 3)).toBe(8000);
    expect(backoffDelay(3000, 6, 15000)).toBe(15000);
  });

  it('stops while the tab is hidden and refetches immediately when it becomes visible', async () => {
    const fetcher = vi.fn(async () => 1);
    renderHook(() => usePolling(fetcher, { intervalMs: 500 }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(fetcher).toHaveBeenCalledTimes(1);

    act(() => setHidden(true));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(fetcher).toHaveBeenCalledTimes(1);

    act(() => setHidden(false));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it('does not poll when disabled but keeps the last data, and resumes when enabled again', async () => {
    const fetcher = vi.fn(async () => 'v');
    const { result, rerender } = renderHook(({ enabled }) => usePolling(fetcher, { intervalMs: 500, enabled }), { initialProps: { enabled: true } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    rerender({ enabled: false });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(result.current.data).toBe('v');
    rerender({ enabled: true });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it('supports an interval that depends on the latest data', async () => {
    let n = 0;
    const fetcher = vi.fn(async () => ++n);
    renderHook(() => usePolling(fetcher, { intervalMs: (d) => (d === 1 ? 100 : 1000) }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(120); // after data=1 the next poll is due in 100 ms
    });
    expect(fetcher).toHaveBeenCalledTimes(2);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500); // data=2 -> 1000 ms
    });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });

  it('clears data and refetches when resetKey changes', async () => {
    const fetcher = vi.fn(async (_s: AbortSignal) => 'a');
    const { result, rerender } = renderHook(({ k }) => usePolling(fetcher, { intervalMs: 1000, resetKey: k }), { initialProps: { k: 'one' } });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.data).toBe('a');
    fetcher.mockImplementation(async () => 'b');
    rerender({ k: 'two' });
    expect(result.current.data).toBeUndefined();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(result.current.data).toBe('b');
  });

  it('aborts the in-flight request on unmount and ignores its late result', async () => {
    let signal: AbortSignal | undefined;
    let resolve: ((v: string) => void) | undefined;
    const fetcher = vi.fn((s: AbortSignal) => {
      signal = s;
      return new Promise<string>((r) => (resolve = r));
    });
    const { result, unmount } = renderHook(() => usePolling(fetcher, { intervalMs: 1000 }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    unmount();
    expect(signal?.aborted).toBe(true);
    resolve?.('late');
    await vi.advanceTimersByTimeAsync(2000);
    expect(result.current.data).toBeUndefined();
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it('refresh() fetches right away', async () => {
    const fetcher = vi.fn(async () => 'r');
    const { result } = renderHook(() => usePolling(fetcher, { intervalMs: 60000 }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    await act(async () => {
      await result.current.refresh();
    });
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
});
