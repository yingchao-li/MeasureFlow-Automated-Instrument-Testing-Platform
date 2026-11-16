import { useId, type ReactNode } from 'react';
import { cn } from './cn';

interface PanelProps {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  /** Remove body padding (tables, charts that bleed to the edge). */
  flush?: boolean;
  className?: string;
  bodyClassName?: string;
  /** Accessible name when there is no visible title. */
  label?: string;
}

/** Bordered surface with an optional header. Radius 8, hairline border, no gradient. */
export function Panel({ title, description, actions, children, flush, className, bodyClassName, label }: PanelProps) {
  const id = useId();
  return (
    <section aria-labelledby={title ? id : undefined} aria-label={title ? undefined : label} className={cn('flex min-w-0 flex-col rounded-lg border border-border bg-surface shadow-sm', className)}>
      {(title || actions) && (
        <header className="flex min-h-[44px] items-center justify-between gap-3 border-b border-border px-4 py-2">
          <div className="flex min-w-0 items-baseline gap-2">
            <h2 id={id} className="truncate text-sm font-semibold text-ink">
              {title}
            </h2>
            {description && <p className="truncate text-xs text-ink-3">{description}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cn('min-h-0 flex-1', !flush && 'p-4', bodyClassName)}>{children}</div>
    </section>
  );
}
