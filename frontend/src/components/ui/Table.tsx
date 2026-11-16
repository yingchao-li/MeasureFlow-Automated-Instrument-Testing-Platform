import type { HTMLAttributes, ReactNode, Ref, TdHTMLAttributes, ThHTMLAttributes, UIEventHandler } from 'react';
import { cn } from './cn';

/** Scroll container; the header row sticks to its top. */
export function TableContainer({
  children,
  className,
  maxHeight,
  label,
  scrollRef,
  onScroll,
}: {
  children: ReactNode;
  className?: string;
  maxHeight?: number | string;
  label?: string;
  scrollRef?: Ref<HTMLDivElement>;
  onScroll?: UIEventHandler<HTMLDivElement>;
}) {
  return (
    <div
      ref={scrollRef}
      onScroll={onScroll}
      role={label ? 'region' : undefined}
      aria-label={label}
      tabIndex={label ? 0 : undefined}
      className={cn('overflow-auto', className)}
      style={maxHeight !== undefined ? { maxHeight } : undefined}
    >
      {children}
    </div>
  );
}

export function Table({ children, className, ...rest }: HTMLAttributes<HTMLTableElement>) {
  return (
    <table className={cn('w-full text-sm', className)} {...rest}>
      {children}
    </table>
  );
}

interface ThProps extends ThHTMLAttributes<HTMLTableCellElement> {
  numeric?: boolean;
}
export function Th({ numeric, className, children, ...rest }: ThProps) {
  return (
    <th
      scope="col"
      className={cn(
        'sticky top-0 z-10 h-8 whitespace-nowrap border-b border-border bg-sunken px-3 text-2xs font-medium uppercase tracking-[0.05em] text-ink-3',
        numeric ? 'text-right' : 'text-left',
        className,
      )}
      {...rest}
    >
      {children}
    </th>
  );
}

interface TdProps extends TdHTMLAttributes<HTMLTableCellElement> {
  numeric?: boolean;
  mono?: boolean;
}
export function Td({ numeric, mono, className, children, ...rest }: TdProps) {
  return (
    <td
      className={cn('h-9 border-b border-border px-3 align-middle', numeric && 'text-right', (numeric || mono) && 'mono text-[13px]', className)}
      {...rest}
    >
      {children}
    </td>
  );
}

interface TrProps extends HTMLAttributes<HTMLTableRowElement> {
  selected?: boolean;
  interactive?: boolean;
}
export function Tr({ selected, interactive, className, children, ...rest }: TrProps) {
  return (
    <tr
      className={cn('transition-colors hover:bg-hover [&:last-child>td]:border-b-0', interactive && 'cursor-pointer', selected && 'bg-primary-soft hover:bg-primary-soft', className)}
      {...rest}
    >
      {children}
    </tr>
  );
}
