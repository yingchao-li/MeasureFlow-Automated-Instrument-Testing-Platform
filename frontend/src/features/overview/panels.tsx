import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ChevronDown, CircleAlert, CircleCheck, CircleX, FlaskConical, Info, TriangleAlert } from 'lucide-react';
import type { Health, Instrument, LogEntry, ReportSummary, RunSummary } from '@/api/types';
import { CalibrationChip, InstrumentStateBadge, KIND_LABEL as INSTRUMENT_KIND } from '@/components/InstrumentBits';
import { Badge, cn, EmptyState, ErrorState, Panel, SkeletonRows, StatusBadge, StatusDot, Table, TableContainer, Td, Th, Tr } from '@/components/ui';
import { HEALTH_STATUS } from '@/lib/status';
import { formatDurationMs, formatKindValue, formatNumber, formatPercent, formatTime, formatTimeMs, formatUptime, kindLabel, relativeTime } from '@/lib/format';
import { Skeleton } from '@/components/ui';

/* ------------------------------------------------------------------ System status */

export function SystemStatusPanel({ health, error, loading, offline, onRetry }: { health: Health | undefined; error: Error | null; loading: boolean; offline: boolean; onRetry: () => void }) {
  return (
    <Panel title="System" className="h-full">
      {!health && loading && <SkeletonRows rows={5} />}
      {!health && !loading && error && <ErrorState error={error} onRetry={onRetry} compact />}
      {health && (
        <div className={cn('space-y-3', offline && 'opacity-50')}>
          <div role="status" aria-live="polite" className="flex items-center gap-2">
            <StatusDot tone={HEALTH_STATUS[health.status].tone} pulse={health.status === 'ok' && !offline} />
            <span className="text-base font-semibold text-ink">{HEALTH_STATUS[health.status].label}</span>
          </div>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-xs">
            <Row k="Uptime" v={formatUptime(health.uptime_s)} />
            <Row k="Backend" v={health.software.backend} />
            <Row k="Simulator" v={health.software.simulator} />
            <Row k="Config" v={health.software.config_version} />
            <Row k="Active test" v={health.running_test ?? 'idle'} />
          </dl>
          {health.checks.length > 0 && <ChecksList checks={health.checks} />}
        </div>
      )}
    </Panel>
  );
}

function ChecksList({ checks }: { checks: Health['checks'] }) {
  const [open, setOpen] = useState(false);
  const bad = checks.filter((c) => c.status !== 'ok');
  const shown = open ? checks : bad;
  return (
    <div className="border-t border-border pt-2.5">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between rounded-sm text-xs text-ink-2 hover:text-ink"
      >
        <span className="flex items-center gap-1.5">
          {bad.length === 0 ? <CircleCheck aria-hidden className="h-3.5 w-3.5 text-success" /> : <TriangleAlert aria-hidden className="h-3.5 w-3.5 text-warn" />}
          {bad.length === 0 ? `All ${checks.length} health checks passing` : `${bad.length} of ${checks.length} health checks need attention`}
        </span>
        <ChevronDown aria-hidden className={cn('h-3.5 w-3.5 text-ink-3 transition-transform', open && 'rotate-180')} />
      </button>
      {shown.length > 0 && (
        <ul className="mt-2 space-y-1" aria-label="Health checks">
          {shown.map((c) => (
            <li key={c.name} className="flex items-start gap-2 text-xs" title={c.detail}>
              {c.status === 'ok' ? (
                <CircleCheck aria-label="ok" className="mt-px h-3.5 w-3.5 shrink-0 text-success" />
              ) : c.status === 'warn' ? (
                <TriangleAlert aria-label="warning" className="mt-px h-3.5 w-3.5 shrink-0 text-warn" />
              ) : (
                <CircleX aria-label="failed" className="mt-px h-3.5 w-3.5 shrink-0 text-danger" />
              )}
              <span className="min-w-0">
                <span className="mono text-ink-2">{c.name}</span>
                {c.status !== 'ok' && <span className="block text-ink-3">{c.detail}</span>}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <>
      <dt className="text-ink-3">{k}</dt>
      <dd className="mono truncate text-right text-ink">{v}</dd>
    </>
  );
}

/* ------------------------------------------------------------------ Instrument tiles */

export function InstrumentTiles({ instruments, loading, error, onRetry, dimmed }: { instruments: Instrument[]; loading: boolean; error: Error | null; onRetry: () => void; dimmed: boolean }) {
  if (loading && instruments.length === 0) {
    return (
      <>
        {[0, 1, 2].map((i) => (
          <div key={i} className="rounded-lg border border-border bg-surface p-4">
            <Skeleton className="mb-3 h-3 w-24" />
            <Skeleton className="mb-2 h-4 w-40" />
            <Skeleton className="h-3 w-32" />
          </div>
        ))}
      </>
    );
  }
  if (error && instruments.length === 0) {
    return (
      <div className="col-span-3 rounded-lg border border-border bg-surface">
        <ErrorState error={error} onRetry={onRetry} compact />
      </div>
    );
  }
  return (
    <>
      {instruments.map((i) => (
        <Link
          key={i.id}
          to={`/instruments?id=${encodeURIComponent(i.id)}`}
          aria-label={`${i.name}, ${i.state}. Open instrument details`}
          className={cn(
            'flex min-w-0 flex-col justify-between gap-3 rounded-lg border border-border bg-surface p-4 shadow-sm transition-colors hover:border-border-strong hover:bg-hover',
            dimmed && 'opacity-60',
          )}
        >
          <div className="flex items-center justify-between gap-2">
            <span className="eyebrow truncate">{INSTRUMENT_KIND[i.kind]}</span>
            <InstrumentStateBadge state={i.state} />
          </div>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-ink">{i.name}</p>
            <p className="mono mt-0.5 truncate text-[11px] text-ink-3">
              {i.host}:{i.port}
              {i.firmware ? ` · fw ${i.firmware}` : ''}
            </p>
            {i.idn && (
              <p className="mono mt-0.5 truncate text-[11px] text-ink-3" title={i.idn}>
                {i.idn}
              </p>
            )}
          </div>
          <div className="flex items-center justify-between gap-2">
            <span className="mono shrink-0 whitespace-nowrap text-[11px] text-ink-3">{i.state === 'connected' && i.latency_ms !== null ? `${formatNumber(i.latency_ms, 1)} ms` : i.last_error ? 'error' : '—'}</span>
            {i.calibration && i.calibration.status !== 'none' ? <CalibrationChip calibration={i.calibration} /> : <span className="text-[11px] text-ink-3">no calibration record</span>}
          </div>
          {i.leased_by && <p className="mono truncate text-[11px] text-info-text">in use by {i.leased_by}</p>}
          {i.state === 'error' && i.last_error && <p className="truncate text-[11px] text-danger-text">{i.last_error}</p>}
        </Link>
      ))}
    </>
  );
}

/* ------------------------------------------------------------------ Pass rate */

const OUTCOMES = [
  { key: 'PASS', label: 'Pass', cls: 'bg-success' },
  { key: 'FAIL', label: 'Fail', cls: 'bg-warn' },
  { key: 'ERROR', label: 'Error', cls: 'bg-danger' },
  { key: 'CANCELLED', label: 'Cancelled', cls: 'bg-neutral' },
] as const;

export function PassRatePanel({ summary, loading, error, onRetry, dimmed }: { summary: ReportSummary | undefined; loading: boolean; error: Error | null; onRetry: () => void; dimmed: boolean }) {
  return (
    <Panel title="Test pass rate" className="h-full">
      {!summary && loading && <SkeletonRows rows={4} />}
      {!summary && !loading && error && <ErrorState error={error} onRetry={onRetry} compact />}
      {summary && summary.tasks.total === 0 && (
        <EmptyState
          compact
          icon={FlaskConical}
          title="No measurements yet"
          description="Run a test sequence to see pass rates and statistics here."
          action={
            <Link to="/sequences" className="text-xs font-medium text-primary-text hover:underline">
              Open Test Sequences
            </Link>
          }
        />
      )}
      {summary && summary.tasks.total > 0 && (
        <div className={cn('space-y-3', dimmed && 'opacity-60')}>
          <div className="flex items-baseline gap-2">
            <span className="mono text-3xl font-medium leading-none text-ink">{summary.tasks.pass_rate === null ? '—' : formatPercent(summary.tasks.pass_rate, 1).replace(' ', ' ')}</span>
            <span className="text-xs text-ink-3">
              {summary.tasks.PASS} of {summary.tasks.total} measurements passed
            </span>
          </div>
          <div role="img" aria-label={OUTCOMES.map((o) => `${o.label} ${summary.tasks[o.key]}`).join(', ')} className="flex h-2 overflow-hidden rounded-full bg-border">
            {OUTCOMES.map((o) => {
              const n = summary.tasks[o.key];
              return n > 0 ? <div key={o.key} className={o.cls} style={{ width: `${(n / summary.tasks.total) * 100}%` }} /> : null;
            })}
          </div>
          <ul className="grid grid-cols-4 gap-2 text-xs">
            {OUTCOMES.map((o) => (
              <li key={o.key}>
                <span className="flex items-center gap-1.5 text-ink-3">
                  <span aria-hidden className={cn('h-2 w-2 rounded-sm', o.cls)} />
                  {o.label}
                </span>
                <span className="mono text-sm text-ink">{summary.tasks[o.key]}</span>
              </li>
            ))}
          </ul>
          <p className="border-t border-border pt-2.5 text-xs text-ink-3">
            <span className="mono text-ink-2">{summary.runs.total}</span> runs &middot; <span className="mono text-ink-2">{summary.runs.PASS}</span> pass &middot;{' '}
            <span className="mono text-ink-2">{summary.runs.FAIL}</span> fail &middot; <span className="mono text-ink-2">{summary.runs.ERROR}</span> error &middot;{' '}
            <span className="mono text-ink-2">{summary.runs.CANCELLED}</span> cancelled
          </p>
        </div>
      )}
    </Panel>
  );
}

/* ------------------------------------------------------------------ Recent runs */

export function RecentRunsPanel({ runs, loading, error, onRetry, dimmed }: { runs: RunSummary[] | undefined; loading: boolean; error: Error | null; onRetry: () => void; dimmed: boolean }) {
  const navigate = useNavigate();
  return (
    <Panel
      title="Recent test runs"
      className="h-full"
      flush
      actions={
        <Link to="/reports" className="text-xs font-medium text-primary-text hover:underline">
          All reports
        </Link>
      }
    >
      {!runs && loading && <div className="p-4"><SkeletonRows rows={5} /></div>}
      {!runs && !loading && error && <ErrorState error={error} onRetry={onRetry} compact />}
      {runs && runs.length === 0 && (
        <EmptyState
          compact
          icon={FlaskConical}
          title="No test runs yet"
          description="Start a sequence to see its result here."
          action={
            <Link to="/sequences" className="text-xs font-medium text-primary-text hover:underline">
              Open Test Sequences
            </Link>
          }
        />
      )}
      {runs && runs.length > 0 && (
        <TableContainer className={cn(dimmed && 'opacity-60')}>
          <Table>
            <thead>
              <tr>
                <Th>Run</Th>
                <Th>Status</Th>
                <Th>DUT</Th>
                <Th numeric>Results</Th>
                <Th numeric>Duration</Th>
                <Th numeric>Started</Th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <Tr key={r.run_id} interactive onClick={() => navigate(`/reports?run=${encodeURIComponent(r.run_id)}`)}>
                  <Td className="max-w-[220px]">
                    <Link to={`/reports?run=${encodeURIComponent(r.run_id)}`} className="block truncate font-medium text-ink hover:underline" onClick={(e) => e.stopPropagation()}>
                      {r.sequence_name}
                    </Link>
                    <span className="mono block truncate text-[11px] text-ink-3">{r.label ? `${r.label} · ` : ''}{r.run_id}</span>
                  </Td>
                  <Td>
                    <StatusBadge status={r.status} />
                  </Td>
                  <Td mono className="whitespace-nowrap text-xs text-ink-2">
                    {r.dut.profile} {r.dut.firmware}
                  </Td>
                  <Td numeric className="whitespace-nowrap text-xs">
                    <span className="text-success-text">{r.counts.PASS}</span>
                    <span className="text-ink-3"> / </span>
                    <span className={r.counts.FAIL ? 'text-warn-text' : 'text-ink-3'}>{r.counts.FAIL}</span>
                    <span className="text-ink-3"> / </span>
                    <span className={r.counts.ERROR ? 'text-danger-text' : 'text-ink-3'}>{r.counts.ERROR}</span>
                  </Td>
                  <Td numeric className="whitespace-nowrap text-xs text-ink-2">
                    {formatDurationMs(r.duration_ms)}
                  </Td>
                  <Td numeric className="whitespace-nowrap text-xs text-ink-2" title={r.created_at}>
                    {relativeTime(r.started_at ?? r.created_at)}
                  </Td>
                </Tr>
              ))}
            </tbody>
          </Table>
        </TableContainer>
      )}
    </Panel>
  );
}

/* ------------------------------------------------------------------ Event feed */

const LEVEL_ICON = {
  debug: { icon: Info, cls: 'text-ink-3', label: 'debug' },
  info: { icon: Info, cls: 'text-info', label: 'info' },
  warn: { icon: TriangleAlert, cls: 'text-warn', label: 'warning' },
  error: { icon: CircleAlert, cls: 'text-danger', label: 'error' },
} as const;

export function EventFeedPanel({ events, loading, error, onRetry, dimmed }: { events: LogEntry[] | undefined; loading: boolean; error: Error | null; onRetry: () => void; dimmed: boolean }) {
  return (
    <Panel title="System events" description="engine, system, environment" flush>
      {!events && loading && <div className="p-4"><SkeletonRows rows={5} /></div>}
      {!events && !loading && error && <ErrorState error={error} onRetry={onRetry} compact />}
      {events && events.length === 0 && <EmptyState compact icon={Info} title="No events yet" description="Engine, system and environment events appear here as they happen." />}
      {events && events.length > 0 && (
        <ul className={cn('max-h-[324px] divide-y divide-border overflow-y-auto', dimmed && 'opacity-60')} aria-label="Recent system events">
          {events.map((e) => {
            const L = LEVEL_ICON[e.level];
            return (
              <li key={e.seq} className="flex items-start gap-2.5 px-4 py-2">
                <L.icon aria-label={L.label} className={cn('mt-0.5 h-3.5 w-3.5 shrink-0', L.cls)} />
                <div className="min-w-0 flex-1">
                  <p className="text-[13px] leading-5 text-ink [overflow-wrap:anywhere]">{e.message}</p>
                  <p className="mono mt-0.5 text-[11px] text-ink-3" title={formatTimeMs(e.ts)}>
                    {formatTime(e.ts)} &middot; {e.source}
                  </p>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}

/* ------------------------------------------------------------------ Measurement statistics */

export function MeasurementStatsPanel({ summary, loading, error, onRetry, dimmed }: { summary: ReportSummary | undefined; loading: boolean; error: Error | null; onRetry: () => void; dimmed: boolean }) {
  const kinds = summary ? Object.entries(summary.by_kind) : [];
  return (
    <Panel title="Measurement statistics" description="all persisted runs" flush>
      {!summary && loading && <div className="p-4"><SkeletonRows rows={5} /></div>}
      {!summary && !loading && error && <ErrorState error={error} onRetry={onRetry} compact />}
      {summary && kinds.length === 0 && <EmptyState compact icon={FlaskConical} title="No statistics yet" description="Statistics per measurement kind appear after the first completed run." />}
      {summary && kinds.length > 0 && (
        <TableContainer className={cn(dimmed && 'opacity-60')}>
          <Table>
            <thead>
              <tr>
                <Th>Measurement</Th>
                <Th numeric>Count</Th>
                <Th numeric>Pass</Th>
                <Th numeric>Fail</Th>
                <Th numeric>Error</Th>
                <Th numeric>Mean</Th>
                <Th numeric>Std dev</Th>
                <Th numeric>Min</Th>
                <Th numeric>Max</Th>
              </tr>
            </thead>
            <tbody>
              {kinds.map(([kind, s]) => (
                <Tr key={kind}>
                  <Td className="whitespace-nowrap font-medium">
                    {kindLabel(kind)} <span className="mono text-[11px] font-normal text-ink-3">{s.unit}</span>
                  </Td>
                  <Td numeric>{s.count}</Td>
                  <Td numeric>{s.pass}</Td>
                  <Td numeric className={s.fail ? 'text-warn-text' : 'text-ink-3'}>{s.fail}</Td>
                  <Td numeric className={s.error ? 'text-danger-text' : 'text-ink-3'}>{s.error}</Td>
                  <Td numeric>{formatKindValue(kind, s.mean)}</Td>
                  <Td numeric className="text-ink-2">{formatKindValue(kind, s.std)}</Td>
                  <Td numeric className="text-ink-2">{formatKindValue(kind, s.min)}</Td>
                  <Td numeric className="text-ink-2">{formatKindValue(kind, s.max)}</Td>
                </Tr>
              ))}
            </tbody>
          </Table>
        </TableContainer>
      )}
    </Panel>
  );
}

export { Badge };
