import { memo, useMemo, useState } from 'react';
import { Bar, BarChart, CartesianGrid, Cell, ErrorBar, LabelList, Tooltip, XAxis, YAxis } from 'recharts';
import { ChartColumn } from 'lucide-react';
import type { FirmwareStats, KindStats } from '@/api/types';
import { ERROR_CODE_HELP } from '@/lib/status';
import { formatKindValue, formatNumber, kindLabel } from '@/lib/format';
import { ChartCanvas } from './ChartCanvas';
import { ChartPanel } from './ChartPanel';
import { axisLabel, axisStyle, ChartTooltip, LegendToggles } from './chartKit';
import { useChartTheme } from './useChartTheme';

/* ------------------------------------------------------------------ pass rate per measurement */

interface PassRateBarsProps {
  byKind: Record<string, KindStats> | undefined;
  loading?: boolean;
  error?: unknown;
  onRetry?: () => void;
  height?: number;
}

/** Pass rate (%) per measurement kind, horizontal bars with value labels. */
export const PassRateBars = memo(function PassRateBars({ byKind, loading, error, onRetry, height = 260 }: PassRateBarsProps) {
  const theme = useChartTheme();
  const data = useMemo(
    () =>
      Object.entries(byKind ?? {})
        .map(([kind, s]) => {
          const total = s.pass + s.fail + s.error;
          return { kind, label: kindLabel(kind), rate: total > 0 ? (s.pass / total) * 100 : 0, pass: s.pass, fail: s.fail, error: s.error, total };
        })
        .filter((d) => d.total > 0)
        .sort((a, b) => a.rate - b.rate),
    [byKind],
  );
  const status = loading && data.length === 0 ? 'loading' : error && data.length === 0 ? 'error' : data.length === 0 ? 'empty' : 'ready';
  const ax = axisStyle(theme);
  return (
    <ChartPanel
      title="Pass rate by measurement"
      description="PASS / (PASS + FAIL + ERROR)"
      height={height}
      status={status}
      error={error}
      onRetry={onRetry}
      emptyIcon={ChartColumn}
      emptyTitle="No measurements yet"
      emptyDescription="Pass rates per measurement appear once runs have completed."
      summary={`Pass rate per measurement: ${data.map((d) => `${d.label} ${formatNumber(d.rate, 1)} percent`).join(', ')}.`}
    >
      <ChartCanvas height={height}>
        {({ width, height: h }) => (
          <BarChart width={width} height={h} data={data} layout="vertical" margin={{ top: 4, right: 48, bottom: 24, left: 8 }} accessibilityLayer>
            <CartesianGrid stroke={theme.grid} horizontal={false} />
            <XAxis type="number" domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tickFormatter={(v: number) => `${v}`} label={axisLabel(theme, 'Pass rate (%)')} {...ax} />
            <YAxis type="category" dataKey="label" width={92} {...ax} tick={{ ...ax.tick, fill: theme.text, fontFamily: 'Inter Variable, sans-serif', fontSize: 12 }} />
            <Tooltip
              isAnimationActive={false}
              cursor={{ fill: theme.grid, fillOpacity: 0.4 }}
              content={<ChartTooltip title={(l) => String(l)} row={(e) => (e.dataKey === 'rate' ? `${formatNumber(Number(e.value), 1)} %  (${String(e.payload?.['pass'])} pass, ${String(e.payload?.['fail'])} fail, ${String(e.payload?.['error'])} error)` : null)} />}
            />
            <Bar dataKey="rate" name="Pass rate" radius={[0, 3, 3, 0]} barSize={16} isAnimationActive={false}>
              {data.map((d) => (
                <Cell key={d.kind} fill={d.rate >= 99.95 ? theme.success : d.rate >= 80 ? theme.series[0] : theme.warn} />
              ))}
              <LabelList dataKey="rate" position="right" formatter={(v: unknown) => `${formatNumber(Number(v), 1)}%`} fill={theme.text} fontSize={11} fontFamily="JetBrains Mono, monospace" />
            </Bar>
          </BarChart>
        )}
      </ChartCanvas>
    </ChartPanel>
  );
});

/* ------------------------------------------------------------------ firmware comparison */

interface FirmwareChartsProps {
  firmwares: ReadonlyArray<FirmwareStats>;
  loading?: boolean;
  error?: unknown;
  onRetry?: () => void;
  height?: number;
}

const OUTCOME_KEYS = [
  { key: 'pass', label: 'PASS', shape: 'square' as const },
  { key: 'fail', label: 'FAIL', shape: 'diamond' as const },
  { key: 'error', label: 'ERROR', shape: 'square' as const },
];

/** Grouped bars of PASS / FAIL / ERROR counts per firmware version. */
export const FirmwareOutcomeChart = memo(function FirmwareOutcomeChart({ firmwares, loading, error, onRetry, height = 280 }: FirmwareChartsProps) {
  const theme = useChartTheme();
  const [hidden, setHidden] = useState<ReadonlySet<string>>(new Set());
  const color = { pass: theme.success, fail: theme.warn, error: theme.danger } as const;
  const data = useMemo(() => firmwares.map((f) => ({ fw: `fw ${f.firmware}`, pass: f.pass, fail: f.fail, error: f.error, rate: f.pass_rate })), [firmwares]);
  const status = loading && data.length === 0 ? 'loading' : error && data.length === 0 ? 'error' : data.length === 0 ? 'empty' : 'ready';
  const ax = axisStyle(theme);
  return (
    <ChartPanel
      title="Outcomes by firmware"
      description="measurement counts"
      height={height}
      status={status}
      error={error}
      onRetry={onRetry}
      emptyIcon={ChartColumn}
      emptyTitle="No firmware data yet"
      emptyDescription="Run the same sequence against different DUT firmware versions to compare them here."
      summary={`Outcomes per firmware: ${data.map((d) => `${d.fw} ${d.pass} pass, ${d.fail} fail, ${d.error} error`).join('; ')}.`}
      footer={
        <LegendToggles
          label="Outcomes"
          items={OUTCOME_KEYS.map((o) => ({ key: o.key, label: o.label, color: color[o.key as keyof typeof color], shape: o.shape, hidden: hidden.has(o.key) }))}
          onToggle={(k) => setHidden((h) => (h.has(k) ? new Set([...h].filter((x) => x !== k)) : new Set([...h, k])))}
        />
      }
    >
      <ChartCanvas height={height}>
        {({ width, height: h }) => (
          <BarChart width={width} height={h} data={data} margin={{ top: 12, right: 16, bottom: 6, left: 4 }} barGap={3} accessibilityLayer>
            <CartesianGrid stroke={theme.grid} vertical={false} />
            <XAxis dataKey="fw" {...ax} tick={{ ...ax.tick, fill: theme.text }} />
            <YAxis allowDecimals={false} width={44} label={axisLabel(theme, 'Measurements', 'insideLeft')} {...ax} />
            <Tooltip isAnimationActive={false} cursor={{ fill: theme.grid, fillOpacity: 0.4 }} content={<ChartTooltip title={(l) => String(l)} row={(e) => `${String(e.name)}: ${String(e.value)}`} />} />
            {OUTCOME_KEYS.map((o) => (
              <Bar key={o.key} dataKey={o.key} name={o.label} fill={color[o.key as keyof typeof color]} hide={hidden.has(o.key)} radius={[3, 3, 0, 0]} maxBarSize={36} isAnimationActive={false}>
                <LabelList dataKey={o.key} position="top" fill={theme.axis} fontSize={10} fontFamily="JetBrains Mono, monospace" />
              </Bar>
            ))}
          </BarChart>
        )}
      </ChartCanvas>
    </ChartPanel>
  );
});

/** Mean (with +/- one standard deviation) of one measurement kind per firmware. */
export const FirmwareMeanChart = memo(function FirmwareMeanChart({ firmwares, kind, loading, error, onRetry, height = 280 }: FirmwareChartsProps & { kind: string }) {
  const theme = useChartTheme();
  const data = useMemo(
    () =>
      firmwares
        .map((f, i) => {
          const s = f.by_kind[kind];
          return s && s.mean !== null ? { fw: `fw ${f.firmware}`, mean: s.mean, err: s.std ?? 0, unit: s.unit, count: s.count, idx: i } : null;
        })
        .filter((d): d is NonNullable<typeof d> => d !== null),
    [firmwares, kind],
  );
  const unit = data[0]?.unit ?? '';
  const status = loading && data.length === 0 ? 'loading' : error && data.length === 0 ? 'error' : data.length === 0 ? 'empty' : 'ready';
  const ax = axisStyle(theme);
  return (
    <ChartPanel
      title={`${kindLabel(kind)} by firmware`}
      description={`mean ± 1 std dev${unit ? `, ${unit}` : ''}`}
      height={height}
      status={status}
      error={error}
      onRetry={onRetry}
      emptyIcon={ChartColumn}
      emptyTitle={`No ${kindLabel(kind)} data per firmware`}
      emptyDescription="Pick another measurement or run a sequence that measures this value."
      summary={`Mean ${kindLabel(kind)} per firmware: ${data.map((d) => `${d.fw} ${formatKindValue(kind, d.mean)} ${d.unit}`).join('; ')}.`}
    >
      <ChartCanvas height={height}>
        {({ width, height: h }) => (
          <BarChart width={width} height={h} data={data} margin={{ top: 12, right: 16, bottom: 6, left: 4 }} accessibilityLayer>
            <CartesianGrid stroke={theme.grid} vertical={false} />
            <XAxis dataKey="fw" {...ax} tick={{ ...ax.tick, fill: theme.text }} />
            <YAxis width={56} tickFormatter={(v: number) => formatKindValue(kind, v)} label={axisLabel(theme, unit, 'insideLeft')} {...ax} />
            <Tooltip isAnimationActive={false} cursor={{ fill: theme.grid, fillOpacity: 0.4 }} content={<ChartTooltip title={(l) => String(l)} row={(e) => `mean ${formatKindValue(kind, Number(e.value))} ${unit} ± ${formatKindValue(kind, Number(e.payload?.['err']))} (n=${String(e.payload?.['count'])})`} />} />
            <Bar dataKey="mean" name="Mean" maxBarSize={48} radius={[3, 3, 0, 0]} isAnimationActive={false}>
              {data.map((d) => (
                <Cell key={d.fw} fill={theme.categories[d.idx % theme.categories.length]} />
              ))}
              <ErrorBar dataKey="err" width={6} stroke={theme.text} strokeWidth={1.25} />
            </Bar>
          </BarChart>
        )}
      </ChartCanvas>
    </ChartPanel>
  );
});

/* ------------------------------------------------------------------ failure reasons */

export const FailureReasonsChart = memo(function FailureReasonsChart({
  reasons,
  loading,
  error,
  onRetry,
  height = 280,
}: {
  reasons: ReadonlyArray<{ reason: string; count: number }> | undefined;
  loading?: boolean;
  error?: unknown;
  onRetry?: () => void;
  height?: number;
}) {
  const theme = useChartTheme();
  const data = useMemo(() => [...(reasons ?? [])].sort((a, b) => b.count - a.count).map((r) => ({ ...r, tolerance: r.reason.startsWith('OUT_OF_TOLERANCE') })), [reasons]);
  const status = loading && data.length === 0 ? 'loading' : error && data.length === 0 ? 'error' : data.length === 0 ? 'empty' : 'ready';
  const ax = axisStyle(theme);
  return (
    <ChartPanel
      title="Failure reasons"
      description="amber = out of tolerance (FAIL), red = communication / software (ERROR)"
      height={height}
      status={status}
      error={error}
      onRetry={onRetry}
      emptyIcon={ChartColumn}
      emptyTitle="No failures recorded"
      emptyDescription="Good news, or no runs yet. Failed and errored measurements are grouped by reason here."
      summary={`Failure reasons: ${data.map((d) => `${d.reason} ${d.count}`).join(', ')}.`}
    >
      <ChartCanvas height={height}>
        {({ width, height: h }) => (
          <BarChart width={width} height={h} data={data} layout="vertical" margin={{ top: 4, right: 40, bottom: 24, left: 8 }} accessibilityLayer>
            <CartesianGrid stroke={theme.grid} horizontal={false} />
            <XAxis type="number" allowDecimals={false} label={axisLabel(theme, 'Measurements')} {...ax} />
            <YAxis type="category" dataKey="reason" width={176} {...ax} tick={{ ...ax.tick, fill: theme.text, fontSize: 10.5 }} />
            <Tooltip isAnimationActive={false} cursor={{ fill: theme.grid, fillOpacity: 0.4 }} content={<ChartTooltip title={(l) => String(l)} row={(e) => `${String(e.value)} · ${ERROR_CODE_HELP[String(e.payload?.['reason'])] ?? ''}`} />} />
            <Bar dataKey="count" name="Count" barSize={16} radius={[0, 3, 3, 0]} isAnimationActive={false}>
              {data.map((d) => (
                <Cell key={d.reason} fill={d.tolerance ? theme.warn : theme.danger} />
              ))}
              <LabelList dataKey="count" position="right" fill={theme.text} fontSize={11} fontFamily="JetBrains Mono, monospace" />
            </Bar>
          </BarChart>
        )}
      </ChartCanvas>
    </ChartPanel>
  );
});
