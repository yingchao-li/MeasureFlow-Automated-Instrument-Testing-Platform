import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowDownToLine, Eraser, Pause, Play } from 'lucide-react';
import { api } from '@/api';
import type { Instrument, LogEntry, LogLevel } from '@/api/types';
import { Button, cn, EmptyState, ErrorState, SelectField, Switch } from '@/components/ui';
import { usePolling } from '@/hooks/usePolling';
import { formatDurationMs, formatTimeMs } from '@/lib/format';
import { LEVEL_ORDER } from '@/lib/status';

const MAX_ENTRIES = 1000;
const MAX_ROWS = 400;

/** Incrementally fetches SCPI traffic (`/api/logs?source=scpi&since_seq=...`). */
export function useCommLog(paused: boolean) {
  const lastSeq = useRef(0);
  const [entries, setEntries] = useState<LogEntry[]>([]);

  const poll = usePolling((signal) => api.logs({ source: 'scpi', limit: lastSeq.current === 0 ? 300 : 500, since_seq: lastSeq.current }, { signal }), {
    enabled: !paused,
    intervalMs: 1000,
  });

  useEffect(() => {
    const res = poll.data;
    if (!res) return;
    if (res.last_seq < lastSeq.current) {
      // backend restarted: its sequence numbers start over
      lastSeq.current = 0;
      setEntries([]);
      void poll.refresh();
      return;
    }
    const fresh = res.logs.filter((l) => l.seq > lastSeq.current);
    if (fresh.length === 0) return;
    lastSeq.current = Math.max(...fresh.map((l) => l.seq));
    setEntries((prev) => [...prev, ...fresh].slice(-MAX_ENTRIES));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [poll.data]);

  const clear = () => setEntries([]);
  return { entries, clear, error: poll.error, isLoading: poll.isLoading, refresh: poll.refresh, failureCount: poll.failureCount };
}

const LEVEL_FILTERS: Array<{ value: string; label: string }> = [
  { value: 'debug', label: 'All levels' },
  { value: 'warn', label: 'Warnings and errors' },
  { value: 'error', label: 'Errors only' },
];

interface CommLogProps {
  instruments: Instrument[];
  /** pre-selected instrument filter ("all" or an instrument id) */
  instrumentId: string;
}

/** Live communication log: TX / RX lines coloured, level + instrument filters, autoscroll toggle, pause, clear. */
export function CommLog({ instruments, instrumentId }: CommLogProps) {
  const [paused, setPaused] = useState(false);
  const [autoscroll, setAutoscroll] = useState(true);
  const [level, setLevel] = useState<LogLevel>('debug');
  const [filterId, setFilterId] = useState(instrumentId);
  const log = useCommLog(paused);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => setFilterId(instrumentId), [instrumentId]);

  const rows = useMemo(() => {
    const min = LEVEL_ORDER[level];
    return log.entries
      .filter((e) => LEVEL_ORDER[e.level] >= min)
      .filter((e) => filterId === 'all' || e.fields?.['instrument'] === filterId)
      .slice(-MAX_ROWS);
  }, [log.entries, level, filterId]);

  useEffect(() => {
    const el = scroller.current;
    if (autoscroll && el) el.scrollTop = el.scrollHeight;
  }, [rows, autoscroll]);

  const onScroll = () => {
    const el = scroller.current;
    if (!el) return;
    const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
    if (!nearBottom && autoscroll) setAutoscroll(false);
  };

  return (
    <div className="flex min-h-0 flex-col">
      <div className="mb-2 flex flex-wrap items-end justify-between gap-3">
        <div className="flex items-end gap-3">
          <SelectField
            label="Instrument"
            value={filterId}
            onChange={setFilterId}
            wrapperClassName="w-44"
            options={[{ value: 'all', label: 'All instruments' }, ...instruments.map((i) => ({ value: i.id, label: i.id }))]}
          />
          <SelectField label="Level" value={level} onChange={(v) => setLevel(v as LogLevel)} wrapperClassName="w-48" options={LEVEL_FILTERS} />
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-2 text-xs text-ink-2">
            <Switch label="Autoscroll" checked={autoscroll} onChange={setAutoscroll} />
            <span className="flex items-center gap-1">
              <ArrowDownToLine aria-hidden className="h-3.5 w-3.5" />
              Autoscroll
            </span>
          </label>
          <Button size="sm" variant="secondary" icon={paused ? <Play aria-hidden className="h-3.5 w-3.5" /> : <Pause aria-hidden className="h-3.5 w-3.5" />} onClick={() => setPaused((p) => !p)} aria-pressed={paused}>
            {paused ? 'Resume' : 'Pause'}
          </Button>
          <Button size="sm" variant="ghost" icon={<Eraser aria-hidden className="h-3.5 w-3.5" />} onClick={log.clear} disabled={log.entries.length === 0}>
            Clear
          </Button>
        </div>
      </div>

      <div
        ref={scroller}
        onScroll={onScroll}
        role="log"
        aria-label="SCPI communication log"
        aria-live="off"
        tabIndex={0}
        className="mono h-[340px] overflow-auto rounded-md border border-border bg-sunken text-[12px] leading-[1.6]"
      >
        {log.error && log.entries.length === 0 ? (
          <ErrorState error={log.error} onRetry={() => void log.refresh()} compact />
        ) : rows.length === 0 ? (
          <EmptyState compact title={log.isLoading ? 'Loading log…' : 'No SCPI traffic yet'} description={log.isLoading ? undefined : 'Commands exchanged with the instruments appear here live, with direction, text and round-trip time.'} />
        ) : (
          <ul>
            {rows.map((e) => (
              <LogRow key={e.seq} e={e} />
            ))}
          </ul>
        )}
      </div>
      <p className="mt-1.5 flex items-center justify-between text-xs text-ink-3" aria-live="polite">
        <span>
          {rows.length} line{rows.length === 1 ? '' : 's'}
          {log.entries.length > rows.length ? ` shown of ${log.entries.length}` : ''}
          {paused ? ' · paused' : ''}
        </span>
        {log.failureCount > 0 && <span className="text-warn-text">Log refresh failing, retrying</span>}
      </p>
    </div>
  );
}

function LogRow({ e }: { e: LogEntry }) {
  const f = e.fields ?? {};
  const dir = typeof f['direction'] === 'string' ? (f['direction'] as string) : null;
  const text = typeof f['text'] === 'string' ? (f['text'] as string) : e.message;
  const inst = typeof f['instrument'] === 'string' ? (f['instrument'] as string) : '';
  const dur = typeof f['duration_ms'] === 'number' ? (f['duration_ms'] as number) : null;
  const isError = e.level === 'error';
  const isWarn = e.level === 'warn';
  return (
    <li className={cn('flex items-baseline gap-2 px-3 py-px hover:bg-hover', isError && 'bg-danger-soft', isWarn && 'bg-warn-soft')}>
      <span className="shrink-0 text-ink-3">{formatTimeMs(e.ts)}</span>
      <span className="w-14 shrink-0 truncate text-ink-3">{inst}</span>
      <span
        className={cn(
          'w-6 shrink-0 text-center text-[11px] font-semibold',
          dir === 'TX' ? 'text-primary-text' : dir === 'RX' ? 'text-success-text' : isError ? 'text-danger-text' : 'text-ink-3',
        )}
      >
        {dir ?? (isError ? 'ERR' : e.level.toUpperCase().slice(0, 3))}
      </span>
      <span className={cn('min-w-0 flex-1 break-all', isError ? 'text-danger-text' : isWarn ? 'text-warn-text' : dir === 'RX' ? 'text-ink' : 'text-ink')}>
        {text}
        {isError && typeof f['kind'] === 'string' && <span className="ml-2 text-[11px]">[{f['kind'] as string}]</span>}
      </span>
      {dur !== null && <span className="shrink-0 text-[11px] text-ink-3">{formatDurationMs(dur)}</span>}
    </li>
  );
}
