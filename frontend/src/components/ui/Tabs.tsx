import { useRef, type KeyboardEvent, type ReactNode } from 'react';
import { cn } from './cn';

export interface TabItem<T extends string> {
  id: T;
  label: string;
  icon?: ReactNode;
  count?: number | string;
}

interface TabsProps<T extends string> {
  tabs: ReadonlyArray<TabItem<T>>;
  value: T;
  onChange: (id: T) => void;
  label: string;
  className?: string;
  idPrefix?: string;
}

/** WAI-ARIA tabs with roving tabindex and arrow / Home / End keys. */
export function Tabs<T extends string>({ tabs, value, onChange, label, className, idPrefix = 'tab' }: TabsProps<T>) {
  const refs = useRef<Array<HTMLButtonElement | null>>([]);

  const onKeyDown = (e: KeyboardEvent<HTMLButtonElement>, index: number) => {
    let next = -1;
    if (e.key === 'ArrowRight') next = (index + 1) % tabs.length;
    else if (e.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
    else if (e.key === 'Home') next = 0;
    else if (e.key === 'End') next = tabs.length - 1;
    if (next >= 0) {
      e.preventDefault();
      const target = tabs[next];
      if (target) {
        onChange(target.id);
        refs.current[next]?.focus();
      }
    }
  };

  return (
    <div role="tablist" aria-label={label} className={cn('flex items-end gap-1 border-b border-border', className)}>
      {tabs.map((t, i) => {
        const active = t.id === value;
        return (
          <button
            key={t.id}
            ref={(el) => {
              refs.current[i] = el;
            }}
            role="tab"
            type="button"
            id={`${idPrefix}-${t.id}`}
            aria-selected={active}
            aria-controls={`${idPrefix}-panel-${t.id}`}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(t.id)}
            onKeyDown={(e) => onKeyDown(e, i)}
            className={cn(
              '-mb-px inline-flex h-9 items-center gap-1.5 whitespace-nowrap border-b-2 px-3 text-sm font-medium transition-colors',
              active ? 'border-primary text-ink' : 'border-transparent text-ink-2 hover:text-ink',
            )}
          >
            {t.icon}
            {t.label}
            {t.count !== undefined && <span className="mono rounded bg-sunken px-1 text-[11px] text-ink-2">{t.count}</span>}
          </button>
        );
      })}
    </div>
  );
}

export function TabPanel({ id, value, children, idPrefix = 'tab', className }: { id: string; value: string; children: ReactNode; idPrefix?: string; className?: string }) {
  if (id !== value) return null;
  return (
    <div role="tabpanel" id={`${idPrefix}-panel-${id}`} aria-labelledby={`${idPrefix}-${id}`} className={className}>
      {children}
    </div>
  );
}
