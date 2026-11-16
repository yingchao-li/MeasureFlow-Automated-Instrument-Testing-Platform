import type { MeasurementKind, TaskLimits } from '@/api/types';

export const EM_DASH = '—';

export function formatNumber(value: number | null | undefined, decimals = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return EM_DASH;
  if (!Number.isFinite(value)) return value > 0 ? 'INF' : '-INF';
  return value.toFixed(decimals);
}

/** Decimal places per measurement kind (keeps columns aligned and honest about resolution). */
export const KIND_DECIMALS: Record<string, number> = {
  rms: 4,
  gain: 2,
  thd: 3,
  snr: 1,
  noise_floor: 1,
  freq_sweep: 2,
};

export const KIND_LABEL: Record<string, string> = {
  rms: 'RMS',
  gain: 'Gain',
  thd: 'THD',
  snr: 'SNR',
  noise_floor: 'Noise floor',
  freq_sweep: 'Freq. sweep',
};

export function kindLabel(kind: string): string {
  return KIND_LABEL[kind] ?? kind;
}

export function formatKindValue(kind: string, value: number | null | undefined): string {
  return formatNumber(value, KIND_DECIMALS[kind] ?? 3);
}

/** "19.98 dB" style measured value. */
export function formatMeasured(kind: MeasurementKind | string, m: { value: number; unit: string } | null | undefined): string {
  if (!m) return EM_DASH;
  return `${formatKindValue(kind, m.value)} ${m.unit}`.trim();
}

/** Compact human limits: "19 … 21 dB", "≤ 1 %", "≥ 60 dB". */
export function formatLimits(limits: TaskLimits | null | undefined): string {
  if (!limits) return EM_DASH;
  const fmt = (n: number) => String(Number(n.toPrecision(6)));
  const { min, max, unit } = limits;
  const u = unit ? ` ${unit}` : '';
  if (min !== null && max !== null) return `${fmt(min)} … ${fmt(max)}${u}`;
  if (max !== null) return `≤ ${fmt(max)}${u}`;
  if (min !== null) return `≥ ${fmt(min)}${u}`;
  return EM_DASH;
}

export function formatDurationMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return EM_DASH;
  if (ms < 1) return `${ms.toFixed(2)} ms`;
  if (ms < 100) return `${ms.toFixed(1)} ms`;
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)} s`;
  const m = Math.floor(s / 60);
  const rem = Math.round(s - m * 60);
  return `${m} min ${String(rem).padStart(2, '0')} s`;
}

export function formatUptime(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return EM_DASH;
  const s = Math.floor(seconds);
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (d > 0) return `${d} d ${h} h`;
  if (h > 0) return `${h} h ${String(m).padStart(2, '0')} min`;
  if (m > 0) return `${m} min ${String(sec).padStart(2, '0')} s`;
  return `${sec} s`;
}

const pad = (n: number, w = 2) => String(n).padStart(w, '0');

function toDate(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

/** HH:MM:SS (local time). */
export function formatTime(iso: string | null | undefined): string {
  const d = toDate(iso);
  return d ? `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}` : EM_DASH;
}

/** HH:MM:SS.mmm (local time). */
export function formatTimeMs(iso: string | null | undefined): string {
  const d = toDate(iso);
  return d ? `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}.${pad(d.getMilliseconds(), 3)}` : EM_DASH;
}

/** YYYY-MM-DD HH:MM (local time). */
export function formatDateTime(iso: string | null | undefined): string {
  const d = toDate(iso);
  return d ? `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}` : EM_DASH;
}

export function formatDate(iso: string | null | undefined): string {
  const d = toDate(iso);
  return d ? `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` : EM_DASH;
}

/** "4 s ago", "3 min ago", "2 h ago", then the date. */
export function relativeTime(iso: string | number | null | undefined, now: number = Date.now()): string {
  if (iso === null || iso === undefined) return EM_DASH;
  const t = typeof iso === 'number' ? iso : new Date(iso).getTime();
  if (Number.isNaN(t)) return EM_DASH;
  const diff = Math.max(0, Math.round((now - t) / 1000));
  if (diff < 5) return 'just now';
  if (diff < 60) return `${diff} s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`;
  return typeof iso === 'number' ? formatDateTime(new Date(iso).toISOString()) : formatDateTime(iso);
}

export function formatPercent(fraction: number | null | undefined, decimals = 1): string {
  if (fraction === null || fraction === undefined || !Number.isFinite(fraction)) return EM_DASH;
  return `${(fraction * 100).toFixed(decimals)} %`;
}

/** Frequency with kHz switch: 1000 -> "1 kHz", 250 -> "250 Hz". */
export function formatHz(hz: number | null | undefined): string {
  if (hz === null || hz === undefined || !Number.isFinite(hz)) return EM_DASH;
  if (Math.abs(hz) >= 1000) return `${Number((hz / 1000).toPrecision(4))} kHz`;
  return `${Number(hz.toPrecision(5))} Hz`;
}

/** Axis tick label for a frequency in Hz: 20, 200, 2k, 20k. */
export function formatHzTick(hz: number): string {
  if (hz >= 1000) return `${Number((hz / 1000).toPrecision(3))}k`;
  return String(Number(hz.toPrecision(3)));
}

export function plural(n: number, singular: string, pluralForm = `${singular}s`): string {
  return `${n} ${n === 1 ? singular : pluralForm}`;
}
