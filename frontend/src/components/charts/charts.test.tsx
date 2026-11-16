import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { FirmwareStats, TrendPoint } from '@/api/types';
import { ApiError } from '@/api/errors';
import { makeLive, makeSweep } from '@/test/fixtures';
import { renderWithProviders } from '@/test/utils';
import { FailureReasonsChart, FirmwareMeanChart, FirmwareOutcomeChart, PassRateBars } from './BarCharts';
import { SpectrumChart } from './SpectrumChart';
import { SweepChart } from './SweepChart';
import { TrendChart } from './TrendChart';
import { WaveformChart } from './WaveformChart';
import { logTicks, niceDomain, niceTicks } from './scales';

const live = makeLive();

describe('WaveformChart', () => {
  it('renders the line, axis titles with units and a screen-reader summary when data is present', () => {
    const { container } = renderWithProviders(<WaveformChart samples={live.waveform.samples} sampleRateHz={live.waveform.sample_rate_hz} />);
    expect(container.querySelector('.recharts-line-curve')).not.toBeNull();
    expect(screen.getByText('Time (ms)')).toBeInTheDocument();
    expect(screen.getByText('Amplitude (V)')).toBeInTheDocument();
    expect(screen.getByText(/Waveform of 256 samples, peak amplitude 0\.5000 V/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reset zoom' })).toBeDisabled(); // nothing zoomed yet
    expect(screen.getByRole('button', { name: 'Zoom in' })).toBeEnabled();
  });

  it('shows an instructive empty state (and the supplied action) without data', () => {
    renderWithProviders(<WaveformChart samples={undefined} sampleRateHz={undefined} emptyAction={<button>Connect all</button>} />);
    expect(screen.getByText('No waveform')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Connect all' })).toBeInTheDocument();
    expect(document.querySelector('.recharts-line')).toBeNull();
  });

  it('shows a skeleton while loading and an error with Retry on failure', async () => {
    const { rerender } = renderWithProviders(<WaveformChart samples={undefined} sampleRateHz={undefined} loading />);
    expect(screen.queryByText('No waveform')).not.toBeInTheDocument();
    const onRetry = vi.fn();
    rerender(<WaveformChart samples={undefined} sampleRateHz={undefined} error={new ApiError('COMMUNICATION_ERROR', 'analyzer disconnected', 502)} onRetry={onRetry} />);
    expect(screen.getByRole('alert')).toHaveTextContent('analyzer disconnected');
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(onRetry).toHaveBeenCalled();
  });

  it('dims stale data and shows the paused overlay', () => {
    renderWithProviders(<WaveformChart samples={live.waveform.samples} sampleRateHz={48000} dimmed overlay="Paused — test running" />);
    expect(screen.getByRole('status')).toHaveTextContent('Paused — test running');
    expect(screen.getByRole('group', { name: 'Waveform chart' })).toHaveAttribute('aria-busy', 'true');
  });
});

describe('SpectrumChart', () => {
  it('renders, reports the peak and drops the DC bin on the log axis', async () => {
    const { container } = renderWithProviders(<SpectrumChart freqHz={live.spectrum.freq_hz} magnitudeDbv={live.spectrum.magnitude} />);
    expect(container.querySelector('.recharts-line-curve')).not.toBeNull();
    expect(screen.getByText(/peak 1\.125 kHz · -6\.0 dBV/)).toBeInTheDocument();
    expect(screen.getByRole('radio', { name: 'Log' })).toBeChecked();
    await userEvent.click(screen.getByRole('radio', { name: 'Linear' }));
    expect(screen.getByRole('radio', { name: 'Linear' })).toBeChecked();
    expect(container.querySelector('.recharts-line-curve')).not.toBeNull();
  });

  it('shows the empty state without data', () => {
    renderWithProviders(<SpectrumChart freqHz={[]} magnitudeDbv={[]} />);
    expect(screen.getByText('No spectrum')).toBeInTheDocument();
  });
});

describe('SweepChart', () => {
  it('plots the sweep tasks and lists the markers in the legend', () => {
    const { container } = renderWithProviders(<SweepChart tasks={makeSweep()} />);
    expect(container.querySelector('.recharts-line-curve')).not.toBeNull();
    expect(screen.getByText(/limits 16 … 21\.5 dB/)).toBeInTheDocument();
    expect(screen.getByText('FAIL')).toBeInTheDocument();
    expect(screen.getByText(/Gain sweep with 5 points from 100 Hz to 8 kHz/)).toBeInTheDocument();
  });
  it('is empty when the run has no sweep results', () => {
    renderWithProviders(<SweepChart tasks={[]} />);
    expect(screen.getByText('No sweep points yet')).toBeInTheDocument();
  });
});

describe('TrendChart', () => {
  const points: TrendPoint[] = [
    { timestamp: '2026-11-16T10:00:00.000Z', run_id: 'run-1', kind: 'thd', value: 0.12, unit: '%', status: 'PASS', firmware: '1.0.0' },
    { timestamp: '2026-11-16T11:00:00.000Z', run_id: 'run-2', kind: 'thd', value: 2.1, unit: '%', status: 'FAIL', firmware: '1.2.0' },
    { timestamp: '2026-11-16T12:00:00.000Z', run_id: 'run-3', kind: 'thd', value: 0.13, unit: '%', status: 'PASS', firmware: '1.0.0' },
  ];
  it('draws one series per firmware with toggles that hide a series', async () => {
    const { container } = renderWithProviders(<TrendChart kind="thd" kindLabel="THD" points={points} unit="%" limits={{ min: null, max: 1 }} firmwares={['1.0.0', '1.2.0']} />);
    expect(container.querySelectorAll('.recharts-line-curve').length).toBe(2);
    const toggle120 = screen.getByRole('button', { name: 'fw 1.2.0' });
    expect(toggle120).toHaveAttribute('aria-pressed', 'true');
    await userEvent.click(toggle120);
    expect(toggle120).toHaveAttribute('aria-pressed', 'false');
    expect(container.querySelectorAll('.recharts-line-curve').length).toBe(1);
  });
  it('explains what to do when there are no measurements', () => {
    renderWithProviders(<TrendChart kind="thd" kindLabel="THD" points={[]} unit="%" limits={null} firmwares={[]} />);
    expect(screen.getByText('No THD measurements yet')).toBeInTheDocument();
  });
});

describe('bar charts', () => {
  const firmwares: FirmwareStats[] = [
    { firmware: '1.0.0', tasks: 120, pass: 118, fail: 1, error: 1, pass_rate: 0.983, by_kind: { thd: { count: 10, mean: 0.12, std: 0.01, min: 0.1, max: 0.14, unit: '%' } } },
    { firmware: '1.2.0', tasks: 40, pass: 30, fail: 10, error: 0, pass_rate: 0.75, by_kind: { thd: { count: 10, mean: 2.2, std: 0.3, min: 1.6, max: 2.9, unit: '%' } } },
  ];
  it('PassRateBars lists every measurement kind with counts', () => {
    renderWithProviders(<PassRateBars byKind={{ gain: { count: 40, pass: 36, fail: 4, error: 0, mean: 19.9, std: 0.3, min: 14, max: 20.1, unit: 'dB' } }} />);
    expect(screen.getByText(/Gain 90\.0 percent/)).toBeInTheDocument();
  });
  it('FirmwareOutcomeChart has PASS/FAIL/ERROR toggles', async () => {
    const { container } = renderWithProviders(<FirmwareOutcomeChart firmwares={firmwares} />);
    expect(container.querySelectorAll('.recharts-bar').length).toBe(3);
    await userEvent.click(screen.getByRole('button', { name: 'ERROR' }));
    expect(screen.getByRole('button', { name: 'ERROR' })).toHaveAttribute('aria-pressed', 'false');
  });
  it('FirmwareMeanChart shows mean per firmware, or an empty state for an unknown kind', () => {
    const { rerender } = renderWithProviders(<FirmwareMeanChart firmwares={firmwares} kind="thd" />);
    expect(screen.getByText(/Mean THD per firmware: fw 1\.0\.0 0\.120 %; fw 1\.2\.0 2\.200 %/)).toBeInTheDocument();
    rerender(<FirmwareMeanChart firmwares={firmwares} kind="snr" />);
    expect(screen.getByText('No SNR data per firmware')).toBeInTheDocument();
  });
  it('FailureReasonsChart shows reasons and the empty state', () => {
    const { rerender } = renderWithProviders(<FailureReasonsChart reasons={[{ reason: 'OUT_OF_TOLERANCE_HIGH', count: 12 }, { reason: 'COMM_TIMEOUT', count: 3 }]} />);
    expect(screen.getByText(/OUT_OF_TOLERANCE_HIGH 12, COMM_TIMEOUT 3/)).toBeInTheDocument();
    rerender(<FailureReasonsChart reasons={[]} />);
    expect(within(document.body).getByText('No failures recorded')).toBeInTheDocument();
  });
});

describe('axis helpers', () => {
  it('niceDomain / niceTicks round outwards and handle flat data', () => {
    expect(niceDomain(0.13, 0.97)).toEqual([0, 1]);
    expect(niceTicks(0, 1, 5)).toEqual([0, 0.2, 0.4, 0.6, 0.8, 1]);
    const [lo, hi] = niceDomain(5, 5);
    expect(lo).toBeLessThan(5);
    expect(hi).toBeGreaterThan(5);
  });
  it('logTicks gives 1-2-5 ticks inside the range', () => {
    expect(logTicks(20, 20000)).toEqual([20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000]);
    expect(logTicks(0, 10)).toEqual([]);
  });
});
