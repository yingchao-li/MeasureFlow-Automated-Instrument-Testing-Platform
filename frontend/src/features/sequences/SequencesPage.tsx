import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Square } from 'lucide-react';
import { api } from '@/api';
import { ApiError, errorMessage } from '@/api/errors';
import type { DutProfile, RunRequest, Sequence } from '@/api/types';
import { PageBody, PageToolbar, RefreshIndicator } from '@/components/layout/PageToolbar';
import { Button, StatusBadge } from '@/components/ui';
import { useHealth } from '@/context/HealthContext';
import { useToast } from '@/context/ToastContext';
import { usePolling } from '@/hooks/usePolling';
import { RUN_LABEL_MAX } from '@/lib/ranges';
import { defaultValues, validateParameters } from '@/lib/parameters';
import { isRunActive } from '@/lib/status';
import { ExecutionView } from './ExecutionView';
import { RunSetup, retriesCheck, type RunSettings } from './RunSetup';
import { SequencePicker } from './SequencePicker';

const RUN_POLL_MS = 250; // 4 Hz while a run is active
const IDLE_POLL_MS = 3000;

function initialSettings(seq: Sequence): RunSettings {
  return { values: defaultValues(seq.parameters), profile: seq.dut.profile, firmware: seq.dut.firmware, retries: '1', label: '' };
}

export function SequencesPage() {
  const toast = useToast();
  const { offline, runningTest } = useHealth();
  const sequences = usePolling((signal) => api.sequences({ signal }), { intervalMs: 60000 });
  const list = sequences.data?.sequences;

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [settingsBySeq, setSettingsBySeq] = useState<Record<string, RunSettings>>({});
  const [runId, setRunId] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const executionRef = useRef<HTMLDivElement>(null);

  // Pick the first sequence once the list is there.
  useEffect(() => {
    if (!selectedId && list && list.length > 0) setSelectedId((list[0] as Sequence).id);
  }, [list, selectedId]);

  const sequence = list?.find((s) => s.id === selectedId) ?? null;
  const settings = useMemo<RunSettings | null>(() => (sequence ? (settingsBySeq[sequence.id] ?? initialSettings(sequence)) : null), [sequence, settingsBySeq]);
  const patchSettings = useCallback(
    (patch: Partial<RunSettings>) => {
      if (!sequence) return;
      setSettingsBySeq((all) => ({ ...all, [sequence.id]: { ...(all[sequence.id] ?? initialSettings(sequence)), ...patch } }));
      setFormError(null);
    },
    [sequence],
  );

  // Run status: the explicit run, else the active one, else the most recently finished (backend default).
  const status = usePolling((signal) => api.testStatus({ ...(runId ? { run_id: runId } : {}), log_tail: 100 }, { signal }), {
    resetKey: runId ?? 'default',
    intervalMs: (d) => (isRunActive(d?.run?.status) || runningTest ? RUN_POLL_MS : IDLE_POLL_MS),
  });
  const run = status.data?.run ?? null;
  const active = isRunActive(run?.status) || Boolean(runningTest);

  // Announce completion once.
  const prevStatus = useRef<string | null>(null);
  useEffect(() => {
    const cur = run?.status ?? null;
    const prev = prevStatus.current;
    if (run && prev && isRunActive(prev as never) && !isRunActive(cur as never)) {
      const fn = cur === 'PASS' ? toast.success : cur === 'CANCELLED' ? toast.info : toast.error;
      fn(`Run ${cur}`, `${run.sequence_name} · ${run.counts.PASS} pass, ${run.counts.FAIL} fail, ${run.counts.ERROR} error`);
    }
    prevStatus.current = cur;
  }, [run, toast]);

  const validation = useMemo(() => (sequence && settings ? validateParameters(sequence.parameters, settings.values) : null), [sequence, settings]);
  const retries = settings ? retriesCheck(settings.retries) : null;
  const labelTooLong = (settings?.label.length ?? 0) > RUN_LABEL_MAX;

  const startBlocked: string | null = offline
    ? 'Backend unreachable — cannot start a run.'
    : !sequence
      ? 'Select a sequence first.'
      : active
        ? `A run is already active${runningTest ? ` (${runningTest})` : ''}. Cancel it or wait for it to finish.`
        : validation && validation.invalidCount > 0
          ? `Fix ${validation.invalidCount} invalid ${validation.invalidCount === 1 ? 'value' : 'values'} before starting.`
          : retries?.error
            ? `Retries: ${retries.error.toLowerCase()}.`
            : labelTooLong
              ? 'Shorten the label.'
              : null;
  const cancelBlocked: string | null = offline ? 'Backend unreachable.' : !active ? 'No run is active.' : run?.cancel_requested ? 'Cancellation already requested.' : null;

  const start = useCallback(async () => {
    if (!sequence || !settings || !validation || startBlocked || retries?.value == null) return;
    const body: RunRequest = {
      sequence_id: sequence.id,
      parameters: validation.numbers,
      dut: { profile: settings.profile as DutProfile, firmware: settings.firmware },
      retries: retries.value,
      ...(settings.label.trim() ? { label: settings.label.trim() } : {}),
    };
    setStarting(true);
    setFormError(null);
    try {
      const res = await api.runTest(body);
      setRunId(res.run.run_id);
      void status.refresh();
      toast.info('Run started', `${res.run.sequence_name} · ${res.run.run_id}`);
      requestAnimationFrame(() => executionRef.current?.scrollIntoView({ behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'start' }));
    } catch (e) {
      const msg = e instanceof ApiError ? `${e.message}${e.field ? ` (${e.field})` : ''}` : errorMessage(e);
      setFormError(msg);
      toast.error('Could not start the run', msg);
    } finally {
      setStarting(false);
    }
  }, [sequence, settings, validation, startBlocked, retries, status, toast]);

  const cancel = useCallback(async () => {
    if (cancelBlocked) return;
    setCancelling(true);
    try {
      await api.cancelTest(run?.run_id);
      void status.refresh();
    } catch (e) {
      toast.error('Could not cancel the run', errorMessage(e));
    } finally {
      setCancelling(false);
    }
  }, [cancelBlocked, run, status, toast]);

  return (
    <>
      <PageToolbar
        title="Test Sequences"
        subtitle={sequence ? sequence.name : undefined}
        progress={run && isRunActive(run.status) ? run.progress : null}
        actions={
          <>
            {run && (
              <span className="flex items-center gap-2 text-xs text-ink-2">
                <StatusBadge status={run.status} />
                <span className="mono">{Math.round(run.progress * 100)}%</span>
              </span>
            )}
            {active && (
              <Button size="sm" variant="secondary" icon={<Square aria-hidden className="h-3.5 w-3.5" />} loading={cancelling} disabledReason={cancelBlocked} onClick={() => void cancel()}>
                Cancel run
              </Button>
            )}
            <RefreshIndicator lastUpdated={status.lastUpdated} fetching={status.isFetching} stale={offline} onRefresh={() => void status.refresh()} />
          </>
        }
      />
      <PageBody>
        <div className="space-y-6">
          <div className="grid grid-cols-12 gap-5">
            <div className="col-span-12 lg:col-span-4 2xl:col-span-3">
              <SequencePicker sequences={list} selectedId={selectedId} onSelect={(id) => (setSelectedId(id), setFormError(null))} loading={sequences.isLoading} error={sequences.error} onRetry={() => void sequences.refresh()} />
            </div>
            <div className="col-span-12 min-w-0 lg:col-span-8 2xl:col-span-9">
              {sequence && settings && validation ? (
                <RunSetup
                  sequence={sequence}
                  settings={settings}
                  validation={validation}
                  onChange={patchSettings}
                  onParam={(key, value) => patchSettings({ values: { ...settings.values, [key]: value } })}
                  onResetParam={(key) => patchSettings({ values: { ...settings.values, [key]: defaultValues(sequence.parameters)[key] ?? '' } })}
                  onResetAll={() => patchSettings({ values: defaultValues(sequence.parameters) })}
                  onStart={() => void start()}
                  onCancel={() => void cancel()}
                  starting={starting}
                  cancelling={cancelling}
                  startBlocked={startBlocked}
                  cancelBlocked={cancelBlocked}
                  formError={formError}
                  locked={false}
                />
              ) : null}
            </div>
          </div>
          <div ref={executionRef} className="scroll-mt-16">
            <ExecutionView run={run} loading={status.isLoading} error={status.error} onRetry={() => void status.refresh()} stale={offline} />
          </div>
        </div>
      </PageBody>
    </>
  );
}
