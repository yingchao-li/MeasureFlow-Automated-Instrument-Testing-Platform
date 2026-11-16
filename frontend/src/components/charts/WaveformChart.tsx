import { memo, useMemo } from 'react';
import { CartesianGrid, Line, LineChart, ReferenceArea, Tooltip, XAxis, YAxis } from 'recharts';
import { AudioWaveform } from 'lucide-react';
import { formatNumber } from '@/lib/format';
import { ChartCanvas } from './ChartCanvas';
import { ChartPanel } from './ChartPanel';
import { axisLabel, axisStyle, ChartTooltip, ZoomControls } from './chartKit';
import { extent, niceTicks, tickDecimals } from './scales';
import { useChartTheme } from './useChartTheme';
import { useChartZoom } from './useChartZoom';

interface WaveformChartProps {
  samples: ReadonlyArray<number> | undefined;
  sampleRateHz: number | undefined;
  unit?: string;
  loading?: boolean;
  error?: unknown;
  onRetry?: () => void;
  dimmed?: boolean;
  overlay?: string;
  emptyDescription?: string;
  emptyAction?: React.ReactNode;
  height?: number;
  title?: string;
}

interface Row {
  t: number;
  v: number;
}

/** Time-domain waveform (volts vs milliseconds) with drag-to-zoom, crosshair tooltip and zoom controls. */
export const WaveformChart = memo(function WaveformChart({
  samples,
  sampleRateHz,
  unit = 'V',
  loading,
  error,
  onRetry,
  dimmed,
  overlay,
  emptyDescription = 'The waveform appears here once the analyzer delivers a buffer.',
  emptyAction,
  height = 240,
  title = 'Waveform',
}: WaveformChartProps) {
  const theme = useChartTheme();
  const rows = useMemo<Row[]>(() => {
    if (!samples || !sampleRateHz || sampleRateHz <= 0) return [];
    const dt = 1000 / sampleRateHz;
    return samples.map((v, i) => ({ t: i * dt, v }));
  }, [samples, sampleRateHz]);

  const full = useMemo<[number, number] | null>(() => (rows.length > 1 ? [0, (rows[rows.length - 1] as Row).t] : null), [rows]);
  const zoom = useChartZoom(full);

  const visible = useMemo(() => {
    const d = zoom.domain;
    return d ? rows.filter((r) => r.t >= d[0] && r.t <= d[1]) : rows;
  }, [rows, zoom.domain]);

  const yTicks = useMemo(() => {
    const ext = extent(visible.map((r) => r.v));
    if (!ext) return [-1, -0.5, 0, 0.5, 1];
    const peak = Math.max(Math.abs(ext[0]), Math.abs(ext[1]), 1e-6) * 1.05;
    return niceTicks(-peak, peak, 6);
  }, [visible]);
  const yDomain = useMemo<[number, number]>(() => [yTicks[0] as number, yTicks[yTicks.length - 1] as number], [yTicks]);
  const yDecimals = tickDecimals(yTicks);
  const xDomain = zoom.domain ?? full;
  const xTicks = useMemo(() => (xDomain ? niceTicks(xDomain[0], xDomain[1], 6).filter((t) => t >= xDomain[0] - 1e-9 && t <= xDomain[1] + 1e-9) : undefined), [xDomain]);
  const xDecimals = xTicks ? tickDecimals(xTicks) : 1;

  const peak = useMemo(() => (rows.length ? Math.max(...rows.map((r) => Math.abs(r.v))) : null), [rows]);
  const status = loading && rows.length === 0 ? 'loading' : error && rows.length === 0 ? 'error' : rows.length === 0 ? 'empty' : 'ready';
  const ax = axisStyle(theme);

  return (
    <ChartPanel
      title={title}
      description={sampleRateHz ? `${rows.length} samples @ ${formatNumber(sampleRateHz / 1000, 1)} kHz` : undefined}
      actions={<ZoomControls zoom={zoom} />}
      height={height}
      status={status}
      error={error}
      onRetry={onRetry}
      emptyIcon={AudioWaveform}
      emptyTitle="No waveform"
      emptyDescription={emptyDescription}
      emptyAction={emptyAction}
      dimmed={dimmed}
      overlay={overlay}
      summary={`Waveform of ${rows.length} samples, peak amplitude ${peak === null ? 'unknown' : formatNumber(peak, 4)} ${unit}.`}
    >
      <ChartCanvas height={height} onDoubleClick={zoom.reset}>
        {({ width, height: h }) => (
          <LineChart width={width} height={h} data={visible} margin={{ top: 6, right: 16, bottom: 24, left: 4 }} {...zoom.handlers} accessibilityLayer>
            <CartesianGrid stroke={theme.grid} vertical strokeDasharray="0" />
            <XAxis
              dataKey="t"
              type="number"
              domain={xDomain ?? ['dataMin', 'dataMax']}
              ticks={xTicks}
              allowDataOverflow
              tickFormatter={(v: number) => formatNumber(v, xDecimals)}
              label={axisLabel(theme, 'Time (ms)')}
              {...ax}
            />
            <YAxis
              type="number"
              domain={yDomain}
              ticks={yTicks}
              allowDataOverflow
              width={56}
              tickFormatter={(v: number) => formatNumber(v, yDecimals)}
              label={axisLabel(theme, `Amplitude (${unit})`, 'insideLeft')}
              {...ax}
            />
            <Tooltip
              isAnimationActive={false}
              cursor={{ stroke: theme.axis, strokeDasharray: '3 3' }}
              content={
                <ChartTooltip
                  title={(l) => `t = ${formatNumber(Number(l), 3)} ms`}
                  row={(e) => `${formatNumber(Number(e.value), 5)} ${unit}`}
                />
              }
            />
            <Line type="linear" dataKey="v" name="Amplitude" stroke={theme.series[0]} strokeWidth={1.5} dot={false} isAnimationActive={false} activeDot={{ r: 3, fill: theme.series[0], stroke: theme.surface }} />
            {zoom.selection && <ReferenceArea x1={zoom.selection.x1} x2={zoom.selection.x2} fill={theme.series[0]} fillOpacity={0.14} stroke={theme.series[0]} strokeOpacity={0.5} />}
          </LineChart>
        )}
      </ChartCanvas>
    </ChartPanel>
  );
});
