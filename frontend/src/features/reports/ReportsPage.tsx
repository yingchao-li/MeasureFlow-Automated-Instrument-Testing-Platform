import { useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { FileClock, GitCompare, ShieldAlert, TrendingUp } from 'lucide-react';
import { api } from '@/api';
import { PageBody, PageToolbar, RefreshIndicator } from '@/components/layout/PageToolbar';
import { cn, Panel, TabPanel, Tabs } from '@/components/ui';
import { useHealth } from '@/context/HealthContext';
import { usePolling } from '@/hooks/usePolling';
import { formatPercent } from '@/lib/format';
import { FirmwarePanel, ReliabilityPanel, TrendPanel } from './AnalysisPanels';
import { HistoryPanel } from './HistoryTables';
import { RunDrawer } from './RunDrawer';

type ReportTab = 'history' | 'trends' | 'firmware' | 'reliability';
const TABS: ReadonlyArray<ReportTab> = ['history', 'trends', 'firmware', 'reliability'];

export function ReportsPage() {
  const { offline } = useHealth();
  const [params, setParams] = useSearchParams();
  const summary = usePolling((signal) => api.reportSummary({}, { signal }), { intervalMs: 10000 });

  const tabParam = params.get('tab');
  const tab: ReportTab = TABS.includes(tabParam as ReportTab) ? (tabParam as ReportTab) : 'history';
  const runId = params.get('run');

  const update = useCallback(
    (patch: Record<string, string | null>) => {
      setParams(
        (p) => {
          const n = new URLSearchParams(p);
          for (const [k, v] of Object.entries(patch)) {
            if (v === null) n.delete(k);
            else n.set(k, v);
          }
          return n;
        },
        { replace: false },
      );
    },
    [setParams],
  );

  const s = summary.data;
  const stale = offline;
  const retry = () => void summary.refresh();

  return (
    <>
      <PageToolbar title="Reports" subtitle="History, trends and firmware comparison" actions={<RefreshIndicator lastUpdated={summary.lastUpdated} fetching={summary.isFetching} stale={stale} onRefresh={retry} />} />
      <PageBody>
        <div className={cn('space-y-5', stale && 'opacity-70')}>
          <Panel label="Summary" bodyClassName="p-0">
            <dl className="grid grid-cols-4 divide-x divide-border">
              <Kpi label="Pass rate" value={s ? (s.tasks.pass_rate === null ? '—' : formatPercent(s.tasks.pass_rate, 1)) : undefined} sub={s ? `${s.tasks.PASS} of ${s.tasks.total} measurements` : undefined} />
              <Kpi label="Runs" value={s ? String(s.runs.total) : undefined} sub={s ? `${s.runs.PASS} pass · ${s.runs.FAIL} fail · ${s.runs.ERROR} error · ${s.runs.CANCELLED} cancelled` : undefined} />
              <Kpi label="Measurements" value={s ? String(s.tasks.total) : undefined} sub={s ? `${s.tasks.FAIL} fail · ${s.tasks.ERROR} error` : undefined} />
              <Kpi label="Recovery rate" value={s ? (s.recovery.recovery_rate === null || s.recovery.tasks_with_retry === 0 ? '—' : formatPercent(s.recovery.recovery_rate, 0)) : undefined} sub={s ? (s.recovery.tasks_with_retry === 0 ? 'no measurement needed a retry' : `${s.recovery.recovered} of ${s.recovery.tasks_with_retry} retries recovered`) : undefined} />
            </dl>
          </Panel>

          <Tabs<ReportTab>
            label="Report sections"
            idPrefix="rep"
            value={tab}
            onChange={(t) => update({ tab: t })}
            tabs={[
              { id: 'history', label: 'History', icon: <FileClock aria-hidden className="h-3.5 w-3.5" /> },
              { id: 'trends', label: 'Trends', icon: <TrendingUp aria-hidden className="h-3.5 w-3.5" /> },
              { id: 'firmware', label: 'Firmware comparison', icon: <GitCompare aria-hidden className="h-3.5 w-3.5" /> },
              { id: 'reliability', label: 'Failures and recovery', icon: <ShieldAlert aria-hidden className="h-3.5 w-3.5" /> },
            ]}
          />
          <TabPanel id="history" value={tab} idPrefix="rep">
            <HistoryPanel onOpenRun={(id) => update({ run: id })} />
          </TabPanel>
          <TabPanel id="trends" value={tab} idPrefix="rep">
            <TrendPanel summary={s} loading={summary.isLoading} error={summary.error} onRetry={retry} />
          </TabPanel>
          <TabPanel id="firmware" value={tab} idPrefix="rep">
            <FirmwarePanel summary={s} loading={summary.isLoading} error={summary.error} onRetry={retry} />
          </TabPanel>
          <TabPanel id="reliability" value={tab} idPrefix="rep">
            <ReliabilityPanel summary={s} loading={summary.isLoading} error={summary.error} onRetry={retry} />
          </TabPanel>
        </div>
      </PageBody>
      <RunDrawer runId={runId} onClose={() => update({ run: null })} />
    </>
  );
}

function Kpi({ label, value, sub }: { label: string; value: string | undefined; sub: string | undefined }) {
  return (
    <div className="min-w-0 px-5 py-3.5">
      <dt className="eyebrow">{label}</dt>
      <dd className="mt-1.5">
        {value === undefined ? (
          <span className="block h-7 w-20 animate-pulse-soft rounded bg-border" aria-label="Loading" />
        ) : (
          <span className="mono text-2xl font-medium leading-none text-ink">{value}</span>
        )}
        <span className="mt-1.5 block truncate text-xs text-ink-3">{sub ?? ' '}</span>
      </dd>
    </div>
  );
}

