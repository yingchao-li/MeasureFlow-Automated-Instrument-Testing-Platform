import { act, screen } from '@testing-library/react';
import { api } from '@/api';
import { ApiError } from '@/api/errors';
import type { Health } from '@/api/types';
import { HealthProvider } from '@/context/HealthContext';
import { makeInstrument, makeLive } from '@/test/fixtures';
import { renderWithProviders } from '@/test/utils';
import { OverviewPage } from './OverviewPage';

function health(over: Partial<Health> = {}): Health {
  return {
    status: 'ok',
    version: '0.1.0',
    time: 't',
    uptime_s: 100,
    instruments_online: 3,
    instruments_total: 3,
    running_test: null,
    software: { backend: '0.1.0', simulator: '0.1.0', config_version: '1.0.0' },
    checks: [{ name: 'results_dir_writable', status: 'ok', detail: 'ok' }],
    ...over,
  };
}

function mockApi(h: Health, connected = true) {
  const inst = [
    makeInstrument({ id: 'siggen', state: connected ? 'connected' : 'disconnected' }),
    makeInstrument({ id: 'analyzer', name: 'Virtual Audio Analyzer', kind: 'audio_analyzer', port: 5026, settings: { points: 16384, sample_rate_hz: 48000, acquisition_stored: false } } as never),
    makeInstrument({ id: 'dut', name: 'Virtual Hearing-Aid DUT', kind: 'device_under_test', port: 5027, calibration: null, settings: null } as never),
  ];
  inst[1] = { ...inst[1], state: connected ? 'connected' : 'disconnected' } as never;
  inst[2] = { ...inst[2], state: connected ? 'connected' : 'disconnected' } as never;
  return {
    health: vi.spyOn(api, 'health').mockResolvedValue(h),
    instruments: vi.spyOn(api, 'instruments').mockResolvedValue({ instruments: inst }),
    live: vi.spyOn(api, 'live').mockResolvedValue(makeLive()),
    summary: vi.spyOn(api, 'reportSummary').mockResolvedValue({
      generated_at: 't',
      runs: { total: 0, PASS: 0, FAIL: 0, ERROR: 0, CANCELLED: 0 },
      tasks: { total: 0, PASS: 0, FAIL: 0, ERROR: 0, CANCELLED: 0, pass_rate: null },
      by_kind: {},
      by_firmware: [],
      failure_reasons: [],
      recovery: { tasks_with_retry: 0, recovered: 0, unrecovered: 0, recovery_rate: null },
      trend: [],
    }),
    runs: vi.spyOn(api, 'testRuns').mockResolvedValue({ total: 0, runs: [] }),
    logs: vi.spyOn(api, 'logs').mockResolvedValue({ logs: [], last_seq: 0 }),
  };
}

/** Advance in small steps so React can commit state between timers (a single large act() would batch them). */
async function advance(ms: number, step = 100) {
  for (let t = 0; t < ms; t += step) {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(step);
    });
  }
}

function renderOverview() {
  return renderWithProviders(
    <HealthProvider>
      <OverviewPage />
    </HealthProvider>,
  );
}

describe('OverviewPage live signal gating', () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it('polls /measurements/live at about 2 Hz while instruments are connected and idle', async () => {
    const m = mockApi(health());
    renderOverview();
    await advance(2100);
    expect(m.live.mock.calls.length).toBeGreaterThanOrEqual(3);
    expect(m.live.mock.calls.length).toBeLessThanOrEqual(6);
    expect(screen.getAllByText('Live').length).toBeGreaterThan(0);
    expect(screen.getByText('0.3530')).toBeInTheDocument(); // RMS readout comes from the API response
    expect(screen.getByText('19.98')).toBeInTheDocument();
  });

  it('does not request live data and says "paused — test running" while a test owns the instruments', async () => {
    const m = mockApi(health({ running_test: 'run-20261116-172129-a1b2' }));
    renderOverview();
    await advance(2500);
    expect(m.live).not.toHaveBeenCalled();
    expect(screen.getAllByText(/Paused — test running/).length).toBeGreaterThan(0);
  });

  it('treats INSTRUMENT_BUSY from the backend as a paused state, not an error', async () => {
    const m = mockApi(health());
    m.live.mockRejectedValue(new ApiError('INSTRUMENT_BUSY', 'instrument leased by run-1', 409));
    renderOverview();
    await advance(1200);
    expect(screen.getAllByText(/Paused — test running/).length).toBeGreaterThan(0);
    expect(screen.queryByText('Acquisition failed')).not.toBeInTheDocument();
  });

  it('offers "Connect all" instead of live data when instruments are disconnected', async () => {
    const m = mockApi(health({ instruments_online: 0 }), false);
    renderOverview();
    await advance(500);
    expect(m.live).not.toHaveBeenCalled();
    expect(screen.getAllByRole('button', { name: /connect all/i }).length).toBeGreaterThan(0);
    expect(screen.getAllByText('Instruments disconnected').length).toBeGreaterThan(0);
  });
});
