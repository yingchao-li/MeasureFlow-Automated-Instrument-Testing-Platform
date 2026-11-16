import { memo, useMemo } from 'react';
import { CartesianGrid, ComposedChart, Line, ReferenceArea, ReferenceLine, Tooltip, XAxis, YAxis } from 'recharts';
import { Activity } from 'lucide-react';
import type { Task } from '@/api/types';
import { formatHz, formatHzTick, formatLimits, formatNumber } from '@/lib/format';
import { ChartCanvas } from './ChartCanvas';
import { ChartPanel } from './ChartPanel';
import { axisLabel, axisStyle, ChartTooltip, LegendToggles, StatusMarker } from './chartKit';
import { extent, logTicks, niceTicks } from './scales';
import { useChartTheme } from './useChartTheme';

interface Row {
  f: number;
  gain: number;
  status: string;
  name: string;
}

/** Gain vs frequency from the `freq_sweep` tasks of one run, with the tolerance band. */
export const SweepChart = memo(function SweepChart({ tasks, height = 220 }: { tasks: ReadonlyArray<Task>; height?: number }) {
  const theme = useChartTheme();

  const { rows, limits, unit } = useMemo(() => {
    const pts = tasks
      .filter((t) => t.kind === 'freq_sweep' && t.measured && typeof t.inputs.frequency_hz === 'number')
      .map<Row>((t) => ({ f: t.inputs.frequency_hz as number, gain: (t.measured as { value: number }).value, status: t.status, name: t.test_name }))
      .sort((a, b) => a.f - b.f);
    const lim = tasks.find((t) => t.kind === 'freq_sweep' && t.limits)?.limits ?? null;
    return { rows: pts, limits: lim, unit: tasks.find((t) => t.kind === 'freq_sweep' && t.measured)?.measured?.unit ?? 'dB' };
  }, [tasks]);

  const xDomain = useMemo<[number, number]>(() => {
    const e = extent(rows.map((r) => r.f));
    return e ? [Math.max(1, e[0] / 1.15), e[1] * 1.15] : [10, 20000];
  }, [rows]);
  const xTicks = useMemo(() => logTicks(xDomain[0], xDomain[1]), [xDomain]);

  const yBounds = useMemo<[number, number]>(() => {
    const vals = rows.map((r) => r.gain);
    if (limits?.min !== null && limits?.min !== undefined) vals.push(limits.min);
    if (limits?.max !== null && limits?.max !== undefined) vals.push(limits.max);
    const e = extent(vals);
    if (!e) return [0, 1];
    const pad = Math.max((e[1] - e[0]) * 0.15, 0.5);
    return [Math.floor(e[0] - pad), Math.ceil(e[1] + pad)];
  }, [rows, limits]);
  const yTicks = useMemo(() => niceTicks(yBounds[0], yBounds[1], 5), [yBounds]);

  const status = rows.length === 0 ? 'empty' : 'ready';
  const lo = limits?.min ?? null;
  const hi = limits?.max ?? null;
  const ax = axisStyle(theme);

  return (
    <ChartPanel
      title="Gain sweep"
      description={limits ? `limits ${formatLimits(limits)}` : undefined}
      height={height}
      status={status}
      emptyIcon={Activity}
      emptyTitle="No sweep points yet"
      emptyDescription="Gain versus frequency appears here once a sweep step has produced results."
      summary={`Gain sweep with ${rows.length} points from ${rows[0] ? formatHz(rows[0].f) : '-'} to ${rows.length ? formatHz((rows[rows.length - 1] as Row).f) : '-'}.`}
      footer={
        <LegendToggles
          label="Marker legend"
          items={[
            { key: 'pass', label: 'PASS', color: theme.series[0], shape: 'circle' },
            { key: 'fail', label: 'FAIL', color: theme.warn, shape: 'diamond' },
            ...(lo !== null || hi !== null ? [{ key: 'band', label: 'Tolerance band', color: theme.success, shape: 'square' as const }] : []),
          ]}
        />
      }
    >
      <ChartCanvas height={height}>
        {({ width, height: h }) => (
          <ComposedChart width={width} height={h} data={rows} margin={{ top: 8, right: 20, bottom: 24, left: 4 }} accessibilityLayer>
            <CartesianGrid stroke={theme.grid} />
            <XAxis dataKey="f" type="number" scale="log" domain={xDomain} ticks={xTicks} allowDataOverflow tickFormatter={formatHzTick} label={axisLabel(theme, 'Frequency (Hz)')} {...ax} />
            <YAxis type="number" domain={yBounds} ticks={yTicks} allowDataOverflow width={52} tickFormatter={(v: number) => formatNumber(v, 1)} label={axisLabel(theme, `Gain (${unit})`, 'insideLeft')} {...ax} />
            {lo !== null && hi !== null && <ReferenceArea y1={lo} y2={hi} fill={theme.success} fillOpacity={0.1} stroke="none" ifOverflow="extendDomain" />}
            {lo !== null && <ReferenceLine y={lo} stroke={theme.success} strokeDasharray="4 3" strokeOpacity={0.7} />}
            {hi !== null && <ReferenceLine y={hi} stroke={theme.success} strokeDasharray="4 3" strokeOpacity={0.7} />}
            <Tooltip
              isAnimationActive={false}
              cursor={{ stroke: theme.axis, strokeDasharray: '3 3' }}
              content={<ChartTooltip title={(l) => formatHz(Number(l))} row={(e) => `${formatNumber(Number(e.value), 2)} ${unit}${e.payload?.['status'] ? ` · ${String(e.payload['status'])}` : ''}`} />}
            />
            <Line
              type="linear"
              dataKey="gain"
              name="Gain"
              stroke={theme.series[0]}
              strokeWidth={1.5}
              isAnimationActive={false}
              dot={(p: { cx?: number; cy?: number; payload?: Row; index?: number }) => (
                <StatusMarker key={`d-${p.index ?? 0}`} cx={p.cx} cy={p.cy} status={p.payload?.status ?? 'PASS'} color={theme.series[0]} theme={theme} />
              )}
              activeDot={{ r: 5, stroke: theme.surface, fill: theme.series[0] }}
            />
          </ComposedChart>
        )}
      </ChartCanvas>
    </ChartPanel>
  );
});
