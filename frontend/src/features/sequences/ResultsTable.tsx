import { useEffect, useMemo, useRef, useState } from 'react';
import { ListChecks } from 'lucide-react';
import type { Task } from '@/api/types';
import { cn, EmptyState, Segmented, StatusBadge, Table, TableContainer, Td, Th, Tr } from '@/components/ui';
import { formatDurationMs, formatLimits, formatMeasured, formatTime } from '@/lib/format';
import { ERROR_CODE_HELP } from '@/lib/status';

interface ResultsTableProps {
  tasks: ReadonlyArray<Task>;
  /** true while the run is active: the table follows the newest row */
  live?: boolean;
  maxHeight?: number;
  /** hide the filter bar (drawers) */
  compact?: boolean;
}

type Filter = 'all' | 'problems';

/**
 * Results of a run: one row per measurement task. FAIL (valid value outside limits, amber) and
 * ERROR (communication / software problem, red) are separate statuses and show their code and message.
 */
export function ResultsTable({ tasks, live, maxHeight = 400, compact }: ResultsTableProps) {
  const [filter, setFilter] = useState<Filter>('all');
  const problems = useMemo(() => tasks.filter((t) => t.status === 'FAIL' || t.status === 'ERROR'), [tasks]);
  const rows = filter === 'problems' ? problems : tasks;
  const isEmpty = tasks.length === 0;

  const scroller = useRef<HTMLDivElement>(null);
  const stick = useRef(true);
  useEffect(() => {
    const el = scroller.current;
    if (live && stick.current && el) el.scrollTop = el.scrollHeight;
  }, [tasks.length, live]);
  // When a run ends (or a finished run is shown) bring the first problem row into view, otherwise show the top.
  useEffect(() => {
    const el = scroller.current;
    if (live || !el) return;
    const bad = el.querySelector<HTMLElement>('[data-status="FAIL"],[data-status="ERROR"]');
    if (!bad) {
      el.scrollTop = 0;
      return;
    }
    const anchor = (bad.previousElementSibling as HTMLElement | null) ?? bad; // keep one row of context
    const head = el.querySelector('thead')?.getBoundingClientRect().height ?? 32;
    el.scrollTop = Math.max(0, anchor.getBoundingClientRect().top - el.getBoundingClientRect().top + el.scrollTop - head);
  }, [live, filter, isEmpty]);

  if (tasks.length === 0) {
    return <EmptyState compact icon={ListChecks} title="No results yet" description="Measurement results appear here as soon as the first measurement completes." />;
  }

  return (
    <div>
      {!compact && (
        <div className="flex items-center justify-between border-b border-border px-4 py-2">
          <Segmented<Filter>
            label="Filter results"
            size="sm"
            value={filter}
            onChange={setFilter}
            options={[
              { value: 'all', label: `All ${tasks.length}` },
              { value: 'problems', label: `FAIL / ERROR ${problems.length}` },
            ]}
          />
        </div>
      )}
      <TableContainer
        label="Measurement results"
        maxHeight={maxHeight}
        scrollRef={scroller}
        onScroll={() => {
          const el = scroller.current;
          if (el) stick.current = el.scrollHeight - el.scrollTop - el.clientHeight < 32;
        }}
      >
        <Table>
          <thead>
            <tr>
              <Th>Test</Th>
              <Th numeric>Measured</Th>
              <Th numeric>Limits</Th>
              <Th>Status</Th>
              <Th numeric>Tries</Th>
              <Th numeric>Duration</Th>
              <Th numeric>Time</Th>
            </tr>
          </thead>
          <tbody>
            {rows.map((t) => (
              <ResultRow key={t.task_id} task={t} />
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-6 text-center text-xs text-ink-3">
                  No FAIL or ERROR results.
                </td>
              </tr>
            )}
          </tbody>
        </Table>
      </TableContainer>
    </div>
  );
}

export function ResultRow({ task: t }: { task: Task }) {
  const problem = t.status === 'FAIL' || t.status === 'ERROR';
  return (
    <Tr data-status={t.status} className={cn(t.status === 'ERROR' && 'bg-danger-soft/40', t.status === 'FAIL' && 'bg-warn-soft/40')}>
      <Td className="min-w-[200px] max-w-[320px] py-1.5 align-top">
        <p className="truncate font-medium text-ink" title={t.test_name}>
          {t.test_name}
        </p>
        {problem && (
          <p className="mt-0.5 flex flex-wrap items-baseline gap-x-2 text-xs">
            {t.error_code && (
              <span className={cn('mono rounded px-1 text-[11px]', t.status === 'ERROR' ? 'bg-danger-soft text-danger-text' : 'bg-warn-soft text-warn-text')} title={ERROR_CODE_HELP[t.error_code]}>
                {t.error_code}
              </span>
            )}
            <span className="text-ink-2">{t.message ?? (t.error_code ? ERROR_CODE_HELP[t.error_code] : '')}</span>
          </p>
        )}
      </Td>
      <Td numeric className="whitespace-nowrap align-top">
        {t.measured ? formatMeasured(t.kind, t.measured) : <span className="text-ink-3">{'—'}</span>}
      </Td>
      <Td numeric className="whitespace-nowrap align-top text-ink-2">
        {formatLimits(t.limits)}
      </Td>
      <Td className="align-top">
        <StatusBadge status={t.status} />
      </Td>
      <Td numeric className={cn('align-top', t.attempts > 1 ? 'text-warn-text' : 'text-ink-2')} title={t.attempts > 1 ? 'Retried after a communication error' : undefined}>
        {t.attempts}
      </Td>
      <Td numeric className="whitespace-nowrap align-top text-ink-2">
        {formatDurationMs(t.duration_ms)}
      </Td>
      <Td numeric className="whitespace-nowrap align-top text-ink-3" title={t.timestamp}>
        {formatTime(t.timestamp)}
      </Td>
    </Tr>
  );
}
