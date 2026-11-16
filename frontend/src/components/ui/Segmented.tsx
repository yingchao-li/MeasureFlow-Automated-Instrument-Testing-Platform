import { useRef, type KeyboardEvent, type ReactNode } from 'react';
import { cn } from './cn';

export interface SegmentOption<T extends string> {
  value: T;
  label: ReactNode;
  /** accessible name when the label is an icon */
  ariaLabel?: string;
}

interface SegmentedProps<T extends string> {
  options: ReadonlyArray<SegmentOption<T>>;
  value: T;
  onChange: (v: T) => void;
  label: string;
  size?: 'sm' | 'md';
  className?: string;
}

/** Single-choice radio group rendered as a segmented control. Arrow keys move the selection. */
export function Segmented<T extends string>({ options, value, onChange, label, size = 'md', className }: SegmentedProps<T>) {
  const refs = useRef<Array<HTMLButtonElement | null>>([]);

  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>, i: number) => {
    let next = -1;
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') next = (i + 1) % options.length;
    else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') next = (i - 1 + options.length) % options.length;
    if (next >= 0) {
      e.preventDefault();
      const o = options[next];
      if (o) {
        onChange(o.value);
        refs.current[next]?.focus();
      }
    }
  };

  return (
    <div role="radiogroup" aria-label={label} className={cn('inline-flex rounded border border-border-strong bg-sunken p-0.5', className)}>
      {options.map((o, i) => {
        const active = o.value === value;
        return (
          <button
            key={o.value}
            ref={(el) => {
              refs.current[i] = el;
            }}
            type="button"
            role="radio"
            aria-checked={active}
            aria-label={o.ariaLabel}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(o.value)}
            onKeyDown={(e) => onKeyDown(e, i)}
            className={cn(
              'inline-flex items-center justify-center gap-1 whitespace-nowrap rounded-sm px-2.5 font-medium transition-colors',
              size === 'sm' ? 'h-6 text-xs' : 'h-7 text-sm',
              active ? 'bg-surface text-ink shadow-sm' : 'text-ink-2 hover:text-ink',
            )}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}
