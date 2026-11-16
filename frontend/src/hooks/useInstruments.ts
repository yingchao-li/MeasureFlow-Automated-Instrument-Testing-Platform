import { useCallback, useMemo, useState } from 'react';
import { api } from '@/api';
import type { AnalyzerInstrument, DutInstrument, Instrument, SigGenInstrument } from '@/api/types';
import { usePolling } from './usePolling';

export const isSigGen = (i: Instrument | undefined): i is SigGenInstrument => i?.kind === 'signal_generator';
export const isAnalyzer = (i: Instrument | undefined): i is AnalyzerInstrument => i?.kind === 'audio_analyzer';
export const isDut = (i: Instrument | undefined): i is DutInstrument => i?.kind === 'device_under_test';

/** Merge updated instrument objects (from connect / configure responses) into a list, preserving order. */
export function mergeInstruments(list: Instrument[], updated: Instrument[]): Instrument[] {
  const byId = new Map(updated.map((u) => [u.id, u]));
  const merged = list.map((i) => byId.get(i.id) ?? i);
  for (const u of updated) if (!list.some((i) => i.id === u.id)) merged.push(u);
  return merged;
}

/**
 * Instrument list polled every `intervalMs`. `apply` lets callers show the result of an action
 * (connect, configure) immediately, until the next poll replaces it.
 */
export function useInstruments(intervalMs = 3000) {
  const poll = usePolling((signal) => api.instruments({ signal }), { intervalMs });
  const [patch, setPatch] = useState<{ at: number; items: Instrument[] } | null>(null);

  const instruments = useMemo<Instrument[]>(() => {
    const base = poll.data?.instruments ?? [];
    if (patch && patch.at > (poll.lastUpdated ?? 0)) return mergeInstruments(base, patch.items);
    return base;
  }, [poll.data, poll.lastUpdated, patch]);

  const apply = useCallback((items: Instrument[]) => setPatch({ at: Date.now(), items }), []);
  const byKind = useMemo(
    () => ({
      siggen: instruments.find(isSigGen),
      analyzer: instruments.find(isAnalyzer),
      dut: instruments.find(isDut),
    }),
    [instruments],
  );
  const allConnected = instruments.length > 0 && instruments.every((i) => i.state === 'connected');
  const anyConnected = instruments.some((i) => i.state === 'connected');

  return { ...poll, instruments, byKind, allConnected, anyConnected, apply };
}
