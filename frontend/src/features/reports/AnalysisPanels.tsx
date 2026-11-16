import { useMemo, useState } from 'react';
import { api } from '@/api';
import type { ReportSummary } from '@/api/types';
import { FailureReasonsChart, FirmwareMeanChart, FirmwareOutcomeChart, PassRateBars } from '@/components/charts/BarCharts';
import { TrendChart } from '@/components/charts/TrendChart';
import { EmptyState, Panel, SelectField, Table, TableContainer, Td, Th, Tr } from '@/components/ui';
import { usePolling } from '@/hooks/usePolling';
import { formatKindValue, formatPercent, kindLabel } from '@/lib/format';
import { RefreshCw } from 'lucide-react';

interface PanelProps {
  summary: ReportSummary | undefined;
  loading: boolean;
  error: Error | null;
  onRetry: () => void;
}

const KIND_ORDER = ['gain', 'thd', 'snr', 'noise_floor', 'rms', 'freq_sweep'];
function orderKinds(kinds: string[]): string[] {
  const rank = (k: string) => (KIND_ORDER.includes(k) ? KIND_ORDER.indexOf(k) : KIND_ORDER.length);
  return [...kinds].sort((a, b) => rank(a) - rank(b));
}

/* ------------------------------------------------------------------ trends */

export function TrendPanel({ summary, loading, error, onRetry }: PanelProps) {
  const kinds = useMemo(() => orderKinds(Array.from(new Set((summary?.trend ?? []).map((p) => p.kind)))), [summary]);
  const [picked, setPicked] = useState<string>('');
  const kind = kinds.includes(picked) ? picked : (kinds[0] ?? '');
  const points = useMemo(() => (summary?.trend ?? []).filter((p) => p.kind === kind), [summary, kind]);
  const unit = points[0]?.unit ?? summary?.by_kind[kind]?.unit ?? '';
  const firmwares = useMemo(() => Array.from(new Set((summary?.trend ?? []).map((p) => p.firmware))).sort((a, b) => a.localeCompare(b, undefined, { numeric: true })), [summary]);

  // Limits band: taken from the newest measurement of this kind (limits are per task, not part of the summary).
  const limitsPoll = usePolling((signal) => api.testResults({ kind, limit: 1 }, { signal }), { enabled: kind !== '', intervalMs: 20000, resetKey: kind });
  const limits = limitsPoll.data?.results[0]?.limits ?? null;

  const stats = summary?.by_kind[kind];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <SelectField label="Measurement" value={kind} onChange={setPicked} options={kinds.map((k) => ({ value: k, label: kindLabel(k) }))} wrapperClassName="w-52" disabled={kinds.length === 0} />
        {stats && (
          <dl className="mono flex gap-6 text-xs">
            {(
              [
                ['n', String(stats.count)],
                ['mean', formatKindValue(kind, stats.mean)],
                ['std', formatKindValue(kind, stats.std)],
                ['min', formatKindValue(kind, stats.min)],
                ['max', formatKindValue(kind, stats.max)],
              ] as const
            ).map(([k, v]) => (
              <div key={k}>
                <dt className="text-[10px] uppercase tracking-wide text-ink-3">{k}</dt>
                <dd className="text-ink">{v}</dd>
              </div>
            ))}
          </dl>
        )}
      </div>
      <TrendChart kind={kind} kindLabel={kindLabel(kind)} points={points} unit={unit} limits={limits ? { min: limits.min, max: limits.max } : null} firmwares={firmwares} loading={loading} error={error} onRetry={onRetry} />
      <PassRateBars byKind={summary?.by_kind} loading={loading} error={error} onRetry={onRetry} />
    </div>
  );
}

/* ------------------------------------------------------------------ firmware comparison */

export function FirmwarePanel({ summary, loading, error, onRetry }: PanelProps) {
  const firmwares = useMemo(() => [...(summary?.by_firmware ?? [])].sort((a, b) => a.firmware.localeCompare(b.firmware, undefined, { numeric: true })), [summary]);
  const kinds = useMemo(() => orderKinds(Array.from(new Set(firmwares.flatMap((f) => Object.keys(f.by_kind))))), [firmwares]);
  const [picked, setPicked] = useState('');
  const kind = kinds.includes(picked) ? picked : (kinds[0] ?? '');

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <FirmwareOutcomeChart firmwares={firmwares} loading={loading} error={error} onRetry={onRetry} />
        <div className="space-y-3">
          <SelectField label="Compare measurement" value={kind} onChange={setPicked} options={kinds.map((k) => ({ value: k, label: kindLabel(k) }))} wrapperClassName="w-52" disabled={kinds.length === 0} />
          <FirmwareMeanChart firmwares={firmwares} kind={kind} loading={loading} error={error} onRetry={onRetry} height={236} />
        </div>
      </div>
      <Panel title="Firmware comparison" description={kind ? kindLabel(kind) : undefined} flush>
        {firmwares.length === 0 ? (
          <EmptyState compact title="No firmware statistics yet" description="Statistics per firmware version appear once runs with different DUT firmware have completed." />
        ) : (
          <TableContainer label="Firmware comparison table">
            <Table>
              <thead>
                <tr>
                  <Th>Firmware</Th>
                  <Th numeric>Measurements</Th>
                  <Th numeric>Pass</Th>
                  <Th numeric>Fail</Th>
                  <Th numeric>Error</Th>
                  <Th numeric>Pass rate</Th>
                  <Th numeric>{kind ? `${kindLabel(kind)} mean` : 'Mean'}</Th>
                  <Th numeric>Std dev</Th>
                  <Th numeric>Min</Th>
                  <Th numeric>Max</Th>
                </tr>
              </thead>
              <tbody>
                {firmwares.map((f) => {
                  const s = f.by_kind[kind];
                  return (
                    <Tr key={f.firmware}>
                      <Td mono className="font-medium">{f.firmware}</Td>
                      <Td numeric>{f.tasks}</Td>
                      <Td numeric>{f.pass}</Td>
                      <Td numeric className={f.fail ? 'text-warn-text' : 'text-ink-3'}>{f.fail}</Td>
                      <Td numeric className={f.error ? 'text-danger-text' : 'text-ink-3'}>{f.error}</Td>
                      <Td numeric>{formatPercent(f.pass_rate, 1)}</Td>
                      <Td numeric>{s ? `${formatKindValue(kind, s.mean)} ${s.unit}` : '—'}</Td>
                      <Td numeric className="text-ink-2">{s ? formatKindValue(kind, s.std) : '—'}</Td>
                      <Td numeric className="text-ink-2">{s ? formatKindValue(kind, s.min) : '—'}</Td>
                      <Td numeric className="text-ink-2">{s ? formatKindValue(kind, s.max) : '—'}</Td>
                    </Tr>
                  );
                })}
              </tbody>
            </Table>
          </TableContainer>
        )}
      </Panel>
    </div>
  );
}

/* ------------------------------------------------------------------ failures and recovery */

export function ReliabilityPanel({ summary, loading, error, onRetry }: PanelProps) {
  const r = summary?.recovery;
  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-5">
      <div className="xl:col-span-3">
        <FailureReasonsChart reasons={summary?.failure_reasons} loading={loading} error={error} onRetry={onRetry} />
      </div>
      <div className="xl:col-span-2">
        <Panel title="Recovery analysis" description="automatic retry after reconnect" className="h-full">
          {!r && <EmptyState compact icon={RefreshCw} title={loading ? 'Loading…' : 'No recovery data'} description={error ? error.message : undefined} />}
          {r && r.tasks_with_retry === 0 && (
            <EmptyState compact icon={RefreshCw} title="No retries were needed" description="When a measurement hits a communication error the engine reconnects and retries it. Those cases are analysed here." />
          )}
          {r && r.tasks_with_retry > 0 && (
            <div className="space-y-4">
              <div className="flex items-baseline gap-2">
                <span className="mono text-3xl font-medium leading-none text-ink">{r.recovery_rate === null ? '—' : formatPercent(r.recovery_rate, 0)}</span>
                <span className="text-xs text-ink-3">of retried measurements recovered</span>
              </div>
              <dl className="grid grid-cols-3 gap-3 text-xs">
                <Kpi k="Retried" v={r.tasks_with_retry} />
                <Kpi k="Recovered" v={r.recovered} tone="success" />
                <Kpi k="Unrecovered" v={r.unrecovered} tone={r.unrecovered ? 'danger' : undefined} />
              </dl>
              <p className="text-xs leading-5 text-ink-2">A measurement counts as recovered when a later attempt (after automatic reconnect) produced a valid result. FAIL results are never retried.</p>
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}

function Kpi({ k, v, tone }: { k: string; v: number; tone?: 'success' | 'danger' }) {
  return (
    <div className="rounded-md border border-border bg-sunken px-3 py-2">
      <dt className="eyebrow">{k}</dt>
      <dd className={`mono mt-0.5 text-lg ${tone === 'success' ? 'text-success-text' : tone === 'danger' ? 'text-danger-text' : 'text-ink'}`}>{v}</dd>
    </div>
  );
}
