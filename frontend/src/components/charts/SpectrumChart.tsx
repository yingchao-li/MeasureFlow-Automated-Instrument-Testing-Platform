import { memo, useMemo, useState } from 'react';
import { CartesianGrid, Line, LineChart, ReferenceArea, Tooltip, XAxis, YAxis } from 'recharts';
import { ChartNoAxesColumn } from 'lucide-react';
import { formatHz, formatHzTick, formatNumber } from '@/lib/format';
import { Segmented } from '@/components/ui';
import { ChartCanvas } from './ChartCanvas';
import { ChartPanel } from './ChartPanel';
import { axisLabel, axisStyle, ChartTooltip, ZoomControls } from './chartKit';
import { extent, logTicks, niceTicks } from './scales';
import { useChartTheme } from './useChartTheme';
import { useChartZoom } from './useChartZoom';

interface SpectrumChartProps {
  freqHz: ReadonlyArray<number> | undefined;
  magnitudeDbv: ReadonlyArray<number> | undefined;
  loading?: boolean;
  error?: unknown;
  onRetry?: () => void;
  dimmed?: boolean;
  overlay?: string;
  emptyDescription?: string;
  emptyAction?: React.ReactNode;
  height?: number;
  title?: string;
  initialScale?: 'log' | 'linear';
}

interface Row {
  f: number;
  m: number;
}

/** Single-sided amplitude spectrum in dBV with a log / linear frequency axis, zoom and peak readout. */
export const SpectrumChart = memo(function SpectrumChart({
  freqHz,
  magnitudeDbv,
  loading,
  error,
  onRetry,
  dimmed,
  overlay,
  emptyDescription = 'The spectrum appears here once the analyzer delivers a buffer.',
  emptyAction,
  height = 240,
  title = 'Spectrum',
  initialScale = 'log',
}: SpectrumChartProps) {
  const theme = useChartTheme();
  const [scale, setScale] = useState<'log' | 'linear'>(initialScale);

  const rows = useMemo<Row[]>(() => {
    if (!freqHz || !magnitudeDbv) return [];
    const n = Math.min(freqHz.length, magnitudeDbv.length);
    const out: Row[] = [];
    for (let i = 0; i < n; i++) {
      const f = freqHz[i] as number;
      const m = magnitudeDbv[i] as number;
      if (!Number.isFinite(f) || !Number.isFinite(m)) continue;
      if (scale === 'log' && f <= 0) continue; // DC bin cannot be drawn on a log axis
      out.push({ f, m });
    }
    return out;
  }, [freqHz, magnitudeDbv, scale]);

  const full = useMemo<[number, number] | null>(() => {
    if (rows.length < 2) return null;
    const lo = (rows[0] as Row).f;
    return [scale === 'log' ? Math.max(lo, 1) : lo, (rows[rows.length - 1] as Row).f];
  }, [rows, scale]);
  const zoom = useChartZoom(full);

  const visible = useMemo(() => {
    const d = zoom.domain;
    return d ? rows.filter((r) => r.f >= d[0] && r.f <= d[1]) : rows;
  }, [rows, zoom.domain]);

  const yBounds = useMemo<[number, number]>(() => {
    const ext = extent(visible.map((r) => r.m));
    if (!ext) return [-140, 0];
    const hi = Math.ceil((ext[1] + 5) / 10) * 10;
    const lo = Math.max(Math.floor(ext[0] / 10) * 10, hi - 160);
    return [Math.min(lo, hi - 20), hi];
  }, [visible]);
  const yTicks = useMemo(() => niceTicks(yBounds[0], yBounds[1], 6), [yBounds]);
  const xTicks = useMemo(() => (scale === 'log' && zoom.domain ? logTicks(zoom.domain[0], zoom.domain[1]) : undefined), [scale, zoom.domain]);

  const peak = useMemo(() => {
    let best: Row | null = null;
    for (const r of rows) if (r.f > 0 && (best === null || r.m > best.m)) best = r;
    return best;
  }, [rows]);

  const status = loading && rows.length === 0 ? 'loading' : error && rows.length === 0 ? 'error' : rows.length === 0 ? 'empty' : 'ready';
  const ax = axisStyle(theme);

  return (
    <ChartPanel
      title={title}
      description={peak ? `peak ${formatHz(peak.f)} · ${formatNumber(peak.m, 1)} dBV` : undefined}
      actions={
        <>
          <Segmented<'log' | 'linear'>
            label="Frequency axis"
            size="sm"
            value={scale}
            onChange={(s) => {
              zoom.reset();
              setScale(s);
            }}
            options={[
              { value: 'log', label: 'Log' },
              { value: 'linear', label: 'Linear' },
            ]}
          />
          <ZoomControls zoom={zoom} />
        </>
      }
      height={height}
      status={status}
      error={error}
      onRetry={onRetry}
      emptyIcon={ChartNoAxesColumn}
      emptyTitle="No spectrum"
      emptyDescription={emptyDescription}
      emptyAction={emptyAction}
      dimmed={dimmed}
      overlay={overlay}
      summary={peak ? `Amplitude spectrum, strongest component ${formatHz(peak.f)} at ${formatNumber(peak.m, 1)} dBV.` : 'Amplitude spectrum.'}
    >
      <ChartCanvas height={height} onDoubleClick={zoom.reset}>
        {({ width, height: h }) => (
          <LineChart width={width} height={h} data={visible} margin={{ top: 6, right: 16, bottom: 24, left: 4 }} {...zoom.handlers} accessibilityLayer>
            <CartesianGrid stroke={theme.grid} />
            <XAxis
              dataKey="f"
              type="number"
              scale={scale === 'log' ? 'log' : 'linear'}
              domain={zoom.domain ?? ['dataMin', 'dataMax']}
              allowDataOverflow
              ticks={xTicks}
              tickFormatter={formatHzTick}
              label={axisLabel(theme, 'Frequency (Hz)')}
              {...ax}
            />
            <YAxis
              type="number"
              domain={yBounds}
              ticks={yTicks}
              allowDataOverflow
              width={56}
              tickFormatter={(v: number) => String(Math.round(v))}
              label={axisLabel(theme, 'Level (dBV)', 'insideLeft')}
              {...ax}
            />
            <Tooltip
              isAnimationActive={false}
              cursor={{ stroke: theme.axis, strokeDasharray: '3 3' }}
              content={<ChartTooltip title={(l) => formatHz(Number(l))} row={(e) => `${formatNumber(Number(e.value), 2)} dBV`} />}
            />
            <Line type="linear" dataKey="m" name="Level" stroke={theme.series[2]} strokeWidth={1.25} dot={false} isAnimationActive={false} activeDot={{ r: 3, fill: theme.series[2], stroke: theme.surface }} />
            {zoom.selection && <ReferenceArea x1={zoom.selection.x1} x2={zoom.selection.x2} fill={theme.series[2]} fillOpacity={0.14} stroke={theme.series[2]} strokeOpacity={0.5} />}
          </LineChart>
        )}
      </ChartCanvas>
    </ChartPanel>
  );
});
