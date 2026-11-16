import { useEffect, useMemo, useRef, useState } from 'react';
import { Ban, Check, CircleDashed, Info, Loader2, OctagonAlert, TriangleAlert, X } from 'lucide-react';
import type { LogEntry, RunDetail, RunStep } from '@/api/types';
import { cn, EmptyState, ProgressBar, Switch } from '@/components/ui';
import { useNow } from '@/hooks/useNow';
import { formatDurationMs, formatTimeMs, plural } from '@/lib/format';
import { isRunActive } from '@/lib/status';

/* ------------------------------------------------------------------ Banner */

export function RunBanner({ run }: { run: RunDetail }) {
  const active = isRunActive(run.status);
  const now = useNow(500);
  const started = run.started_at ? new Date(run.started_at).getTime() : null;
  const elapsed = run.duration_ms ?? (started && active ? Math.max(0, now - started) : null);
  const fails = run.counts.FAIL;
  const errors = run.counts.ERROR;
  const total = run.counts.PASS + fails + errors + run.counts.CANCELLED;

  type Tone = 'info' | 'success' | 'warn' | 'danger' | 'neutral';
  let tone: Tone = 'neutral';
  let Icon = Info;
  let headline = '';
  let detail: string | null = null;

  switch (run.status) {
    case 'PENDING':
    case 'RUNNING':
      tone = 'info';
      Icon = Loader2;
      headline = run.cancel_requested ? 'Cancelling…' : `Running${run.current_step ? ` — ${run.steps.find((st) => st.id === run.current_step)?.name ?? run.current_step}` : ''}`;
      detail = run.cancel_requested ? 'Cleanup runs first: generator output off, instruments released.' : null;
      break;
    case 'PASS':
      tone = 'success';
      Icon = Check;
      headline = 'Run PASSED';
      detail = `All ${plural(total, 'measurement')} within limits.`;
      break;
    case 'FAIL':
      tone = 'warn';
      Icon = X;
      headline = 'Run FAILED — out of tolerance';
      detail = `${plural(fails, 'measurement')} outside the limits. The instruments worked correctly; the DUT did not meet the specification.`;
      break;
    case 'ERROR':
      tone = 'danger';
      Icon = OctagonAlert;
      headline = 'Run ERROR — communication or software problem';
      detail = `This is not a tolerance failure. ${run.error ? `${run.error.code}: ${run.error.message}` : `${plural(errors, 'measurement')} could not be completed.`}`;
      break;
    case 'CANCELLED':
      tone = 'neutral';
      Icon = Ban;
      headline = 'Run CANCELLED';
      detail = 'Stopped on request. Cleanup completed; results so far are kept.';
      break;
  }

  const styles: Record<Tone, string> = {
    info: 'border-info/40 bg-info-soft text-info-text',
    success: 'border-success/40 bg-success-soft text-success-text',
    warn: 'border-warn/50 bg-warn-soft text-warn-text',
    danger: 'border-danger/40 bg-danger-soft text-danger-text',
    neutral: 'border-border-strong bg-neutral-soft text-neutral-text',
  };
  const barTone = run.status === 'FAIL' ? 'warn' : run.status === 'ERROR' ? 'danger' : run.status === 'PASS' ? 'success' : run.status === 'CANCELLED' ? 'neutral' : 'info';

  return (
    <div role="status" aria-live="polite" data-run-status={run.status} className={cn('rounded-md border px-4 py-3', styles[tone])}>
      <div className="flex items-start gap-3">
        <Icon aria-hidden className={cn('mt-0.5 h-4 w-4 shrink-0', run.status === 'RUNNING' && 'animate-spin')} strokeWidth={2.25} />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold">{headline}</p>
          {detail && <p className="mt-0.5 text-xs text-ink-2">{detail}</p>}
        </div>
        <dl className="mono flex shrink-0 gap-4 text-xs text-ink-2">
          <Stat k="PASS" v={run.counts.PASS} />
          <Stat k="FAIL" v={fails} hot={fails > 0 ? 'warn' : undefined} />
          <Stat k="ERROR" v={errors} hot={errors > 0 ? 'danger' : undefined} />
          <div>
            <dt className="text-[10px] uppercase tracking-wide text-ink-3">Elapsed</dt>
            <dd className="text-ink">{formatDurationMs(elapsed)}</dd>
          </div>
        </dl>
      </div>
      <div className="mt-3 flex items-center gap-3">
        <ProgressBar value={run.progress} tone={barTone} label="Run progress" />
        <span className="mono w-10 shrink-0 text-right text-xs text-ink-2">{Math.round(run.progress * 100)}%</span>
      </div>
    </div>
  );
}

function Stat({ k, v, hot }: { k: string; v: number; hot?: 'warn' | 'danger' }) {
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-wide text-ink-3">{k}</dt>
      <dd className={cn(hot === 'warn' && 'font-semibold text-warn-text', hot === 'danger' && 'font-semibold text-danger-text', !hot && 'text-ink')}>{v}</dd>
    </div>
  );
}

/* ------------------------------------------------------------------ Steps */

function StepIcon({ status }: { status: string }) {
  const cls = 'h-4 w-4 shrink-0';
  switch (status) {
    case 'PASS':
      return <Check aria-label="passed" className={cn(cls, 'text-success')} strokeWidth={2.5} />;
    case 'FAIL':
      return <X aria-label="failed" className={cn(cls, 'text-warn')} strokeWidth={2.5} />;
    case 'ERROR':
      return <TriangleAlert aria-label="error" className={cn(cls, 'text-danger')} />;
    case 'CANCELLED':
      return <Ban aria-label="cancelled" className={cn(cls, 'text-neutral')} />;
    case 'RUNNING':
      return <Loader2 aria-label="running" className={cn(cls, 'animate-spin text-info')} />;
    default:
      return <CircleDashed aria-label="pending" className={cn(cls, 'text-ink-3')} />;
  }
}

export function StepList({ steps, currentStep }: { steps: ReadonlyArray<RunStep>; currentStep: string | null }) {
  if (steps.length === 0) return <EmptyState compact icon={CircleDashed} title="No steps reported yet" />;
  return (
    <ol aria-label="Run steps" className="divide-y divide-border">
      {steps.map((s, i) => {
        const current = s.status === 'RUNNING' || (currentStep !== null && (currentStep === s.id || currentStep === s.name) && s.status !== 'PASS');
        return (
          <li key={s.id} className={cn('flex items-start gap-2.5 px-4 py-2', current && 'bg-info-soft/50')} aria-current={current ? 'step' : undefined}>
            <span className="mono mt-0.5 w-4 shrink-0 text-right text-[11px] text-ink-3">{i + 1}</span>
            <StepIcon status={s.status} />
            <div className="min-w-0 flex-1">
              <p className={cn('truncate text-[13px]', s.status === 'PENDING' ? 'text-ink-3' : 'text-ink')}>{s.name}</p>
              {s.message && (s.status === 'ERROR' || s.status === 'FAIL' || s.status === 'CANCELLED') && <p className={cn('text-xs', s.status === 'ERROR' ? 'text-danger-text' : 'text-ink-2')}>{s.message}</p>}
            </div>
            <span className="mono shrink-0 text-[11px] text-ink-3">{s.duration_ms !== null ? formatDurationMs(s.duration_ms) : ''}</span>
          </li>
        );
      })}
    </ol>
  );
}

/* ------------------------------------------------------------------ Log tail */

const LEVEL_CLS: Record<string, string> = {
  debug: 'text-ink-3',
  info: 'text-info-text',
  warn: 'text-warn-text',
  error: 'text-danger-text',
};

export function RunLog({ entries: all, live }: { entries: ReadonlyArray<LogEntry>; live: boolean }) {
  const [autoscroll, setAutoscroll] = useState(true);
  const [showScpi, setShowScpi] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const entries = useMemo(() => (showScpi ? all : all.filter((e) => e.source !== 'scpi')), [all, showScpi]);
  const hidden = all.length - entries.length;
  useEffect(() => {
    const el = ref.current;
    if (autoscroll && el) el.scrollTop = el.scrollHeight;
  }, [entries, autoscroll]);

  return (
    <div>
      <div className="flex items-center justify-between gap-4 border-b border-border px-4 py-1.5">
        <span className="text-xs text-ink-3">
          {live ? 'Following the run' : `${entries.length} entries`}
          {hidden > 0 && ` \u00b7 ${hidden} SCPI lines hidden`}
        </span>
        <div className="flex items-center gap-4">
          <label className="flex items-center gap-2 text-xs text-ink-2">
            <Switch label="Show SCPI traffic" checked={showScpi} onChange={setShowScpi} />
            SCPI traffic
          </label>
          <label className="flex items-center gap-2 text-xs text-ink-2">
            <Switch label="Autoscroll log" checked={autoscroll} onChange={setAutoscroll} />
            Autoscroll
          </label>
        </div>
      </div>
      <div
        ref={ref}
        role="log"
        aria-label="Test log"
        aria-live="off"
        tabIndex={0}
        onScroll={() => {
          const el = ref.current;
          if (el && el.scrollHeight - el.scrollTop - el.clientHeight > 40 && autoscroll) setAutoscroll(false);
        }}
        className="mono max-h-[240px] min-h-[120px] overflow-auto bg-sunken text-[12px] leading-[1.6]"
      >
        {entries.length === 0 ? (
          <p className="px-4 py-4 font-sans text-xs text-ink-3">No log entries for this run yet.</p>
        ) : (
          <ul>
            {entries.map((e) => (
              <li key={e.seq} className={cn('flex items-baseline gap-2 px-4 py-px hover:bg-hover', e.level === 'error' && 'bg-danger-soft/60', e.level === 'warn' && 'bg-warn-soft/60')}>
                <span className="shrink-0 text-ink-3">{formatTimeMs(e.ts)}</span>
                <span className={cn('w-10 shrink-0 text-[11px] font-semibold uppercase', LEVEL_CLS[e.level])}>{e.level}</span>
                <span className="w-14 shrink-0 truncate text-ink-3">{e.source}</span>
                <span className={cn('min-w-0 flex-1 break-words', e.level === 'error' ? 'text-danger-text' : e.level === 'warn' ? 'text-warn-text' : 'text-ink')}>{e.message}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
