export interface NumberRule {
  min?: number;
  max?: number;
  unit?: string;
  integer?: boolean;
  label?: string;
}

export interface NumberCheck {
  value: number | null;
  error: string | null;
}

const fmt = (n: number) => String(Number(n.toPrecision(8)));

/** Validate a text field as a finite number inside [min, max]. Empty input is an error. */
export function checkNumber(text: string, rule: NumberRule = {}): NumberCheck {
  const trimmed = text.trim().replace(',', '.');
  if (trimmed === '') return { value: null, error: 'Enter a value' };
  if (!/^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/.test(trimmed)) return { value: null, error: 'Enter a number' };
  const value = Number(trimmed);
  if (!Number.isFinite(value)) return { value: null, error: 'Enter a finite number' };
  if (rule.integer && !Number.isInteger(value)) return { value: null, error: 'Must be a whole number' };
  const unit = rule.unit ? ` ${rule.unit}` : '';
  if (rule.min !== undefined && rule.max !== undefined && (value < rule.min || value > rule.max)) {
    return { value, error: `Must be between ${fmt(rule.min)} and ${fmt(rule.max)}${unit}` };
  }
  if (rule.min !== undefined && value < rule.min) return { value, error: `Must be at least ${fmt(rule.min)}${unit}` };
  if (rule.max !== undefined && value > rule.max) return { value, error: `Must be at most ${fmt(rule.max)}${unit}` };
  return { value, error: null };
}

export function numberToText(n: number | null | undefined): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return '';
  return String(Number(n.toPrecision(10)));
}
