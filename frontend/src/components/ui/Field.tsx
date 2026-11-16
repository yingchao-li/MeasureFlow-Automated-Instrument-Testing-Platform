import { forwardRef, useId, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes } from 'react';
import { AlertCircle, ChevronDown } from 'lucide-react';
import { cn } from './cn';

interface FieldShellProps {
  id: string;
  label: ReactNode;
  hint?: ReactNode;
  error?: string | null;
  warning?: string | null;
  /** Element shown at the right end of the label row (e.g. a reset button). */
  labelAction?: ReactNode;
  className?: string;
  children: ReactNode;
  hideLabel?: boolean;
}

/** Label + control + hint / error message with correct aria wiring. */
export function FieldShell({ id, label, hint, error, warning, labelAction, className, children, hideLabel }: FieldShellProps) {
  return (
    <div className={cn('min-w-0', className)}>
      <div className={cn('mb-1 flex items-center justify-between gap-2', hideLabel && 'sr-only')}>
        <label htmlFor={id} className="truncate text-xs font-medium text-ink-2">
          {label}
        </label>
        {labelAction}
      </div>
      {children}
      {error ? (
        <p id={`${id}-msg`} className="mt-1 flex items-start gap-1 text-xs text-danger-text">
          <AlertCircle aria-hidden className="mt-0.5 h-3 w-3 shrink-0" />
          <span>{error}</span>
        </p>
      ) : warning ? (
        <p id={`${id}-msg`} className="mt-1 text-xs text-warn-text">
          {warning}
        </p>
      ) : hint ? (
        <p id={`${id}-msg`} className="mt-1 text-xs text-ink-3">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

const CONTROL =
  'w-full min-w-0 rounded border bg-surface text-sm text-ink placeholder:text-ink-3 transition-colors disabled:cursor-not-allowed disabled:bg-sunken disabled:text-ink-3';

interface TextFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'onChange' | 'value' | 'id'> {
  id?: string;
  label: ReactNode;
  value: string;
  onChange: (value: string) => void;
  unit?: string;
  hint?: ReactNode;
  error?: string | null;
  warning?: string | null;
  labelAction?: ReactNode;
  mono?: boolean;
  hideLabel?: boolean;
  wrapperClassName?: string;
}

/** Text / number input. Numeric values stay strings in form state (see lib/validation.checkNumber). */
export const TextField = forwardRef<HTMLInputElement, TextFieldProps>(function TextField(
  { id, label, value, onChange, unit, hint, error, warning, labelAction, mono, hideLabel, className, wrapperClassName, ...rest },
  ref,
) {
  const auto = useId();
  const fid = id ?? auto;
  const described = error || warning || hint ? `${fid}-msg` : undefined;
  return (
    <FieldShell id={fid} label={label} hint={hint} error={error} warning={warning} labelAction={labelAction} className={wrapperClassName} hideLabel={hideLabel}>
      <div
        className={cn(
          'flex items-center rounded border bg-surface transition-colors focus-within:outline focus-within:outline-2 focus-within:outline-offset-1 focus-within:outline-ring',
          error ? 'border-danger' : 'border-control hover:border-ink-3',
          rest.disabled && 'bg-sunken',
        )}
      >
        <input
          ref={ref}
          id={fid}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-invalid={error ? true : undefined}
          aria-describedby={described}
          className={cn(CONTROL, 'h-[30px] border-0 bg-transparent px-2.5 outline-none focus-visible:outline-none', mono && 'mono', unit && 'pr-1', className)}
          {...rest}
        />
        {unit && <span className="mono pointer-events-none select-none whitespace-nowrap pr-2.5 text-xs text-ink-3">{unit}</span>}
      </div>
    </FieldShell>
  );
});

interface SelectFieldProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'onChange' | 'value' | 'id'> {
  id?: string;
  label: ReactNode;
  value: string;
  onChange: (value: string) => void;
  options: ReadonlyArray<{ value: string; label: string; disabled?: boolean }>;
  hint?: ReactNode;
  error?: string | null;
  hideLabel?: boolean;
  wrapperClassName?: string;
}

export const SelectField = forwardRef<HTMLSelectElement, SelectFieldProps>(function SelectField(
  { id, label, value, onChange, options, hint, error, hideLabel, className, wrapperClassName, ...rest },
  ref,
) {
  const auto = useId();
  const fid = id ?? auto;
  return (
    <FieldShell id={fid} label={label} hint={hint} error={error} className={wrapperClassName} hideLabel={hideLabel}>
      <div className="relative">
        <select
          ref={ref}
          id={fid}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-invalid={error ? true : undefined}
          aria-describedby={error || hint ? `${fid}-msg` : undefined}
          className={cn(CONTROL, 'h-8 appearance-none pl-2.5 pr-8', error ? 'border-danger' : 'border-control hover:border-ink-3', className)}
          {...rest}
        >
          {options.map((o) => (
            <option key={o.value} value={o.value} disabled={o.disabled}>
              {o.label}
            </option>
          ))}
        </select>
        <ChevronDown aria-hidden className="pointer-events-none absolute right-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-3" />
      </div>
    </FieldShell>
  );
});

interface SwitchProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  disabled?: boolean;
  busy?: boolean;
  id?: string;
}

/** role=switch toggle. `label` is the accessible name (render a visible label next to it). */
export function Switch({ checked, onChange, label, disabled, busy, id }: SwitchProps) {
  return (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      aria-busy={busy || undefined}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        'relative inline-flex h-[18px] w-8 shrink-0 items-center rounded-full border transition-colors disabled:cursor-not-allowed disabled:opacity-50',
        checked ? 'border-primary bg-primary' : 'border-control bg-sunken',
      )}
    >
      <span
        aria-hidden
        className={cn('inline-block h-3 w-3 rounded-full transition-transform duration-150', checked ? 'translate-x-[16px] bg-primary-fg' : 'translate-x-[2px] bg-control')}
      />
    </button>
  );
}
