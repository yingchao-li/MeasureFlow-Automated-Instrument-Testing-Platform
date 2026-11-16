import type { CommandResponse } from '@/api/types';

export type ConsoleResult =
  | { type: 'ok'; response: string | null; isQuery: boolean; durationMs: number; error: { code: number; message: string } | null; truncated: boolean }
  | { type: 'fail'; code: string; message: string };

export interface ConsoleEntry {
  id: number;
  command: string;
  at: string; // ISO
  result: ConsoleResult | 'pending';
}

export interface ConsoleSession {
  entries: ConsoleEntry[];
  history: string[];
  nextId: number;
}

const HISTORY_LIMIT = 100;
const ENTRY_LIMIT = 400;

/** In-memory per-instrument sessions so the transcript survives tab switches and instrument changes. */
const sessions = new Map<string, ConsoleSession>();

export function getSession(instrumentId: string): ConsoleSession {
  let s = sessions.get(instrumentId);
  if (!s) {
    s = { entries: [], history: [], nextId: 1 };
    sessions.set(instrumentId, s);
  }
  return s;
}

export function resetConsoleSessions(): void {
  sessions.clear();
}

export function pushHistory(session: ConsoleSession, command: string): string[] {
  const h = session.history;
  if (h[h.length - 1] === command) return h;
  return [...h, command].slice(-HISTORY_LIMIT);
}

export function trimEntries(entries: ConsoleEntry[]): ConsoleEntry[] {
  return entries.length > ENTRY_LIMIT ? entries.slice(-ENTRY_LIMIT) : entries;
}

export function toResult(res: CommandResponse): ConsoleResult {
  return { type: 'ok', response: res.response, isQuery: res.is_query, durationMs: res.duration_ms, error: res.error, truncated: Boolean(res.truncated) };
}
