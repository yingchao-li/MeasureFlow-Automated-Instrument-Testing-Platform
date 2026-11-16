import type { ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { Plug } from 'lucide-react';
import type { LiveMeasurement } from '@/api/types';
import { SpectrumChart } from '@/components/charts/SpectrumChart';
import { WaveformChart } from '@/components/charts/WaveformChart';
import { Button, cn, StatusDot } from '@/components/ui';
import { formatHz, formatKindValue, formatNumber } from '@/lib/format';
import type { LiveStatus } from './useLiveMeasurement';

interface LiveSectionProps {
  frame: LiveMeasurement | undefined;
  status: LiveStatus;
  error: Error | null;
  runningTest: string | null;
  onConnectAll: () => void;
  connecting: boolean;
  onRetry: () => void;
}

const STATUS_TEXT: Record<LiveStatus, { tone: 'success' | 'warn' | 'danger' | 'neutral' | 'info'; label: string }> = {
  live: { tone: 'success', label: 'Live' },
  loading: { tone: 'info', label: 'Acquiring' },
  'test-running': { tone: 'info', label: 'Paused — test running' },
  disconnected: { tone: 'neutral', label: 'Instruments disconnected' },
  offline: { tone: 'danger', label: 'Offline — last frame' },
  error: { tone: 'warn', label: 'Acquisition failed' },
};

export function LiveSection({ frame, status, error, runningTest, onConnectAll, connecting, onRetry }: LiveSectionProps) {
  const dimmed = status !== 'live' && status !== 'loading';
  const meta = STATUS_TEXT[status];
  const overlay =
    status === 'test-running' ? `Paused — test ${runningTest ?? ''} is running`.trim() : status === 'offline' ? 'Backend offline — showing last frame' : status === 'disconnected' && frame ? 'Instruments disconnected' : undefined;

  const emptyAction: ReactNode =
    status === 'disconnected' ? (
      <Button variant="primary" size="sm" icon={<Plug aria-hidden className="h-3.5 w-3.5" />} loading={connecting} onClick={onConnectAll}>
        Connect all instruments
      </Button>
    ) : status === 'test-running' ? (
      <Link to="/sequences" className="text-xs font-medium text-primary-text hover:underline">
        View the running test
      </Link>
    ) : undefined;
  const emptyDescription =
    status === 'disconnected'
      ? 'Connect the signal generator, analyzer and DUT to see the live signal.'
      : status === 'test-running'
        ? 'Live acquisition is paused while a test owns the instruments. It resumes when the run ends.'
        : undefined;

  return (
    <section aria-label="Live signal" className="space-y-3">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-2.5">
          <h2 className="text-sm font-semibold text-ink">Live signal</h2>
          <span role="status" aria-live="polite" className={cn('inline-flex items-center gap-1.5 text-xs', status === 'live' ? 'text-ink-2' : 'text-ink-2')}>
            <StatusDot tone={meta.tone} pulse={status === 'live'} />
            {meta.label}
            {status === 'live' && frame && <span className="mono text-ink-3">&middot; 2 Hz &middot; {formatNumber(frame.duration_ms, 1)} ms</span>}
          </span>
          {status === 'error' && error && <span className="max-w-md truncate text-xs text-warn-text">{error.message}</span>}
        </div>
        {frame && (
          <p className="mono text-xs text-ink-3">
            {frame.stimulus.function} &middot; {formatHz(frame.stimulus.frequency_hz)} &middot; {formatNumber(frame.stimulus.amplitude_vpk, 3)} Vpk &middot; output {frame.stimulus.output ? 'ON' : 'OFF'}
          </p>
        )}
      </div>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <WaveformChart
          samples={frame?.waveform.samples}
          sampleRateHz={frame?.waveform.sample_rate_hz}
          unit={frame?.waveform.unit}
          loading={status === 'loading'}
          error={status === 'error' ? error : undefined}
          onRetry={onRetry}
          dimmed={dimmed && Boolean(frame)}
          overlay={overlay}
          emptyDescription={emptyDescription}
          emptyAction={emptyAction}
        />
        <SpectrumChart
          freqHz={frame?.spectrum.freq_hz}
          magnitudeDbv={frame?.spectrum.magnitude}
          loading={status === 'loading'}
          error={status === 'error' ? error : undefined}
          onRetry={onRetry}
          dimmed={dimmed && Boolean(frame)}
          overlay={overlay}
          emptyDescription={emptyDescription}
          emptyAction={emptyAction}
        />
      </div>
      {frame && frame.warnings.length > 0 && (
        <ul className="space-y-0.5 text-xs text-warn-text">
          {frame.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

const METRICS: Array<{ key: keyof LiveMeasurement['metrics']; label: string; unit: string; kind: string }> = [
  { key: 'rms_v', label: 'RMS', unit: 'V', kind: 'rms' },
  { key: 'gain_db', label: 'Gain', unit: 'dB', kind: 'gain' },
  { key: 'thd_percent', label: 'THD', unit: '%', kind: 'thd' },
  { key: 'snr_db', label: 'SNR', unit: 'dB', kind: 'snr' },
  { key: 'noise_floor_dbv', label: 'Noise floor', unit: 'dBV', kind: 'noise_floor' },
];

/** Live scalar readouts. A metric the backend could not compute is null and shows an em dash. */
export function MetricsStrip({ metrics, dimmed }: { metrics: LiveMeasurement['metrics'] | undefined; dimmed?: boolean }) {
  return (
    <dl className={cn('grid w-full grid-cols-5 divide-x divide-border transition-opacity', dimmed && 'opacity-50')}>
      {METRICS.map((m) => {
        const v = metrics?.[m.key];
        return (
          <div key={m.key} className="min-w-0 px-4 py-3 first:pl-0">
            <dt className="eyebrow">{m.label}</dt>
            <dd className="mt-1 flex items-baseline gap-1">
              <span className={cn('mono text-2xl font-medium leading-none', v === null || v === undefined ? 'text-ink-3' : 'text-ink')} aria-label={v === null || v === undefined ? `${m.label} not available` : undefined}>
                {formatKindValue(m.kind, v)}
              </span>
              <span className="mono text-xs text-ink-3">{m.unit}</span>
            </dd>
          </div>
        );
      })}
    </dl>
  );
}
