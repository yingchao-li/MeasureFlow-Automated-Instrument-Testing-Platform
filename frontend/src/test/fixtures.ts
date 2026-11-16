/* Test fixtures only. The application itself never contains canned data: every number in the UI comes from the API. */
import type { Instrument, LiveMeasurement, RunSummary, Task, TaskStatus } from '@/api/types';

export function makeTask(over: Partial<Task> = {}): Task {
  return {
    task_id: 'run-20261116-172129-a1b2-T001',
    run_id: 'run-20261116-172129-a1b2',
    step_id: 'gain',
    test_name: 'Gain @ 1000 Hz',
    kind: 'gain',
    status: 'PASS',
    inputs: { frequency_hz: 1000, amplitude_vpk: 0.05, function: 'SIN' },
    measured: { value: 19.98, unit: 'dB' },
    limits: { min: 19, max: 21, unit: 'dB' },
    duration_ms: 14.2,
    timestamp: '2026-11-16T17:21:30.043Z',
    attempts: 1,
    message: 'within limits',
    error_code: null,
    dut_profile: 'NORMAL',
    dut_firmware: '1.0.0',
    ...over,
  };
}

export const PASS_TASK = makeTask();
export const FAIL_TASK = makeTask({
  task_id: 'run-20261116-172129-a1b2-T002',
  step_id: 'thd',
  test_name: 'THD @ 1000 Hz',
  kind: 'thd',
  status: 'FAIL',
  measured: { value: 2.31, unit: '%' },
  limits: { min: null, max: 1, unit: '%' },
  message: 'THD 2.31 % above limit 1 %',
  error_code: 'OUT_OF_TOLERANCE_HIGH',
});
export const ERROR_TASK = makeTask({
  task_id: 'run-20261116-172129-a1b2-T003',
  step_id: 'snr',
  test_name: 'SNR @ 1000 Hz',
  kind: 'snr',
  status: 'ERROR',
  measured: null,
  limits: { min: 60, max: null, unit: 'dB' },
  attempts: 3,
  message: 'analyzer did not answer within 2000 ms',
  error_code: 'COMM_TIMEOUT',
});

export function makeSweep(): Task[] {
  return [100, 500, 1000, 4000, 8000].map((f, i) =>
    makeTask({
      task_id: `run-x-T1${i}`,
      step_id: 'sweep',
      test_name: `Gain @ ${f} Hz`,
      kind: 'freq_sweep',
      inputs: { frequency_hz: f, amplitude_vpk: 0.05, measurement: 'gain' },
      measured: { value: 19 + i * 0.4, unit: 'dB' },
      limits: { min: 16, max: 21.5, unit: 'dB' },
      status: (i === 4 ? 'FAIL' : 'PASS') as TaskStatus,
    }),
  );
}

export function makeRun(over: Partial<RunSummary> = {}): RunSummary {
  return {
    run_id: 'run-20261116-172129-a1b2',
    sequence_id: 'full_pipeline',
    sequence_name: 'Full Pipeline',
    label: null,
    status: 'PASS',
    progress: 1,
    current_step: null,
    cancel_requested: false,
    created_at: '2026-11-16T17:21:29.043Z',
    started_at: '2026-11-16T17:21:29.100Z',
    finished_at: '2026-11-16T17:21:34.100Z',
    duration_ms: 5000,
    dut: { profile: 'NORMAL', firmware: '1.0.0' },
    retries: 1,
    counts: { PASS: 6, FAIL: 0, ERROR: 0, CANCELLED: 0, PENDING: 0, RUNNING: 0 },
    error: null,
    ...over,
  };
}

export function makeInstrument(over: Partial<Instrument> = {}): Instrument {
  return {
    id: 'siggen',
    name: 'Virtual Signal Generator',
    kind: 'signal_generator',
    host: '127.0.0.1',
    port: 5025,
    state: 'connected',
    idn: 'MeasureFlow,VSG-1000,SN-SIM-0001,1.0.0',
    firmware: '1.0.0',
    last_error: null,
    last_seen: '2026-11-16T17:21:29.043Z',
    latency_ms: 0.8,
    leased_by: null,
    calibration: { status: 'valid', due: '2027-10-01', days_remaining: 319 },
    settings: { function: 'SIN', frequency_hz: 1000, amplitude_vpk: 0.05, sample_rate_hz: 48000, output: true },
    ...over,
  } as Instrument;
}

export function makeLive(): LiveMeasurement {
  const fs = 48000;
  const n = 256;
  return {
    timestamp: '2026-11-16T17:21:29.043Z',
    stimulus: { function: 'SIN', frequency_hz: 1000, amplitude_vpk: 0.05, output: true },
    waveform: { sample_rate_hz: fs, unit: 'V', samples: Array.from({ length: n }, (_, i) => 0.5 * Math.sin((2 * Math.PI * 1000 * i) / fs)) },
    spectrum: {
      sample_rate_hz: fs,
      nfft: 16384,
      df_hz: 2.93,
      unit: 'dBV',
      freq_hz: Array.from({ length: 64 }, (_, i) => i * 375),
      magnitude: Array.from({ length: 64 }, (_, i) => (i === 3 ? -6 : -100 - i)),
    },
    metrics: { rms_v: 0.353, gain_db: 19.98, thd_percent: 0.12, snr_db: 70.1, noise_floor_dbv: -80.9 },
    duration_ms: 6.2,
    warnings: [],
  };
}
