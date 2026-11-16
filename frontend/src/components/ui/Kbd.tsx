import type { ReactNode } from 'react';

export function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="mono inline-flex h-[18px] min-w-[18px] items-center justify-center rounded border border-border-strong bg-sunken px-1 text-[11px] font-medium text-ink-2">{children}</kbd>
  );
}
