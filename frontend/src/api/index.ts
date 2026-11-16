import { request, type RequestOptions } from './client';
import type {
  CommandResponse,
  ConfigureResponse,
  Environment,
  Health,
  InstrumentsResponse,
  LiveMeasurement,
  LogsQuery,
  LogsResponse,
  ReportSummary,
  ReportsResponse,
  RunDetailResponse,
  RunRequest,
  RunResponse,
  RunsQuery,
  RunsResponse,
  SequencesResponse,
  TaskResultsQuery,
  TaskResultsResponse,
} from './types';

type Opts = Pick<RequestOptions, 'signal' | 'timeoutMs'>;

/** One function per endpoint of INTERFACE.md section 5. */
export const api = {
  health: (o?: Opts) => request<Health>('/api/health', { timeoutMs: 4000, ...o }),
  environment: (o?: Opts) => request<Environment>('/api/environment', { timeoutMs: 15000, ...o }),

  instruments: (o?: Opts) => request<InstrumentsResponse>('/api/instruments', o),
  connect: (id: string, o?: Opts) =>
    request<InstrumentsResponse>('/api/instruments/connect', { method: 'POST', body: { id }, timeoutMs: 15000, ...o }),
  disconnect: (id: string, o?: Opts) =>
    request<InstrumentsResponse>('/api/instruments/disconnect', { method: 'POST', body: { id }, timeoutMs: 15000, ...o }),
  command: (id: string, command: string, o?: Opts) =>
    request<CommandResponse>('/api/instruments/command', { method: 'POST', body: { id, command }, timeoutMs: 15000, ...o }),
  configure: (id: string, settings: Record<string, string | number | boolean>, o?: Opts) =>
    request<ConfigureResponse>('/api/instruments/configure', { method: 'POST', body: { id, settings }, timeoutMs: 15000, ...o }),

  live: (params: { points?: number; bins?: number } = {}, o?: Opts) =>
    request<LiveMeasurement>('/api/measurements/live', { query: params, timeoutMs: 6000, ...o }),

  sequences: (o?: Opts) => request<SequencesResponse>('/api/sequences', o),
  runTest: (body: RunRequest, o?: Opts) => request<RunResponse>('/api/tests/run', { method: 'POST', body, timeoutMs: 10000, ...o }),
  cancelTest: (runId?: string, o?: Opts) =>
    request<RunResponse>('/api/tests/cancel', { method: 'POST', body: runId ? { run_id: runId } : {}, ...o }),
  testStatus: (params: { run_id?: string; log_tail?: number } = {}, o?: Opts) =>
    request<RunDetailResponse>('/api/tests/status', { query: params, ...o }),
  testResults: (query: TaskResultsQuery = {}, o?: Opts) => request<TaskResultsResponse>('/api/tests/results', { query, ...o }),
  testRuns: (query: RunsQuery = {}, o?: Opts) => request<RunsResponse>('/api/tests/runs', { query, ...o }),

  reports: (o?: Opts) => request<ReportsResponse>('/api/reports', o),
  reportSummary: (query: { sequence_id?: string; limit?: number } = {}, o?: Opts) =>
    request<ReportSummary>('/api/reports/summary', { query, timeoutMs: 15000, ...o }),
  logs: (query: LogsQuery = {}, o?: Opts) => request<LogsResponse>('/api/logs', { query, ...o }),
};

export type Api = typeof api;

/** Download URLs for a run (plain anchors; the backend sets Content-Disposition). */
export function reportUrl(runId: string, ext: 'csv' | 'html' | 'pdf'): string {
  return `/api/reports/${encodeURIComponent(runId)}.${ext}`;
}

export { ApiError, errorMessage, errorTitle, isApiError } from './errors';
export type * from './types';
