import type { SequenceParameter } from '@/api/types';
import { defaultValues, isModified, isToleranceParameter, orderTolerances, validateParameters } from './parameters';
import { checkNumber } from './validation';

const params: SequenceParameter[] = [
  { key: 'frequency_hz', label: 'Frequency', unit: 'Hz', default: 1000, min: 20, max: 20000 },
  { key: 'gain_min_db', label: 'Gain lower limit', unit: 'dB', default: 19, min: -20, max: 60 },
  { key: 'gain_max_db', label: 'Gain upper limit', unit: 'dB', default: 21, min: -20, max: 60 },
  { key: 'thd_max_percent', label: 'THD upper limit', unit: '%', default: 1, min: 0, max: 100 },
];

describe('checkNumber', () => {
  it('accepts plain, decimal-comma and exponent input', () => {
    expect(checkNumber('1000').value).toBe(1000);
    expect(checkNumber('0,05').value).toBe(0.05);
    expect(checkNumber('1e3').value).toBe(1000);
  });
  it.each([
    ['', 'Enter a value'],
    ['abc', 'Enter a number'],
    ['12abc', 'Enter a number'],
    ['NaN', 'Enter a number'],
    ['Infinity', 'Enter a number'],
  ])('rejects %j', (text, message) => {
    expect(checkNumber(text).error).toBe(message);
  });
  it('reports the allowed range including the unit', () => {
    expect(checkNumber('5', { min: 20, max: 20000, unit: 'Hz' }).error).toBe('Must be between 20 and 20000 Hz');
    expect(checkNumber('5', { min: 20, unit: 'Hz' }).error).toBe('Must be at least 20 Hz');
    expect(checkNumber('50', { max: 20 }).error).toBe('Must be at most 20');
    expect(checkNumber('2.5', { integer: true }).error).toBe('Must be a whole number');
  });
  it('treats the bounds as inclusive', () => {
    expect(checkNumber('20', { min: 20, max: 20000 }).error).toBeNull();
    expect(checkNumber('20000', { min: 20, max: 20000 }).error).toBeNull();
  });
});

describe('validateParameters', () => {
  it('is valid for the defaults and returns numbers for the request body', () => {
    const v = validateParameters(params, defaultValues(params));
    expect(v.invalidCount).toBe(0);
    expect(v.numbers).toEqual({ frequency_hz: 1000, gain_min_db: 19, gain_max_db: 21, thd_max_percent: 1 });
  });
  it('flags out-of-range and non-numeric values and counts them', () => {
    const v = validateParameters(params, { ...defaultValues(params), frequency_hz: '5', thd_max_percent: 'x' });
    expect(v.invalidCount).toBe(2);
    expect(v.errors['frequency_hz']).toContain('between 20 and 20000');
    expect(v.errors['thd_max_percent']).toBe('Enter a number');
    expect(v.numbers['frequency_hz']).toBeUndefined();
  });
  it('warns (without blocking) when a lower limit exceeds its upper limit', () => {
    const v = validateParameters(params, { ...defaultValues(params), gain_min_db: '25' });
    expect(v.invalidCount).toBe(0);
    expect(v.warnings['gain_min_db']).toMatch(/above the upper limit/);
    expect(v.warnings['gain_max_db']).toMatch(/below the lower limit/);
  });
  it('separates stimulus from tolerance parameters and detects modifications', () => {
    expect(params.map(isToleranceParameter)).toEqual([false, true, true, true]);
    expect(isModified(params[0] as SequenceParameter, '1000')).toBe(false);
    expect(isModified(params[0] as SequenceParameter, '1000.0')).toBe(false);
    expect(isModified(params[0] as SequenceParameter, '500')).toBe(true);
  });
});

describe('orderTolerances', () => {
  it('groups limits by quantity with the lower limit first', () => {
    const keys = orderTolerances([{ key: 'gain_max_db' }, { key: 'gain_min_db' }, { key: 'rms_max_v' }, { key: 'rms_min_v' }, { key: 'thd_max_percent' }]).map((p) => p.key);
    expect(keys).toEqual(['gain_min_db', 'gain_max_db', 'rms_min_v', 'rms_max_v', 'thd_max_percent']);
  });
});
