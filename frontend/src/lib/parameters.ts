import type { SequenceParameter } from '@/api/types';
import { checkNumber, numberToText } from './validation';

export function defaultValues(parameters: ReadonlyArray<SequenceParameter>): Record<string, string> {
  return Object.fromEntries(parameters.map((p) => [p.key, numberToText(p.default)]));
}

export interface ParameterValidation {
  /** Blocking errors by parameter key (null = valid). */
  errors: Record<string, string | null>;
  /** Non-blocking hints, e.g. lower limit above the upper limit. */
  warnings: Record<string, string | null>;
  /** Parsed numeric values for the valid keys. */
  numbers: Record<string, number>;
  invalidCount: number;
}

/** Tolerance parameters are limit values: `rms_min_v`, `thd_max_percent`, ... */
export function isToleranceParameter(p: Pick<SequenceParameter, 'key'>): boolean {
  return /(^|_)(min|max)(_|$)/.test(p.key);
}

/** Order limit parameters for display: grouped by quantity, lower limit before upper limit. */
export function orderTolerances<T extends Pick<SequenceParameter, 'key'>>(items: ReadonlyArray<T>): T[] {
  const stem = (k: string) => k.replace(/(^|_)(min|max)(_|$)/, '$1#$3');
  const rank = (k: string) => (/(^|_)min(_|$)/.test(k) ? 0 : 1);
  const firstSeen = new Map<string, number>();
  items.forEach((p, i) => {
    const st = stem(p.key);
    if (!firstSeen.has(st)) firstSeen.set(st, i);
  });
  return [...items].sort((a, b) => (firstSeen.get(stem(a.key)) as number) - (firstSeen.get(stem(b.key)) as number) || rank(a.key) - rank(b.key));
}

/** Validate every parameter against the declared [min, max] (INTERFACE 5.10) plus lower <= upper pairs. */
export function validateParameters(parameters: ReadonlyArray<SequenceParameter>, values: Record<string, string>): ParameterValidation {
  const errors: Record<string, string | null> = {};
  const warnings: Record<string, string | null> = {};
  const numbers: Record<string, number> = {};
  let invalidCount = 0;

  for (const p of parameters) {
    const check = checkNumber(values[p.key] ?? '', { min: p.min, max: p.max, unit: p.unit });
    errors[p.key] = check.error;
    if (check.error) invalidCount += 1;
    else if (check.value !== null) numbers[p.key] = check.value;
  }

  for (const p of parameters) {
    if (!p.key.includes('_min_')) continue;
    const partner = p.key.replace('_min_', '_max_');
    const lo = numbers[p.key];
    const hi = numbers[partner];
    if (lo !== undefined && hi !== undefined && lo > hi) {
      warnings[p.key] = 'Lower limit is above the upper limit; every measurement will FAIL';
      warnings[partner] = 'Upper limit is below the lower limit; every measurement will FAIL';
    }
  }
  return { errors, warnings, numbers, invalidCount };
}

export function isModified(p: SequenceParameter, text: string | undefined): boolean {
  if (text === undefined) return false;
  const n = Number(text.trim().replace(',', '.'));
  return !(Number.isFinite(n) && n === p.default);
}
