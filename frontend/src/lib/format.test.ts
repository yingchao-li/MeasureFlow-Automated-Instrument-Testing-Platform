import { EM_DASH, formatDurationMs, formatHz, formatHzTick, formatKindValue, formatLimits, formatMeasured, formatNumber, formatPercent, formatUptime, relativeTime } from './format';

describe('format helpers', () => {
  it('formats numbers without inventing values', () => {
    expect(formatNumber(19.9764, 2)).toBe('19.98');
    expect(formatNumber(null)).toBe(EM_DASH);
    expect(formatNumber(undefined)).toBe(EM_DASH);
    expect(formatNumber(NaN)).toBe(EM_DASH);
    expect(formatNumber(Infinity)).toBe('INF');
  });
  it('uses a fixed number of decimals per measurement kind', () => {
    expect(formatKindValue('thd', 0.12345)).toBe('0.123');
    expect(formatKindValue('rms', 0.35312)).toBe('0.3531');
    expect(formatKindValue('noise_floor', -80.94)).toBe('-80.9');
    expect(formatMeasured('gain', { value: 20, unit: 'dB' })).toBe('20.00 dB');
    expect(formatMeasured('gain', null)).toBe(EM_DASH);
  });
  it('writes limits with open bounds', () => {
    expect(formatLimits({ min: 19, max: 21, unit: 'dB' })).toBe('19 … 21 dB');
    expect(formatLimits({ min: null, max: 1, unit: '%' })).toBe('≤ 1 %');
    expect(formatLimits({ min: 60, max: null, unit: 'dB' })).toBe('≥ 60 dB');
    expect(formatLimits({ min: null, max: null, unit: 'dB' })).toBe(EM_DASH);
    expect(formatLimits(null)).toBe(EM_DASH);
  });
  it('formats durations, uptime, frequencies and percentages', () => {
    expect(formatDurationMs(0.5)).toBe('0.50 ms');
    expect(formatDurationMs(14.23)).toBe('14.2 ms');
    expect(formatDurationMs(250)).toBe('250 ms');
    expect(formatDurationMs(5000)).toBe('5.0 s');
    expect(formatDurationMs(125000)).toBe('2 min 05 s');
    expect(formatUptime(12.3)).toBe('12 s');
    expect(formatUptime(3725)).toBe('1 h 02 min');
    expect(formatHz(1000)).toBe('1 kHz');
    expect(formatHz(250)).toBe('250 Hz');
    expect(formatHzTick(20000)).toBe('20k');
    expect(formatHzTick(200)).toBe('200');
    expect(formatPercent(0.882, 1)).toBe('88.2 %');
  });
  it('relative times', () => {
    const now = Date.parse('2026-11-16T12:00:00Z');
    expect(relativeTime('2026-11-16T11:59:58Z', now)).toBe('just now');
    expect(relativeTime('2026-11-16T11:59:30Z', now)).toBe('30 s ago');
    expect(relativeTime('2026-11-16T11:50:00Z', now)).toBe('10 min ago');
    expect(relativeTime(null)).toBe(EM_DASH);
  });
});
