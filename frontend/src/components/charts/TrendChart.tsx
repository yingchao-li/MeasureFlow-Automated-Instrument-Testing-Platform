import { memo, useMemo, useState } from 'react';
import { CartesianGrid, ComposedChart, Line, ReferenceArea, ReferenceLine, Tooltip, XAxis, YAxis } from 'recharts';
import { TrendingUp } from 'lucide-react';
import type { TrendPoint } from '@/api/types';
import { formatKindValue, formatNumber } from '@/lib/format';
import { ChartCanvas } from './ChartCanvas';
import { ChartPanel } from './ChartPanel';
import { axisLabel, axisStyle, ChartTooltip, LegendToggles, StatusMarker, ZoomControls } from './chartKit';
import { extent, niceDomain, niceTicks } from './scales';
import { useChartTheme } from './useChartTheme';
import { useChartZoom } from './useChartZoom';

interface TrendChartProps {
  kind: string;
  kindLabel: string;
  points: ReadonlyArray<TrendPoint>;
  unit: string;
  limits: { min: number | null; max: number | null } | null;
  /** all firmware versions (stable colour assignment even when a filter hides some) */
  firmwares: ReadonlyArray<string>;
  loading?: boolean;
  error?: unknown;
  onRetry?: () => void;
  height?: number;
}

type Row = Record<string, number | string | undefined> & { t: number; status: string; fw: string; run_id: string };

function formatTick(ms: number, span: number): string {
  const d = new Date(ms);
  const p = (n: number) => String(n).padStart(2, '0');
  if (span < 36 * 3600 * 1000) return `${p(d.getHours())}:${p(d.getMinutes())}`;
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

/** Measurement value vs time, one series per firmware (toggleable), limits band when known, drag-to-zoom. */
export const TrendChart = memo(function TrendChart({ kind, kindLabel, points, unit, limits, firmwares, loading, error, onRetry, height = 320 }: TrendChartProps) {
  const theme = useChartTheme();
  const [hidden, setHidden] = useState<ReadonlySet<string>>(new Set());

  const rows = useMemo<Row[]>(() => {
    return points
      .map((p) => ({ t: new Date(p.timestamp).getTime(), p }))
      .filter((x) => Number.isFinite(x.t) && !hidden.has(x.p.firmware))
      .sort((a, b) => a.t - b.t)
      .map(({ t, p }) => ({ t, [`v:${p.firmware}`]: p.value, status: p.status, fw: p.firmware, run_id: p.run_id }));
  }, [points, hidden]);

  const full = useMemo<[number, number] | null>(() => {
    const e = extent(rows.map((r) => r.t));
    if (!e) return null;
    return e[0] === e[1] ? [e[0] - 30000, e[1] + 30000] : e;
  }, [rows]);
  const zoom = useChartZoom(full);

  const yDomain = useMemo<[number, number]>(() => {
    const d = zoom.domain;
    const vals = rows.filter((r) => !d || (r.t >= d[0] && r.t <= d[1])).map((r) => r[`v:${r.fw}`] as number);
    if (limits?.min !== null && limits?.min !== undefined) vals.push(limits.min);
    if (limits?.max !== null && limits?.max !== undefined) vals.push(limits.max);
    const e = extent(vals);
    if (!e) return [0, 1];
    const pad = (e[1] - e[0]) * 0.12 || Math.abs(e[0]) * 0.1 || 1;
    return niceDomain(e[0] - pad, e[1] + pad, 5);
  }, [rows, limits, zoom.domain]);
  const yTicks = useMemo(() => niceTicks(yDomain[0], yDomain[1], 5), [yDomain]);

  const colorOf = (fw: string) => theme.categories[Math.max(0, firmwares.indexOf(fw)) % theme.categories.length] as string;
  const shownFirmwares = firmwares.filter((f) => points.some((p) => p.firmware === f));
  const status = loading && points.length === 0 ? 'loading' : error && points.length === 0 ? 'error' : points.length === 0 ? 'empty' : 'ready';
  const span = zoom.domain ? zoom.domain[1] - zoom.domain[0] : 0;
  const ax = axisStyle(theme);
  const lo = limits?.min ?? null;
  const hi = limits?.max ?? null;

  return (
    <ChartPanel
      title={`${kindLabel} trend`}
      description={`${points.length} measurements${limits && (lo !== null || hi !== null) ? ' · shaded band = limits' : ''}`}
      actions={<ZoomControls zoom={zoom} />}
      height={height}
      status={status}
      error={error}
      onRetry={onRetry}
      emptyIcon={TrendingUp}
      emptyTitle={`No ${kindLabel} measurements yet`}
      emptyDescription="Completed runs add one point per measurement. Start a sequence that measures this value."
      summary={`${kindLabel} measured over time, ${points.length} points in ${shownFirmwares.length} firmware series.`}
      footer={
        <>
          <LegendToggles
            label="Firmware series"
            items={shownFirmwares.map((f) => ({ key: f, label: `fw ${f}`, color: colorOf(f), shape: 'line' as const, hidden: hidden.has(f) }))}
            onToggle={(f) =>
              setHidden((h) => {
                const n = new Set(h);
                if (n.has(f)) n.delete(f);
                else n.add(f);
                return n;
              })
            }
          />
          <span className="flex items-center gap-3 text-[11px] text-ink-3">
            <span className="flex items-center gap-1">
              <svg width="10" height="10" aria-hidden>
                <circle cx="5" cy="5" r="3.5" fill={theme.axis} />
              </svg>
              PASS
            </span>
            <span className="flex items-center gap-1">
              <svg width="10" height="10" aria-hidden>
                <path d="M5 0 L10 5 L5 10 L0 5 Z" fill={theme.warn} />
              </svg>
              FAIL
            </span>
          </span>
        </>
      }
    >
      <ChartCanvas height={height} onDoubleClick={zoom.reset}>
        {({ width, height: h }) => (
          <ComposedChart width={width} height={h} data={rows} margin={{ top: 8, right: 20, bottom: 24, left: 4 }} {...zoom.handlers} accessibilityLayer>
            <CartesianGrid stroke={theme.grid} />
            <XAxis dataKey="t" type="number" domain={zoom.domain ?? ['dataMin', 'dataMax']} allowDataOverflow tickFormatter={(v: number) => formatTick(v, span)} label={axisLabel(theme, 'Time')} {...ax} />
            <YAxis type="number" domain={yDomain} ticks={yTicks} allowDataOverflow width={60} tickFormatter={(v: number) => formatKindValue(kind, v)} label={axisLabel(theme, `${kindLabel} (${unit})`, 'insideLeft')} {...ax} />
            {lo !== null && hi !== null && <ReferenceArea y1={lo} y2={hi} fill={theme.success} fillOpacity={0.1} stroke="none" ifOverflow="hidden" />}
            {lo !== null && <ReferenceLine y={lo} stroke={theme.success} strokeDasharray="4 3" strokeOpacity={0.7} ifOverflow="hidden" />}
            {hi !== null && <ReferenceLine y={hi} stroke={theme.success} strokeDasharray="4 3" strokeOpacity={0.7} ifOverflow="hidden" />}
            <Tooltip
              isAnimationActive={false}
              cursor={{ stroke: theme.axis, strokeDasharray: '3 3' }}
              content={
                <ChartTooltip
                  title={(l) => new Date(Number(l)).toLocaleString()}
                  row={(e) => {
                    if (typeof e.value !== 'number') return null;
                    const pl = e.payload ?? {};
                    return `fw ${String(pl['fw'])} · ${formatNumber(e.value, 4)} ${unit} · ${String(pl['status'])} · ${String(pl['run_id']).replace('run-', '')}`;
                  }}
                />
              }
            />
            {shownFirmwares.map((fw) => (
              <Line
                key={fw}
                type="linear"
                dataKey={`v:${fw}`}
                name={`fw ${fw}`}
                stroke={colorOf(fw)}
                strokeWidth={1.25}
                connectNulls
                hide={hidden.has(fw)}
                isAnimationActive={false}
                dot={(p: { cx?: number; cy?: number; payload?: Row; index?: number }) => (
                  <StatusMarker key={`${fw}-${p.index ?? 0}`} cx={p.payload?.fw === fw ? p.cx : undefined} cy={p.cy} status={p.payload?.status ?? 'PASS'} color={colorOf(fw)} theme={theme} r={3} />
                )}
                activeDot={{ r: 5, stroke: theme.surface, fill: colorOf(fw) }}
              />
            ))}
          </ComposedChart>
        )}
      </ChartCanvas>
    </ChartPanel>
  );
});
