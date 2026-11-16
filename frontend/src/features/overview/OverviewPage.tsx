import { useCallback, useState } from 'react';
import { api } from '@/api';
import { errorMessage } from '@/api/errors';
import type { LogEntry } from '@/api/types';
import { PageBody, PageToolbar, RefreshIndicator } from '@/components/layout/PageToolbar';
import { Button, cn, Panel } from '@/components/ui';
import { useHealth } from '@/context/HealthContext';
import { useToast } from '@/context/ToastContext';
import { useInstruments } from '@/hooks/useInstruments';
import { usePolling } from '@/hooks/usePolling';
import { LiveSection, MetricsStrip } from './LiveSection';
import { EventFeedPanel, InstrumentTiles, MeasurementStatsPanel, PassRatePanel, RecentRunsPanel, SystemStatusPanel } from './panels';
import { QuickStimulus } from './QuickStimulus';
import { useLiveMeasurement } from './useLiveMeasurement';
import { Plug } from 'lucide-react';

const EVENT_SOURCES = ['engine', 'system', 'env', 'api'] as const;

/** Non-SCPI events: SCPI traffic would drown the feed (it is shown on the Instruments page instead). */
async function fetchEvents(signal: AbortSignal): Promise<LogEntry[]> {
  const pages = await Promise.all(EVENT_SOURCES.map((source) => api.logs({ source, limit: 40 }, { signal })));
  return pages
    .flatMap((p) => p.logs)
    .filter((e) => e.level !== 'debug' && (e.source !== 'api' || e.level === 'warn' || e.level === 'error'))
    .sort((a, b) => b.seq - a.seq)
    .slice(0, 30);
}

export function OverviewPage() {
  const toast = useToast();
  const { health, error: healthError, isLoading: healthLoading, offline, runningTest, refresh: refreshHealth } = useHealth();
  const inst = useInstruments();
  const summary = usePolling((signal) => api.reportSummary({}, { signal }), { intervalMs: 10000 });
  const runs = usePolling((signal) => api.testRuns({ limit: 8 }, { signal }), { intervalMs: 5000 });
  const events = usePolling(fetchEvents, { intervalMs: 5000 });
  const live = useLiveMeasurement({ connected: inst.allConnected, runningTest, offline });
  const [connecting, setConnecting] = useState(false);

  const connectAll = useCallback(async () => {
    setConnecting(true);
    try {
      const res = await api.connect('all');
      inst.apply(res.instruments);
      const failed = res.instruments.filter((i) => i.state !== 'connected');
      if (failed.length) toast.error('Some instruments did not connect', failed.map((f) => `${f.name}: ${f.last_error ?? f.state}`).join('\n'));
      else toast.success('All instruments connected');
    } catch (e) {
      toast.error('Could not connect the instruments', errorMessage(e));
    } finally {
      setConnecting(false);
      void inst.refresh();
    }
  }, [inst, toast]);

  const refreshAll = useCallback(() => {
    void refreshHealth();
    void inst.refresh();
    void summary.refresh();
    void runs.refresh();
    void events.refresh();
    void live.refresh();
  }, [refreshHealth, inst, summary, runs, events, live]);

  const stimulusBlocked = offline
    ? 'Backend unreachable.'
    : !inst.byKind.siggen || inst.byKind.siggen.state !== 'connected'
      ? 'Connect the signal generator to change the stimulus.'
      : inst.byKind.siggen.leased_by || runningTest
        ? 'A test is running and owns the instruments.'
        : null;

  const stale = offline;
  const showConnect = inst.instruments.length > 0 && !inst.allConnected && !offline;

  return (
    <>
      <PageToolbar
        title="Overview"
        subtitle="System status and live signal"
        actions={
          <>
            {showConnect && (
              <Button size="sm" variant="primary" icon={<Plug aria-hidden className="h-3.5 w-3.5" />} loading={connecting} onClick={() => void connectAll()}>
                Connect all
              </Button>
            )}
            <RefreshIndicator lastUpdated={inst.lastUpdated} fetching={inst.isFetching} stale={stale} onRefresh={refreshAll} />
          </>
        }
      />
      <PageBody>
        <div className="space-y-5">
          <div className="grid grid-cols-12 gap-4">
            <div className="col-span-12 xl:col-span-3">
              <SystemStatusPanel health={health} error={healthError} loading={healthLoading} offline={offline} onRetry={() => void refreshHealth()} />
            </div>
            <div className="col-span-12 xl:col-span-9">
              <div className="grid h-full grid-cols-1 gap-4 sm:grid-cols-3">
                <InstrumentTiles instruments={inst.instruments} loading={inst.isLoading} error={inst.error} onRetry={() => void inst.refresh()} dimmed={stale} />
              </div>
            </div>
          </div>

          <LiveSection
            frame={live.frame}
            status={live.status}
            error={live.error}
            runningTest={runningTest}
            onConnectAll={() => void connectAll()}
            connecting={connecting}
            onRetry={() => void live.refresh()}
          />

          <div className="grid grid-cols-12 gap-4">
            <div className="col-span-12 xl:col-span-8">
              <Panel title="Live metrics" description="DUT output, latest acquisition" className="h-full">
                <div className="flex h-full items-center"><MetricsStrip metrics={live.frame?.metrics} dimmed={live.status !== 'live' && live.status !== 'loading'} /></div>
              </Panel>
            </div>
            <div className="col-span-12 xl:col-span-4">
              <QuickStimulus siggen={inst.byKind.siggen} blockedReason={stimulusBlocked} onApplied={(i) => inst.apply([i])} />
            </div>
          </div>

          <div className="grid grid-cols-12 gap-4">
            <div className="col-span-12 xl:col-span-4">
              <PassRatePanel summary={summary.data} loading={summary.isLoading} error={summary.error} onRetry={() => void summary.refresh()} dimmed={stale} />
            </div>
            <div className="col-span-12 xl:col-span-8">
              <RecentRunsPanel runs={runs.data?.runs} loading={runs.isLoading} error={runs.error} onRetry={() => void runs.refresh()} dimmed={stale} />
            </div>
          </div>

          <div className={cn('grid grid-cols-12 gap-4')}>
            <div className="col-span-12 xl:col-span-7">
              <MeasurementStatsPanel summary={summary.data} loading={summary.isLoading} error={summary.error} onRetry={() => void summary.refresh()} dimmed={stale} />
            </div>
            <div className="col-span-12 xl:col-span-5">
              <EventFeedPanel events={events.data} loading={events.isLoading} error={events.error} onRetry={() => void events.refresh()} dimmed={stale} />
            </div>
          </div>
        </div>
      </PageBody>
    </>
  );
}
