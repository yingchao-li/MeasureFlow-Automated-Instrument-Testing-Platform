import { useCallback, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Cable, Plug, Unplug } from 'lucide-react';
import { api } from '@/api';
import { errorMessage } from '@/api/errors';
import type { Instrument } from '@/api/types';
import { CalibrationChip, InstrumentStateBadge, KIND_LABEL } from '@/components/InstrumentBits';
import { PageBody, PageToolbar, RefreshIndicator } from '@/components/layout/PageToolbar';
import { Button, cn, EmptyState, ErrorState, Panel, Skeleton, TabPanel, Tabs } from '@/components/ui';
import { useHealth } from '@/context/HealthContext';
import { useToast } from '@/context/ToastContext';
import { useHotkey } from '@/hooks/useHotkey';
import { isAnalyzer, isDut, isSigGen, useInstruments } from '@/hooks/useInstruments';
import { formatDate, formatNumber, relativeTime } from '@/lib/format';
import { CommLog } from './CommLog';
import { AnalyzerForm, DutForm, SigGenForm } from './SettingsForms';
import { ScpiConsole, type ScpiConsoleHandle } from './ScpiConsole';

type DetailTab = 'config' | 'console' | 'log';

export function InstrumentsPage() {
  const toast = useToast();
  const { offline, runningTest } = useHealth();
  const inst = useInstruments(2000);
  const [params, setParams] = useSearchParams();
  const [tab, setTab] = useState<DetailTab>('config');
  const [busyId, setBusyId] = useState<string | null>(null);
  const consoleRef = useRef<ScpiConsoleHandle>(null);
  const [focusConsole, setFocusConsole] = useState(0);

  const selectedId = params.get('id') ?? inst.instruments[0]?.id ?? null;
  const selected = inst.instruments.find((i) => i.id === selectedId) ?? inst.instruments[0];

  const select = useCallback(
    (id: string) => {
      setParams(
        (p) => {
          const n = new URLSearchParams(p);
          n.set('id', id);
          return n;
        },
        { replace: true },
      );
    },
    [setParams],
  );

  // "/" jumps to the console input.
  useHotkey('/', (e) => {
    e.preventDefault();
    setTab('console');
    setFocusConsole((n) => n + 1);
  });
  useEffect(() => {
    if (focusConsole > 0 && tab === 'console') consoleRef.current?.focus();
  }, [focusConsole, tab]);

  const act = useCallback(
    async (kind: 'connect' | 'disconnect', id: string) => {
      setBusyId(id);
      try {
        const res = kind === 'connect' ? await api.connect(id) : await api.disconnect(id);
        inst.apply(res.instruments);
        const failed = res.instruments.filter((i) => kind === 'connect' && i.state !== 'connected');
        if (failed.length) toast.error(`${failed.map((f) => f.name).join(', ')} did not connect`, failed.map((f) => f.last_error ?? f.state).join('\n'));
        else toast.success(id === 'all' ? (kind === 'connect' ? 'All instruments connected' : 'All instruments disconnected') : `${kind === 'connect' ? 'Connected' : 'Disconnected'} ${id}`);
      } catch (e) {
        toast.error(kind === 'connect' ? 'Connect failed' : 'Disconnect failed', errorMessage(e));
      } finally {
        setBusyId(null);
        void inst.refresh();
      }
    },
    [inst, toast],
  );

  const anyDisconnected = inst.instruments.some((i) => i.state !== 'connected');
  const anyConnected = inst.anyConnected;
  const blockedByTest = runningTest ? `Test ${runningTest} is running and owns the instruments` : null;
  const blockedByOffline = offline ? 'Backend unreachable' : null;

  return (
    <>
      <PageToolbar
        title="Instruments"
        subtitle={inst.instruments.length ? `${inst.instruments.filter((i) => i.state === 'connected').length} of ${inst.instruments.length} connected` : undefined}
        actions={
          <>
            <Button size="sm" variant="secondary" icon={<Unplug aria-hidden className="h-3.5 w-3.5" />} loading={busyId === 'all'} disabledReason={blockedByOffline ?? blockedByTest ?? (!anyConnected ? 'No instrument is connected' : null)} onClick={() => void act('disconnect', 'all')}>
              Disconnect all
            </Button>
            <Button size="sm" variant="primary" icon={<Plug aria-hidden className="h-3.5 w-3.5" />} loading={busyId === 'all'} disabledReason={blockedByOffline ?? (!anyDisconnected ? 'All instruments are already connected' : null)} onClick={() => void act('connect', 'all')}>
              Connect all
            </Button>
            <RefreshIndicator lastUpdated={inst.lastUpdated} fetching={inst.isFetching} stale={offline} onRefresh={() => void inst.refresh()} />
          </>
        }
      />
      <PageBody>
        {inst.isLoading && inst.instruments.length === 0 && <LoadingSkeleton />}
        {!inst.isLoading && inst.instruments.length === 0 && inst.error && <ErrorState error={inst.error} onRetry={() => void inst.refresh()} />}
        {!inst.isLoading && inst.instruments.length === 0 && !inst.error && <EmptyState icon={Cable} title="No instruments configured" description="Add instruments to configs/instruments.json and restart the backend." />}
        {inst.instruments.length > 0 && selected && (
          <div className={cn('grid grid-cols-12 gap-5', offline && 'opacity-70')}>
            <div className="col-span-12 lg:col-span-4 2xl:col-span-3">
              <nav aria-label="Instruments">
                <ul className="space-y-2">
                  {inst.instruments.map((i) => (
                    <li key={i.id}>
                      <InstrumentCard
                        instrument={i}
                        selected={i.id === selected.id}
                        busy={busyId === i.id || busyId === 'all'}
                        onSelect={() => select(i.id)}
                        onToggle={() => void act(i.state === 'connected' ? 'disconnect' : 'connect', i.id)}
                        toggleBlocked={blockedByOffline ?? (i.state === 'connected' ? (i.leased_by ? `Leased by test ${i.leased_by}` : blockedByTest) : null)}
                      />
                    </li>
                  ))}
                </ul>
              </nav>
            </div>

            <div className="col-span-12 min-w-0 space-y-4 lg:col-span-8 2xl:col-span-9">
              <InstrumentHeader instrument={selected} />
              <Tabs<DetailTab>
                label="Instrument sections"
                idPrefix="inst"
                value={tab}
                onChange={setTab}
                tabs={[
                  { id: 'config', label: 'Configuration' },
                  { id: 'console', label: 'SCPI console' },
                  { id: 'log', label: 'Communication log' },
                ]}
              />
              <TabPanel id="config" value={tab} idPrefix="inst">
                <ConfigPane instrument={selected} blockedReason={blockedByOffline ?? blockedByTest ?? (selected.state !== 'connected' ? 'Connect the instrument to change its settings' : selected.leased_by ? `Leased by test ${selected.leased_by}` : null)} onApplied={(i) => inst.apply([i])} onConnect={() => void act('connect', selected.id)} connecting={busyId === selected.id} />
              </TabPanel>
              <TabPanel id="console" value={tab} idPrefix="inst">
                <Panel title="SCPI console" description={`${selected.id} · ${selected.host}:${selected.port}`}>
                  <ScpiConsole
                    ref={consoleRef}
                    instrumentId={selected.id}
                    instrumentKind={selected.kind}
                    disabledReason={blockedByOffline ?? (selected.state !== 'connected' ? 'Connect the instrument to send commands' : blockedByTest)}
                  />
                </Panel>
              </TabPanel>
              <TabPanel id="log" value={tab} idPrefix="inst">
                <Panel title="Communication log" description="SCPI traffic, live">
                  <CommLog instruments={inst.instruments} instrumentId={selected.id} />
                </Panel>
              </TabPanel>
            </div>
          </div>
        )}
      </PageBody>
    </>
  );
}

function LoadingSkeleton() {
  return (
    <div className="grid grid-cols-12 gap-5" role="status" aria-label="Loading instruments">
      <div className="col-span-12 space-y-2 lg:col-span-4 2xl:col-span-3">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-[92px] w-full" />
        ))}
      </div>
      <div className="col-span-12 space-y-4 lg:col-span-8 2xl:col-span-9">
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-9 w-72" />
        <Skeleton className="h-72 w-full" />
      </div>
    </div>
  );
}

function InstrumentCard({
  instrument: i,
  selected,
  busy,
  onSelect,
  onToggle,
  toggleBlocked,
}: {
  instrument: Instrument;
  selected: boolean;
  busy: boolean;
  onSelect: () => void;
  onToggle: () => void;
  toggleBlocked: string | null;
}) {
  const connected = i.state === 'connected';
  return (
    <div className={cn('rounded-lg border bg-surface shadow-sm transition-colors', selected ? 'border-primary ring-1 ring-primary' : 'border-border hover:border-border-strong')}>
      <button type="button" aria-current={selected ? 'true' : undefined} onClick={onSelect} className="block w-full rounded-t-lg px-3.5 pb-2 pt-3 text-left">
        <div className="flex items-center justify-between gap-2">
          <span className="eyebrow truncate">{KIND_LABEL[i.kind]}</span>
          <InstrumentStateBadge state={i.state} />
        </div>
        <p className="mt-1.5 truncate text-sm font-semibold text-ink">{i.name}</p>
        <p className="mono mt-0.5 truncate text-[11px] text-ink-3">
          {i.id} &middot; {i.host}:{i.port}
          {i.firmware ? ` · fw ${i.firmware}` : ''}
        </p>
      </button>
      <div className="flex items-center justify-between gap-2 px-3.5 pb-3">
        <span className="mono truncate text-[11px] text-ink-3">{connected && i.latency_ms !== null ? `${formatNumber(i.latency_ms, 1)} ms` : i.last_error ? i.last_error : '—'}</span>
        <Button size="sm" variant={connected ? 'secondary' : 'primary'} loading={busy} disabledReason={toggleBlocked} onClick={onToggle} icon={connected ? <Unplug aria-hidden className="h-3.5 w-3.5" /> : <Plug aria-hidden className="h-3.5 w-3.5" />}>
          {connected ? 'Disconnect' : 'Connect'}
        </Button>
      </div>
    </div>
  );
}

function InstrumentHeader({ instrument: i }: { instrument: Instrument }) {
  const idn = i.idn?.split(',').map((s) => s.trim()) ?? [];
  return (
    <Panel>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2.5">
            <h2 className="truncate text-lg font-semibold tracking-[-0.01em] text-ink">{i.name}</h2>
            <InstrumentStateBadge state={i.state} />
          </div>
          <p className="mono mt-1 text-xs text-ink-3">
            {i.id} &middot; {KIND_LABEL[i.kind]} &middot; {i.host}:{i.port}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <CalibrationChip calibration={i.calibration} />
          {i.leased_by && <span className="mono rounded bg-info-soft px-1.5 py-0.5 text-[11px] text-info-text">leased by {i.leased_by}</span>}
        </div>
      </div>
      {i.state === 'error' && i.last_error && (
        <p role="alert" className="mt-3 rounded border border-danger/40 bg-danger-soft px-3 py-2 text-xs text-danger-text">
          {i.last_error}
        </p>
      )}
      <dl className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3 border-t border-border pt-3 text-xs sm:grid-cols-4">
        <Fact label="Model" value={idn[1]} />
        <Fact label="Serial" value={idn[2]} />
        <Fact label="Firmware" value={i.firmware ?? idn[3]} />
        <Fact label="Latency" value={i.latency_ms !== null && i.state === 'connected' ? `${formatNumber(i.latency_ms, 1)} ms` : undefined} />
        <Fact label="Last seen" value={i.last_seen ? relativeTime(i.last_seen) : undefined} />
        <Fact label="Calibration due" value={i.calibration?.due ? formatDate(i.calibration.due) : undefined} />
        <Fact label="IDN" value={i.idn ?? undefined} wide />
      </dl>
    </Panel>
  );
}

function Fact({ label, value, wide }: { label: string; value: string | undefined; wide?: boolean }) {
  return (
    <div className={cn('min-w-0', wide && 'col-span-2')}>
      <dt className="eyebrow">{label}</dt>
      <dd className="mono mt-0.5 truncate text-[13px] text-ink" title={value}>
        {value ?? '—'}
      </dd>
    </div>
  );
}

function ConfigPane({ instrument: i, blockedReason, onApplied, onConnect, connecting }: { instrument: Instrument; blockedReason: string | null; onApplied: (i: Instrument) => void; onConnect: () => void; connecting: boolean }) {
  if (i.state !== 'connected' || !i.settings) {
    return (
      <Panel>
        <EmptyState
          icon={Cable}
          title="Instrument is not connected"
          description="Connect it to read its current settings and change its configuration."
          action={
            <Button variant="primary" size="sm" icon={<Plug aria-hidden className="h-3.5 w-3.5" />} loading={connecting} onClick={onConnect} disabledReason={blockedReason && i.state === 'connected' ? blockedReason : null}>
              Connect {i.id}
            </Button>
          }
        />
      </Panel>
    );
  }
  const title = isSigGen(i) ? 'Signal generator settings' : isDut(i) ? 'Device under test settings' : 'Analyzer settings';
  return (
    <Panel title={title} description="Validated by the backend, ranges from the instrument spec">
      {isSigGen(i) && <SigGenForm instrument={i} blockedReason={blockedReason} onApplied={onApplied} />}
      {isDut(i) && <DutForm instrument={i} blockedReason={blockedReason} onApplied={onApplied} />}
      {isAnalyzer(i) && <AnalyzerForm instrument={i} blockedReason={blockedReason} onApplied={onApplied} />}
    </Panel>
  );
}
