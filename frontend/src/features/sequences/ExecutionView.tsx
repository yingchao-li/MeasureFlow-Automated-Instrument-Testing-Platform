import { FlaskConical } from 'lucide-react';
import type { RunDetail } from '@/api/types';
import { SweepChart } from '@/components/charts/SweepChart';
import { EmptyState, ErrorState, Panel, SkeletonRows } from '@/components/ui';
import { formatDateTime } from '@/lib/format';
import { isRunActive } from '@/lib/status';
import { ResultsTable } from './ResultsTable';
import { RunBanner, RunLog, StepList } from './RunParts';

interface ExecutionViewProps {
  run: RunDetail | null | undefined;
  loading: boolean;
  error: Error | null;
  onRetry: () => void;
  stale: boolean;
}

/** Live view of one run: banner + progress, steps, results table, sweep chart, log tail. */
export function ExecutionView({ run, loading, error, onRetry, stale }: ExecutionViewProps) {
  if (!run && loading) {
    return (
      <Panel title="Execution">
        <SkeletonRows rows={6} />
      </Panel>
    );
  }
  if (!run && error) {
    return (
      <Panel title="Execution">
        <ErrorState error={error} onRetry={onRetry} compact />
      </Panel>
    );
  }
  if (!run) {
    return (
      <Panel title="Execution">
        <EmptyState icon={FlaskConical} title="No run yet" description="Choose a sequence, review its parameters and press Start run. Progress, results and the log appear here live." />
      </Panel>
    );
  }

  const active = isRunActive(run.status);
  const hasSweep = run.tasks.some((t) => t.kind === 'freq_sweep');
  return (
    <section aria-label="Execution" className={stale ? 'space-y-4 opacity-70' : 'space-y-4'}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="flex items-baseline gap-3">
          <h2 className="text-sm font-semibold text-ink">Execution</h2>
          <p className="mono text-xs text-ink-3">
            {run.sequence_name} &middot; {run.run_id}
            {run.label ? ` · ${run.label}` : ''}
          </p>
        </div>
        <p className="mono text-xs text-ink-3">
          DUT {run.dut.profile} fw {run.dut.firmware} &middot; {formatDateTime(run.started_at ?? run.created_at)}
        </p>
      </div>
      <RunBanner run={run} />
      <div className="grid gap-4 xl:grid-cols-[minmax(280px,340px)_minmax(0,1fr)]">
        <Panel title="Steps" description={`${run.steps.length}`} flush>
          <StepList steps={run.steps} currentStep={run.current_step} />
        </Panel>
        <Panel title="Results" description={`${run.tasks.length} measurements`} flush>
          <ResultsTable tasks={run.tasks} live={active} maxHeight={520} />
        </Panel>
      </div>
      <div className={hasSweep ? 'grid grid-cols-12 gap-4' : ''}>
        {hasSweep && (
          <div className="col-span-12 xl:col-span-5">
            <SweepChart tasks={run.tasks} />
          </div>
        )}
        <div className={hasSweep ? 'col-span-12 xl:col-span-7' : ''}>
          <Panel title="Test log" description="tail of this run" flush>
            <RunLog entries={run.log} live={active} />
          </Panel>
        </div>
      </div>
    </section>
  );
}
