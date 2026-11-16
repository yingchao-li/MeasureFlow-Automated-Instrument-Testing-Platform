import type { ReactNode } from 'react';
import { Ban, Check, CircleDashed, Loader2, TriangleAlert, X, type LucideIcon } from 'lucide-react';
import type { Tone } from '@/lib/status';
import { RUN_STATUS } from '@/lib/status';
import { cn } from './cn';

const TONE: Record<Tone, string> = {
  success: 'bg-success-soft text-success-text',
  warn: 'bg-warn-soft text-warn-text',
  danger: 'bg-danger-soft text-danger-text',
  neutral: 'bg-neutral-soft text-neutral-text',
  info: 'bg-info-soft text-info-text',
  primary: 'bg-primary-soft text-primary-text',
};

const DOT: Record<Tone, string> = {
  success: 'bg-success',
  warn: 'bg-warn',
  danger: 'bg-danger',
  neutral: 'bg-neutral',
  info: 'bg-info',
  primary: 'bg-primary',
};

export function Badge({ tone = 'neutral', icon, children, className, title }: { tone?: Tone; icon?: ReactNode; children: ReactNode; className?: string; title?: string }) {
  return (
    <span
      title={title}
      className={cn('inline-flex h-5 shrink-0 items-center gap-1 whitespace-nowrap rounded px-1.5 text-2xs font-semibold tracking-wide', TONE[tone], className)}
    >
      {icon}
      {children}
    </span>
  );
}

const STATUS_ICON: Record<string, LucideIcon> = {
  PASS: Check,
  FAIL: X,
  ERROR: TriangleAlert,
  CANCELLED: Ban,
  RUNNING: Loader2,
  PENDING: CircleDashed,
};

/** Run / task status. Shape (icon) and text carry the meaning in addition to colour. */
export function StatusBadge({ status, className }: { status: string; className?: string }) {
  const meta = RUN_STATUS[status as keyof typeof RUN_STATUS] ?? { tone: 'neutral' as Tone, label: status };
  const Icon = STATUS_ICON[status] ?? CircleDashed;
  return (
    <Badge tone={meta.tone} className={cn('uppercase', className)} icon={<Icon aria-hidden className={cn('h-3 w-3', status === 'RUNNING' && 'animate-spin')} strokeWidth={2.5} />}>
      {meta.label}
    </Badge>
  );
}

export function StatusDot({ tone = 'neutral', pulse, className, label }: { tone?: Tone; pulse?: boolean; className?: string; label?: string }) {
  return (
    <span className={cn('relative inline-flex h-2 w-2 shrink-0', className)}>
      {pulse && <span aria-hidden className={cn('absolute inset-0 animate-ping rounded-full opacity-50', DOT[tone])} />}
      <span aria-hidden={label ? undefined : true} className={cn('relative inline-block h-2 w-2 rounded-full', DOT[tone])} />
      {label && <span className="sr-only">{label}</span>}
    </span>
  );
}

export { DOT as TONE_DOT, TONE as TONE_SOFT };
