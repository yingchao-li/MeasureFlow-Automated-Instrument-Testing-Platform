import type { Tone } from '@/lib/status';
import { cn } from './cn';
import { TONE_DOT } from './Badge';

export function ProgressBar({ value, tone = 'primary', label, className }: { value: number; tone?: Tone; label: string; className?: string }) {
  const pct = Math.max(0, Math.min(100, Math.round(value * 100)));
  return (
    <div role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} className={cn('h-1.5 w-full overflow-hidden rounded-full bg-border', className)}>
      <div className={cn('h-full rounded-full transition-[width] duration-150 ease-out', TONE_DOT[tone])} style={{ width: `${pct}%` }} />
    </div>
  );
}
