import { Activity, Cable, Check, ClipboardList, FileText, Gauge, Settings2, SlidersHorizontal, Waves, type LucideIcon } from 'lucide-react';
import type { Sequence, StepType } from '@/api/types';
import { cn, EmptyState, ErrorState, Panel, SkeletonRows } from '@/components/ui';

const STEP_ICON: Record<StepType, LucideIcon> = {
  init: Cable,
  configure_signal: Waves,
  configure_dut: SlidersHorizontal,
  measure: Gauge,
  sweep: Activity,
  cleanup: Settings2,
  report: FileText,
};
const STEP_LABEL: Record<StepType, string> = {
  init: 'Init',
  configure_signal: 'Stimulus',
  configure_dut: 'DUT',
  measure: 'Measure',
  sweep: 'Sweep',
  cleanup: 'Cleanup',
  report: 'Report',
};

interface SequencePickerProps {
  sequences: Sequence[] | undefined;
  selectedId: string | null;
  onSelect: (id: string) => void;
  loading: boolean;
  error: Error | null;
  onRetry: () => void;
}

/** Sequence list with descriptions; the selected one expands into its step preview. */
export function SequencePicker({ sequences, selectedId, onSelect, loading, error, onRetry }: SequencePickerProps) {
  return (
    <Panel title="Sequences" description={sequences ? `${sequences.length} available` : undefined} flush className="h-full">
      {!sequences && loading && (
        <div className="p-4">
          <SkeletonRows rows={6} />
        </div>
      )}
      {!sequences && !loading && error && <ErrorState error={error} onRetry={onRetry} compact />}
      {sequences && sequences.length === 0 && <EmptyState compact icon={ClipboardList} title="No sequences found" description="Add sequence files to configs/sequences/ and restart the backend." />}
      {sequences && sequences.length > 0 && (
        <ul role="radiogroup" aria-label="Test sequence" className="divide-y divide-border">
          {sequences.map((s) => {
            const selected = s.id === selectedId;
            return (
              <li key={s.id}>
                <button
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  onClick={() => onSelect(s.id)}
                  title={selected ? undefined : s.description}
                  className={cn('block w-full px-4 py-2.5 text-left transition-colors', selected ? 'bg-primary-soft' : 'hover:bg-hover')}
                >
                  <span className="flex items-center justify-between gap-2">
                    <span className="flex min-w-0 items-center gap-2">
                      <span aria-hidden className={cn('flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full border', selected ? 'border-primary bg-primary text-primary-fg' : 'border-control')}>
                        {selected && <Check className="h-2.5 w-2.5" strokeWidth={3.5} />}
                      </span>
                      <span className={cn('truncate text-sm font-medium', selected ? 'text-primary-text' : 'text-ink')}>{s.name}</span>
                    </span>
                    <span className="mono shrink-0 text-[11px] text-ink-3">v{s.version}</span>
                  </span>
                  <span className={cn('mt-1 block pl-[22px] text-xs leading-[18px] text-ink-2', selected ? '' : 'truncate')}>{s.description}</span>
                  {selected && (
                    <span className="mono mt-1 block pl-[22px] text-[11px] text-ink-3">
                      {s.steps.length} steps &middot; {s.parameters.length} parameters
                    </span>
                  )}
                </button>
                {selected && (
                  <ol aria-label={`${s.name} steps`} className="border-t border-primary/20 bg-surface px-4 py-2">
                    {s.steps.map((st, i) => {
                      const Icon = STEP_ICON[st.type] ?? Settings2;
                      return (
                        <li key={st.id} className="flex items-center gap-2 py-1 text-xs">
                          <span className="mono w-4 shrink-0 text-right text-[11px] text-ink-3">{i + 1}</span>
                          <Icon aria-hidden className="h-3.5 w-3.5 shrink-0 text-ink-3" />
                          <span className="min-w-0 flex-1 truncate text-ink-2">{st.name}</span>
                          <span className="shrink-0 rounded bg-sunken px-1 text-[10px] uppercase tracking-wide text-ink-3">{STEP_LABEL[st.type] ?? st.type}</span>
                        </li>
                      );
                    })}
                  </ol>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}
