import { useCallback, useEffect, useImperativeHandle, useRef, useState, forwardRef, type KeyboardEvent } from 'react';
import { CornerDownLeft, Eraser, TriangleAlert } from 'lucide-react';
import { api } from '@/api';
import { ApiError } from '@/api/errors';
import type { CommandResponse, InstrumentKind } from '@/api/types';
import { Button, cn, Kbd } from '@/components/ui';
import { formatDurationMs, formatTimeMs } from '@/lib/format';
import { checkScpiCommand, quickCommands } from '@/lib/scpi';
import { getSession, pushHistory, toResult, trimEntries, type ConsoleEntry } from './consoleSession';

export interface ScpiConsoleHandle {
  focus: () => void;
}

interface ScpiConsoleProps {
  instrumentId: string;
  instrumentKind: InstrumentKind;
  /** Reason sending is impossible (not connected, offline...). null = ready. */
  disabledReason?: string | null;
  /** Injectable for tests; defaults to POST /api/instruments/command. */
  send?: (id: string, command: string) => Promise<CommandResponse>;
}

/**
 * Interactive SCPI console: monospace transcript, Enter sends, Up/Down walk the history,
 * quick-insert chips, response + duration + SCPI error queue entry per command.
 */
export const ScpiConsole = forwardRef<ScpiConsoleHandle, ScpiConsoleProps>(function ScpiConsole(
  { instrumentId, instrumentKind, disabledReason = null, send = (id, cmd) => api.command(id, cmd) },
  ref,
) {
  const session = getSession(instrumentId);
  const [entries, setEntries] = useState<ConsoleEntry[]>(session.entries);
  const [history, setHistory] = useState<string[]>(session.history);
  const [input, setInput] = useState('');
  const [inputError, setInputError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const logRef = useRef<HTMLDivElement>(null);
  /** index into history while browsing with the arrow keys; history.length = the draft */
  const cursor = useRef<number>(session.history.length);
  const draft = useRef('');

  useImperativeHandle(ref, () => ({ focus: () => inputRef.current?.focus() }), []);

  // New instrument: load its session.
  useEffect(() => {
    const s = getSession(instrumentId);
    setEntries(s.entries);
    setHistory(s.history);
    cursor.current = s.history.length;
    setInput('');
    setInputError(null);
  }, [instrumentId]);

  // Keep the newest line in view.
  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [entries]);

  const commit = useCallback(
    (nextEntries: ConsoleEntry[], nextHistory?: string[]) => {
      const s = getSession(instrumentId);
      s.entries = nextEntries;
      setEntries(nextEntries);
      if (nextHistory) {
        s.history = nextHistory;
        setHistory(nextHistory);
      }
    },
    [instrumentId],
  );

  const submit = useCallback(async () => {
    const command = input.trim();
    const check = checkScpiCommand(command);
    if (!check.ok) {
      setInputError(check.error);
      return;
    }
    if (disabledReason || busy) return;
    setInputError(null);
    const s = getSession(instrumentId);
    const id = s.nextId++;
    const nextHistory = pushHistory(s, command);
    const pending: ConsoleEntry = { id, command, at: new Date().toISOString(), result: 'pending' };
    commit(trimEntries([...s.entries, pending]), nextHistory);
    cursor.current = nextHistory.length;
    draft.current = '';
    setInput('');
    setBusy(true);
    try {
      const res = await send(instrumentId, command);
      commit(getSession(instrumentId).entries.map((e) => (e.id === id ? { ...e, at: res.timestamp || e.at, result: toResult(res) } : e)));
    } catch (e) {
      const code = e instanceof ApiError ? e.code : 'ERROR';
      const message = e instanceof Error ? e.message : String(e);
      commit(getSession(instrumentId).entries.map((x) => (x.id === id ? { ...x, result: { type: 'fail', code, message } } : x)));
    } finally {
      setBusy(false);
      inputRef.current?.focus();
    }
  }, [input, disabledReason, busy, instrumentId, commit, send]);

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      void submit();
    } else if (e.key === 'ArrowUp') {
      if (history.length === 0) return;
      e.preventDefault();
      if (cursor.current === history.length) draft.current = input;
      cursor.current = Math.max(0, cursor.current - 1);
      setInput(history[cursor.current] ?? '');
      setInputError(null);
    } else if (e.key === 'ArrowDown') {
      if (cursor.current >= history.length) return;
      e.preventDefault();
      cursor.current = Math.min(history.length, cursor.current + 1);
      setInput(cursor.current === history.length ? draft.current : (history[cursor.current] ?? ''));
    } else if (e.key === 'Escape' && input) {
      e.preventDefault();
      e.stopPropagation();
      setInput('');
      cursor.current = history.length;
    }
  };

  const insert = (command: string) => {
    setInput(command);
    setInputError(null);
    cursor.current = history.length;
    const el = inputRef.current;
    el?.focus();
    requestAnimationFrame(() => el?.setSelectionRange(command.length, command.length));
  };

  const clear = () => commit([]);

  return (
    <div className="flex min-h-0 flex-col">
      <div className="mb-2 flex flex-wrap items-center gap-1.5" role="group" aria-label="Quick insert commands">
        <span className="mr-1 text-xs text-ink-3">Insert</span>
        {quickCommands(instrumentKind).map((q) => (
          <button
            key={q.label}
            type="button"
            title={q.hint}
            onClick={() => insert(q.command)}
            className="mono h-6 rounded border border-border-strong bg-surface px-1.5 text-[11px] text-ink-2 transition-colors hover:bg-hover hover:text-ink"
          >
            {q.label.trimEnd()}
          </button>
        ))}
      </div>

      <div
        ref={logRef}
        role="log"
        aria-live="polite"
        aria-label="SCPI transcript"
        tabIndex={0}
        className="mono h-[300px] overflow-y-auto rounded-t-md border border-b-0 border-border bg-sunken px-3 py-2 text-[12.5px] leading-[1.55]"
      >
        {entries.length === 0 ? (
          <p className="font-sans text-xs text-ink-3">
            No commands sent yet. Type a command below, for example <span className="mono text-ink-2">*IDN?</span>, and press Enter. Queries end with <span className="mono text-ink-2">?</span> and show a response; setters show nothing unless the instrument queues an error.
          </p>
        ) : (
          entries.map((e) => <TranscriptEntry key={e.id} entry={e} />)
        )}
      </div>

      <div className={cn('flex items-center gap-2 rounded-b-md border bg-surface px-3 transition-colors focus-within:outline focus-within:outline-2 focus-within:-outline-offset-1 focus-within:outline-ring', inputError ? 'border-danger' : 'border-control')}>
        <span aria-hidden className="mono select-none text-sm text-primary">
          &rsaquo;
        </span>
        <input
          ref={inputRef}
          value={input}
          onChange={(e) => {
            setInput(e.target.value);
            if (inputError) setInputError(null);
          }}
          onKeyDown={onKeyDown}
          aria-label="SCPI command"
          aria-invalid={inputError ? true : undefined}
          aria-describedby="scpi-input-help"
          placeholder={disabledReason ?? 'SCPI command, e.g. *IDN?'}
          disabled={Boolean(disabledReason)}
          spellCheck={false}
          autoCapitalize="off"
          autoCorrect="off"
          autoComplete="off"
          className="mono h-9 min-w-0 flex-1 bg-transparent text-[13px] text-ink outline-none placeholder:font-sans placeholder:text-ink-3 focus-visible:outline-none disabled:cursor-not-allowed"
        />
        <Button size="sm" variant="primary" onClick={() => void submit()} loading={busy} disabledReason={disabledReason} icon={<CornerDownLeft aria-hidden className="h-3.5 w-3.5" />}>
          Send
        </Button>
      </div>
      <div className="mt-1.5 flex items-center justify-between gap-3 text-xs">
        <p id="scpi-input-help" className={cn(inputError ? 'text-danger-text' : 'text-ink-3')}>
          {inputError ?? (
            <>
              <Kbd>Enter</Kbd> send &middot; <Kbd>&uarr;</Kbd> <Kbd>&darr;</Kbd> history &middot; <Kbd>/</Kbd> focus
            </>
          )}
        </p>
        <Button size="sm" variant="ghost" icon={<Eraser aria-hidden className="h-3.5 w-3.5" />} onClick={clear} disabled={entries.length === 0}>
          Clear
        </Button>
      </div>
    </div>
  );
});

function TranscriptEntry({ entry }: { entry: ConsoleEntry }) {
  const r = entry.result;
  return (
    <div className="mb-1.5 break-all" data-testid="scpi-entry">
      <div className="flex items-baseline gap-2">
        <span className="shrink-0 text-[11px] text-ink-3">{formatTimeMs(entry.at)}</span>
        <span aria-hidden className="shrink-0 text-primary">
          &rsaquo;
        </span>
        <span className="font-medium text-ink">{entry.command}</span>
      </div>
      {r === 'pending' && <p className="pl-[5.4rem] text-ink-3">&hellip;</p>}
      {r !== 'pending' && r.type === 'ok' && (
        <div className="pl-[5.4rem]">
          {r.response !== null && (
            <p className="flex items-baseline justify-between gap-3 text-ink">
              <span>
                {r.response}
                {r.truncated && <span className="ml-2 font-sans text-[11px] text-warn-text">(truncated)</span>}
              </span>
              <span className="shrink-0 text-[11px] text-ink-3">{formatDurationMs(r.durationMs)}</span>
            </p>
          )}
          {r.response === null && !r.error && <p className="flex justify-between text-ink-3">ok<span className="text-[11px]">{formatDurationMs(r.durationMs)}</span></p>}
          {r.error && (
            <p className="flex items-start justify-between gap-3 text-danger-text" role="alert">
              <span className="flex items-start gap-1.5">
                <TriangleAlert aria-hidden className="mt-[3px] h-3 w-3 shrink-0" />
                <span>
                  SCPI error {r.error.code}: {r.error.message}
                </span>
              </span>
              {r.response === null && <span className="shrink-0 text-[11px] text-ink-3">{formatDurationMs(r.durationMs)}</span>}
            </p>
          )}
        </div>
      )}
      {r !== 'pending' && r.type === 'fail' && (
        <p className="flex items-start gap-1.5 pl-[5.4rem] text-danger-text" role="alert">
          <TriangleAlert aria-hidden className="mt-[3px] h-3 w-3 shrink-0" />
          <span>
            {r.code}: {r.message}
          </span>
        </p>
      )}
    </div>
  );
}
