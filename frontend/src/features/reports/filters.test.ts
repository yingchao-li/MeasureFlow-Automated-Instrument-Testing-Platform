import { makeRun } from '@/test/fixtures';
import { EMPTY_FILTERS, filterRuns, hasActiveFilters, uniqueSorted } from './filters';

const runs = [
  makeRun({ run_id: 'run-a', status: 'PASS', label: 'nightly', created_at: '2026-11-10T12:00:00.000Z' }),
  makeRun({ run_id: 'run-b', status: 'FAIL', sequence_id: 'gain_verification', sequence_name: 'Gain Verification', dut: { profile: 'LOWGAIN', firmware: '1.2.0' }, created_at: '2026-11-12T12:00:00.000Z' }),
  makeRun({ run_id: 'run-c', status: 'ERROR', dut: { profile: 'NORMAL', firmware: '1.2.0' }, created_at: '2026-11-14T12:00:00.000Z' }),
];

describe('filterRuns', () => {
  it('returns everything for empty filters', () => {
    expect(filterRuns(runs, EMPTY_FILTERS)).toHaveLength(3);
    expect(hasActiveFilters(EMPTY_FILTERS)).toBe(false);
  });
  it('filters by sequence, status, firmware and profile', () => {
    expect(filterRuns(runs, { ...EMPTY_FILTERS, sequence: 'gain_verification' }).map((r) => r.run_id)).toEqual(['run-b']);
    expect(filterRuns(runs, { ...EMPTY_FILTERS, status: 'ERROR' }).map((r) => r.run_id)).toEqual(['run-c']);
    expect(filterRuns(runs, { ...EMPTY_FILTERS, firmware: '1.2.0' }).map((r) => r.run_id)).toEqual(['run-b', 'run-c']);
    expect(filterRuns(runs, { ...EMPTY_FILTERS, profile: 'LOWGAIN' }).map((r) => r.run_id)).toEqual(['run-b']);
  });
  it('matches free text against id, label and sequence name case-insensitively', () => {
    expect(filterRuns(runs, { ...EMPTY_FILTERS, text: 'NIGHTLY' }).map((r) => r.run_id)).toEqual(['run-a']);
    expect(filterRuns(runs, { ...EMPTY_FILTERS, text: 'gain ver' }).map((r) => r.run_id)).toEqual(['run-b']);
    expect(filterRuns(runs, { ...EMPTY_FILTERS, text: 'run-c' }).map((r) => r.run_id)).toEqual(['run-c']);
    expect(filterRuns(runs, { ...EMPTY_FILTERS, text: 'nothing' })).toEqual([]);
  });
  it('applies an inclusive local date range', () => {
    expect(filterRuns(runs, { ...EMPTY_FILTERS, from: '2026-11-12', to: '2026-11-12' }).map((r) => r.run_id)).toEqual(['run-b']);
    expect(filterRuns(runs, { ...EMPTY_FILTERS, from: '2026-11-13' }).map((r) => r.run_id)).toEqual(['run-c']);
    expect(filterRuns(runs, { ...EMPTY_FILTERS, to: '2026-11-10' }).map((r) => r.run_id)).toEqual(['run-a']);
  });
  it('uniqueSorted sorts versions numerically', () => {
    expect(uniqueSorted(['1.10.0', '1.2.0', '1.2.0', '1.0.0'])).toEqual(['1.0.0', '1.2.0', '1.10.0']);
  });
});
