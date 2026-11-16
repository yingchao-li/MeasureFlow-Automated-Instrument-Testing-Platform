/** Axis helpers shared by the chart wrappers. */

export function niceStep(range: number, targetTicks = 5): number {
  if (!(range > 0)) return 1;
  const raw = range / targetTicks;
  const pow = Math.pow(10, Math.floor(Math.log10(raw)));
  const f = raw / pow;
  const eps = 1e-9;
  const nice = f <= 1 + eps ? 1 : f <= 2 + eps ? 2 : f <= 5 + eps ? 5 : 10;
  return nice * pow;
}

/** Round [min, max] outwards to "nice" bounds. Handles degenerate ranges. */
export function niceDomain(min: number, max: number, targetTicks = 5): [number, number] {
  if (!Number.isFinite(min) || !Number.isFinite(max)) return [0, 1];
  if (min === max) {
    const pad = Math.abs(min) > 0 ? Math.abs(min) * 0.1 : 1;
    return [min - pad, max + pad];
  }
  const step = niceStep(max - min, targetTicks);
  return [Math.floor(min / step) * step, Math.ceil(max / step) * step];
}

export function niceTicks(min: number, max: number, targetTicks = 5): number[] {
  const [lo, hi] = niceDomain(min, max, targetTicks);
  const step = niceStep(hi - lo, targetTicks);
  const out: number[] = [];
  const n = Math.round((hi - lo) / step);
  for (let i = 0; i <= n; i++) {
    const v = lo + i * step;
    out.push(Math.abs(v) < step * 1e-9 ? 0 : Number(v.toPrecision(12)));
  }
  return out;
}

/** Decimal places needed to print every tick of an evenly spaced tick list without duplicates. */
export function tickDecimals(ticks: ReadonlyArray<number>): number {
  if (ticks.length < 2) return 2;
  const step = Math.abs((ticks[1] as number) - (ticks[0] as number));
  if (!(step > 0)) return 2;
  return Math.min(8, Math.max(0, Math.ceil(-Math.log10(step) - 1e-9)));
}

/** 1-2-5 ticks inside [lo, hi] for a logarithmic frequency axis. */
export function logTicks(lo: number, hi: number): number[] {
  const out: number[] = [];
  if (!(lo > 0) || !(hi > lo)) return out;
  const startDecade = Math.floor(Math.log10(lo));
  const endDecade = Math.ceil(Math.log10(hi));
  for (let d = startDecade; d <= endDecade; d++) {
    for (const m of [1, 2, 5]) {
      const v = m * Math.pow(10, d);
      if (v >= lo * 0.999 && v <= hi * 1.001) out.push(v);
    }
  }
  // keep the axis readable: with many decades only label the powers of ten
  if (out.length > 12) {
    return out.filter((v) => {
      const mantissa = v / Math.pow(10, Math.floor(Math.log10(v) + 1e-9));
      return Math.abs(mantissa - 1) < 1e-9;
    });
  }
  return out;
}

/** Min / max of the finite values in an array (null when there are none). */
export function extent(values: ReadonlyArray<number>): [number, number] | null {
  let lo = Infinity;
  let hi = -Infinity;
  for (const v of values) {
    if (Number.isFinite(v)) {
      if (v < lo) lo = v;
      if (v > hi) hi = v;
    }
  }
  return lo <= hi ? [lo, hi] : null;
}
