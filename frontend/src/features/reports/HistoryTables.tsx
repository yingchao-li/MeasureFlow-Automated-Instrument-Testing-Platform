import { useEffect, useMemo, useState } from 'react';
import { Search, X } from 'lucide-react';
import { api } from '@/api';
import type { RunSummary, Task } from '@/api/types';
import {
  Button,
  EmptyState,
  ErrorState,
  Pagination,
  Segmented,
  SelectField,
  SkeletonRows,
  StatusBadge,
  Table,
  TableContainer,
  Td,
  TextField,
  Th,
  Tr,
} from '@/components/ui';
import { usePolling } from '@/hooks/usePolling';
import { formatDateTime, formatDurationMs, formatLimits, formatMeasured, kindLabel, relativeTime } from '@/lib/format';
import { ERROR_CODE_HELP } from '@/lib/status';
import { DownloadLinks } from './DownloadLinks';
import { EMPTY_FILTERS, filterRuns, hasActiveFilters, uniqueSorted, type RunFilters } from './filters';

const PAGE_SIZE = 15;
const FETCH_PAGE = 200;
const MAX_RUNS = 1000;

/** Fetch the whole run history (newest first) in pages so the client can filter and paginate it. */
async function fetchAllRuns(signal: AbortSignal): Promise<{ runs: RunSummary[]; total: number }> {
  const first = await api.testRuns({ limit: FETCH_PAGE, offset: 0 }, { signal });
  const runs = [...first.runs];
  while (runs.length < Math.min(first.total, MAX_RUNS)) {
    const next = await api.testRuns({ limit: FETCH_PAGE, offset: runs.length }, { signal });
    if (next.runs.length === 0) break;
    runs.push(...next.runs);
  }
  return { runs, total: first.total };
}

const STATUS_OPTIONS = ['PASS', 'FAIL', 'ERROR', 'CANCELLED', 'RUNNING'].map((s) => ({ value: s, label: s }));
const ALL = (label: string) => ({ value: '', label });

type Mode = 'runs' | 'results';

interface HistoryProps {
  onOpenRun: (runId: string) => void;
}

/** History tab: runs (client-side filters) or individual measurements (server-side filters + pagination). */
export function HistoryPanel({ onOpenRun }: HistoryProps) {
  const [mode, setMode] = useState<Mode>('runs');
  return (
    <div className="rounded-lg border border-border bg-surface shadow-sm">
      {mode === 'runs' ? <RunsHistory onOpenRun={onOpenRun} mode={mode} onMode={setMode} /> : <ResultsHistory onOpenRun={onOpenRun} mode={mode} onMode={setMode} />}
    </div>
  );
}

function ModeSwitch({ mode, onMode }: { mode: Mode; onMode: (m: Mode) => void }) {
  return (
    <Segmented<Mode>
      label="History view"
      value={mode}
      onChange={onMode}
      options={[
        { value: 'runs', label: 'Runs' },
        { value: 'results', label: 'Measurements' },
      ]}
    />
  );
}

/* ------------------------------------------------------------------ runs */

function RunsHistory({ onOpenRun, mode, onMode }: HistoryProps & { mode: Mode; onMode: (m: Mode) => void }) {
  const [filters, setFilters] = useState<RunFilters>(EMPTY_FILTERS);
  const [page, setPage] = useState(0);
  const poll = usePolling(fetchAllRuns, { intervalMs: 8000 });
  const all = poll.data?.runs;

  const options = useMemo(() => {
    const runs = all ?? [];
    return {
      sequences: uniqueSorted(runs.map((r) => r.sequence_id)).map((id) => ({ value: id, label: runs.find((r) => r.sequence_id === id)?.sequence_name ?? id })),
      firmwares: uniqueSorted(runs.map((r) => r.dut.firmware)).map((v) => ({ value: v, label: v })),
      profiles: uniqueSorted(runs.map((r) => r.dut.profile)).map((v) => ({ value: v, label: v })),
    };
  }, [all]);

  const filtered = useMemo(() => (all ? filterRuns(all, filters) : []), [all, filters]);
  useEffect(() => setPage(0), [filters]);
  const pageRows = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const set = (patch: Partial<RunFilters>) => setFilters((f) => ({ ...f, ...patch }));

  return (
    <>
      <div className="space-y-3 border-b border-border p-4">
        <div className="flex flex-wrap items-end gap-3">
          <ModeSwitch mode={mode} onMode={onMode} />
          <TextField
            label="Search"
            hideLabel
            placeholder="Search run id, label or sequence"
            value={filters.text}
            onChange={(text) => set({ text })}
            wrapperClassName="w-72"
            type="search"
            aria-label="Search runs"
          />
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <SelectField label="Sequence" value={filters.sequence} onChange={(sequence) => set({ sequence })} options={[ALL('All sequences'), ...options.sequences]} wrapperClassName="w-48" />
          <SelectField label="Status" value={filters.status} onChange={(status) => set({ status })} options={[ALL('Any status'), ...STATUS_OPTIONS]} wrapperClassName="w-36" />
          <SelectField label="Firmware" value={filters.firmware} onChange={(firmware) => set({ firmware })} options={[ALL('Any firmware'), ...options.firmwares]} wrapperClassName="w-36" />
          <SelectField label="DUT profile" value={filters.profile} onChange={(profile) => set({ profile })} options={[ALL('Any profile'), ...options.profiles]} wrapperClassName="w-36" />
          <TextField label="From" type="date" value={filters.from} onChange={(from) => set({ from })} mono wrapperClassName="w-40" max={filters.to || undefined} />
          <TextField label="To" type="date" value={filters.to} onChange={(to) => set({ to })} mono wrapperClassName="w-40" min={filters.from || undefined} />
          {hasActiveFilters(filters) && (
            <Button size="sm" variant="ghost" icon={<X aria-hidden className="h-3.5 w-3.5" />} onClick={() => setFilters(EMPTY_FILTERS)} className="mb-0.5">
              Clear filters
            </Button>
          )}
        </div>
      </div>

      {!all && poll.isLoading && (
        <div className="p-4">
          <SkeletonRows rows={8} />
        </div>
      )}
      {!all && !poll.isLoading && poll.error && <ErrorState error={poll.error} onRetry={() => void poll.refresh()} />}
      {all && all.length === 0 && <EmptyState icon={Search} title="No test runs yet" description="Runs appear here as soon as a test sequence has been started. Open Test Sequences to start one." />}
      {all && all.length > 0 && filtered.length === 0 && (
        <EmptyState icon={Search} title="No runs match these filters" description="Widen the date range or clear a filter." action={<Button size="sm" onClick={() => setFilters(EMPTY_FILTERS)}>Clear filters</Button>} />
      )}
      {all && filtered.length > 0 && (
        <>
          <TableContainer label="Run history">
            <Table>
              <thead>
                <tr>
                  <Th>Run</Th>
                  <Th>Status</Th>
                  <Th>DUT</Th>
                  <Th numeric>Pass / Fail / Error</Th>
                  <Th numeric>Duration</Th>
                  <Th numeric>Created</Th>
                  <Th numeric>Report</Th>
                </tr>
              </thead>
              <tbody>
                {pageRows.map((r) => (
                  <Tr key={r.run_id} interactive onClick={() => onOpenRun(r.run_id)}>
                    <Td className="max-w-[260px] py-1.5">
                      <button type="button" onClick={(e) => (e.stopPropagation(), onOpenRun(r.run_id))} className="block w-full truncate text-left font-medium text-ink hover:underline" aria-label={`Open details of ${r.sequence_name} ${r.run_id}`}>
                        {r.sequence_name}
                      </button>
                      <span className="mono block truncate text-[11px] text-ink-3">{r.label ? `${r.label} · ` : ''}{r.run_id}</span>
                    </Td>
                    <Td>
                      <StatusBadge status={r.status} />
                    </Td>
                    <Td mono className="whitespace-nowrap text-xs text-ink-2">
                      {r.dut.profile} &middot; {r.dut.firmware}
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
                    <Td numeric className="whitespace-nowrap text-xs text-ink-2" title={relativeTime(r.created_at)}>
                      {formatDateTime(r.created_at)}
                    </Td>
                    <Td className="w-[1%]">
                      <DownloadLinks runId={r.run_id} />
                    </Td>
                  </Tr>
                ))}
              </tbody>
            </Table>
          </TableContainer>
          <Pagination page={page} pageSize={PAGE_SIZE} total={filtered.length} onPage={setPage} />
          {poll.data && poll.data.total > MAX_RUNS && <p className="border-t border-border px-4 py-2 text-xs text-ink-3">Showing the newest {MAX_RUNS} of {poll.data.total} runs.</p>}
        </>
      )}
    </>
  );
}

/* ------------------------------------------------------------------ measurements */

const KIND_OPTIONS = ['rms', 'gain', 'thd', 'snr', 'noise_floor', 'freq_sweep'].map((k) => ({ value: k, label: kindLabel(k) }));

function ResultsHistory({ onOpenRun, mode, onMode }: HistoryProps & { mode: Mode; onMode: (m: Mode) => void }) {
  const [f, setF] = useState({ status: '', kind: '', firmware: '', profile: '' });
  const [page, setPage] = useState(0);
  const key = JSON.stringify([f, page]);
  const poll = usePolling((signal) => api.testResults({ limit: PAGE_SIZE, offset: page * PAGE_SIZE, ...f }, { signal }), { intervalMs: 8000, resetKey: key });
  const set = (patch: Partial<typeof f>) => (setF((s) => ({ ...s, ...patch })), setPage(0));
  const rows = poll.data?.results;

  return (
    <>
      <div className="space-y-3 border-b border-border p-4">
        <div className="flex flex-wrap items-end gap-3">
          <ModeSwitch mode={mode} onMode={onMode} />
          <SelectField label="Measurement" value={f.kind} onChange={(kind) => set({ kind })} options={[ALL('All measurements'), ...KIND_OPTIONS]} wrapperClassName="w-44" />
          <SelectField label="Status" value={f.status} onChange={(status) => set({ status })} options={[ALL('Any status'), ...['PASS', 'FAIL', 'ERROR', 'CANCELLED'].map((s) => ({ value: s, label: s }))]} wrapperClassName="w-36" />
          <SelectField label="Firmware" value={f.firmware} onChange={(firmware) => set({ firmware })} options={[ALL('Any firmware'), ...['1.0.0', '1.1.0', '1.2.0'].map((v) => ({ value: v, label: v }))]} wrapperClassName="w-36" />
          <SelectField label="DUT profile" value={f.profile} onChange={(profile) => set({ profile })} options={[ALL('Any profile'), ...['NORMAL', 'LOWGAIN', 'HIGHTHD', 'NOISY', 'CLIPPING'].map((v) => ({ value: v, label: v }))]} wrapperClassName="w-36" />
          {Object.values(f).some(Boolean) && (
            <Button size="sm" variant="ghost" icon={<X aria-hidden className="h-3.5 w-3.5" />} onClick={() => (setF({ status: '', kind: '', firmware: '', profile: '' }), setPage(0))} className="mb-0.5">
              Clear filters
            </Button>
          )}
        </div>
      </div>
      {!rows && poll.isLoading && (
        <div className="p-4">
          <SkeletonRows rows={8} />
        </div>
      )}
      {!rows && !poll.isLoading && poll.error && <ErrorState error={poll.error} onRetry={() => void poll.refresh()} />}
      {rows && rows.length === 0 && <EmptyState icon={Search} title="No measurements found" description="Nothing matches these filters yet. Clear a filter or run a test sequence." />}
      {rows && rows.length > 0 && poll.data && (
        <>
          <TableContainer label="Measurement history">
            <Table>
              <thead>
                <tr>
                  <Th>Test</Th>
                  <Th numeric>Measured</Th>
                  <Th numeric>Limits</Th>
                  <Th>Status</Th>
                  <Th>DUT</Th>
                  <Th>Run</Th>
                  <Th numeric>Time</Th>
                </tr>
              </thead>
              <tbody>
                {rows.map((t: Task) => (
                  <Tr key={t.task_id}>
                    <Td className="max-w-[260px] py-1.5">
                      <span className="block truncate font-medium text-ink" title={t.test_name}>{t.test_name}</span>
                      {(t.status === 'FAIL' || t.status === 'ERROR') && t.error_code && (
                        <span className="mono block truncate text-[11px] text-ink-3" title={ERROR_CODE_HELP[t.error_code]}>{t.error_code}</span>
                      )}
                    </Td>
                    <Td numeric className="whitespace-nowrap">{formatMeasured(t.kind, t.measured)}</Td>
                    <Td numeric className="whitespace-nowrap text-ink-2">{formatLimits(t.limits)}</Td>
                    <Td>
                      <StatusBadge status={t.status} />
                    </Td>
                    <Td mono className="whitespace-nowrap text-xs text-ink-2">
                      {t.dut_profile} &middot; {t.dut_firmware}
                    </Td>
                    <Td className="max-w-[200px]">
                      <button type="button" onClick={() => onOpenRun(t.run_id)} className="mono block w-full truncate text-left text-[11px] text-primary-text hover:underline" aria-label={`Open details of run ${t.run_id}`}>
                        {t.run_id}
                      </button>
                    </Td>
                    <Td numeric className="whitespace-nowrap text-xs text-ink-2">{formatDateTime(t.timestamp)}</Td>
                  </Tr>
                ))}
              </tbody>
            </Table>
          </TableContainer>
          <Pagination page={page} pageSize={PAGE_SIZE} total={poll.data.total} onPage={setPage} />
        </>
      )}
    </>
  );
}
