import type { RunSummary } from '@/api/types';

export interface RunFilters {
  text: string;
  sequence: string;
  status: string;
  firmware: string;
  profile: string;
  /** YYYY-MM-DD (local) or '' */
  from: string;
  to: string;
}

export const EMPTY_FILTERS: RunFilters = { text: '', sequence: '', status: '', firmware: '', profile: '', from: '', to: '' };

export function hasActiveFilters(f: RunFilters): boolean {
  return Object.values(f).some((v) => v !== '');
}

function startOfDay(ymd: string): number {
  const [y, m, d] = ymd.split('-').map(Number);
  return new Date(y as number, (m as number) - 1, d as number, 0, 0, 0, 0).getTime();
}

/** Client-side filtering of the run history (the backend only filters runs by status and sequence). */
export function filterRuns(runs: ReadonlyArray<RunSummary>, f: RunFilters): RunSummary[] {
  const text = f.text.trim().toLowerCase();
  const from = f.from ? startOfDay(f.from) : null;
  const to = f.to ? startOfDay(f.to) + 24 * 3600 * 1000 - 1 : null;
  return runs.filter((r) => {
    if (f.sequence && r.sequence_id !== f.sequence) return false;
    if (f.status && r.status !== f.status) return false;
    if (f.firmware && r.dut.firmware !== f.firmware) return false;
    if (f.profile && r.dut.profile !== f.profile) return false;
    const created = new Date(r.created_at).getTime();
    if (from !== null && created < from) return false;
    if (to !== null && created > to) return false;
    if (text) {
      const hay = `${r.run_id} ${r.label ?? ''} ${r.sequence_name} ${r.sequence_id}`.toLowerCase();
      if (!hay.includes(text)) return false;
    }
    return true;
  });
}

export function uniqueSorted(values: Iterable<string>): string[] {
  return Array.from(new Set(values)).sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
}
