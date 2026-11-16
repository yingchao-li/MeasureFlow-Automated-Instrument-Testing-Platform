import { SweepChart } from '@/components/charts/SweepChart';
import { Dialog, ErrorState, SkeletonRows } from '@/components/ui';
import { usePolling } from '@/hooks/usePolling';
import { api } from '@/api';
import { formatDateTime, formatDurationMs } from '@/lib/format';
import { isRunActive } from '@/lib/status';
import { ResultsTable } from '@/features/sequences/ResultsTable';
import { RunBanner, RunLog, StepList } from '@/features/sequences/RunParts';
import { DownloadLinks } from './DownloadLinks';

interface RunDrawerProps {
  runId: string | null;
  onClose: () => void;
}

/** Detail drawer for one run: banner, downloads, parameters, steps, results (+ sweep chart), log. */
export function RunDrawer({ runId, onClose }: RunDrawerProps) {
  const { data, error, isLoading, refresh } = usePolling((signal) => api.testStatus({ run_id: runId ?? undefined, log_tail: 200 }, { signal }), {
    enabled: runId !== null,
    resetKey: runId ?? '',
    intervalMs: (d) => (isRunActive(d?.run?.status) ? 1000 : 30000),
  });
  const run = data?.run ?? null;

  return (
    <Dialog open={runId !== null} onClose={onClose} variant="drawer" widthClass="w-[760px] max-w-[94vw]" title={run?.sequence_name ?? 'Run details'} description={<span className="mono">{runId}</span>}>
      <div className="space-y-5 p-5">
        {runId && <DownloadLinks runId={runId} variant="buttons" />}
        {isLoading && !run && <SkeletonRows rows={8} />}
        {!run && !isLoading && error && <ErrorState error={error} onRetry={() => void refresh()} compact />}
        {!run && !isLoading && !error && <ErrorState error={new Error('This run is no longer available.')} title="Run not found" compact />}
        {run && (
          <>
            <RunBanner run={run} />
            <dl className="grid grid-cols-2 gap-x-6 gap-y-3 text-xs sm:grid-cols-4">
              <Meta k="Created" v={formatDateTime(run.created_at)} />
              <Meta k="Duration" v={formatDurationMs(run.duration_ms)} />
              <Meta k="DUT profile" v={run.dut.profile} />
              <Meta k="DUT firmware" v={run.dut.firmware} />
              <Meta k="Retries" v={String(run.retries)} />
              <Meta k="Label" v={run.label ?? '—'} />
              <Meta k="Sequence" v={run.sequence_id} />
              <Meta k="Run id" v={run.run_id} />
            </dl>
            {Object.keys(run.parameters ?? {}).length > 0 && (
              <section aria-label="Parameters">
                <h3 className="eyebrow mb-1.5">Parameters</h3>
                <dl className="mono grid grid-cols-2 gap-x-6 gap-y-1 rounded-md border border-border bg-sunken px-3 py-2 text-[12px] sm:grid-cols-3">
                  {Object.entries(run.parameters).map(([k, v]) => (
                    <div key={k} className="flex justify-between gap-2">
                      <dt className="truncate text-ink-3">{k}</dt>
                      <dd className="text-ink">{v}</dd>
                    </div>
                  ))}
                </dl>
              </section>
            )}
            <section aria-label="Results">
              <h3 className="eyebrow mb-1.5">Results</h3>
              <div className="overflow-hidden rounded-md border border-border">
                <ResultsTable tasks={run.tasks} live={isRunActive(run.status)} maxHeight={320} />
              </div>
            </section>
            {run.tasks.some((t) => t.kind === 'freq_sweep') && <SweepChart tasks={run.tasks} />}
            <section aria-label="Steps">
              <h3 className="eyebrow mb-1.5">Steps</h3>
              <div className="overflow-hidden rounded-md border border-border">
                <StepList steps={run.steps} currentStep={run.current_step} />
              </div>
            </section>
            <section aria-label="Log">
              <h3 className="eyebrow mb-1.5">Log</h3>
              <div className="overflow-hidden rounded-md border border-border">
                <RunLog entries={run.log} live={isRunActive(run.status)} />
              </div>
            </section>
          </>
        )}
      </div>
    </Dialog>
  );
}

function Meta({ k, v }: { k: string; v: string }) {
  return (
    <div className="min-w-0">
      <dt className="eyebrow">{k}</dt>
      <dd className="mono mt-0.5 truncate text-[13px] text-ink" title={v}>
        {v}
      </dd>
    </div>
  );
}
