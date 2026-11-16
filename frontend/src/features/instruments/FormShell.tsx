import type { FormEvent, ReactNode } from 'react';
import { TriangleAlert } from 'lucide-react';
import { Button } from '@/components/ui';

interface FormShellProps {
  onSubmit: () => void;
  onRevert: () => void;
  dirty: boolean;
  submitting: boolean;
  /** Why Apply is unavailable (null when it is available). */
  blockedReason: string | null;
  formError: string | null;
  children: ReactNode;
  applyLabel?: string;
}

/** Shared footer (Revert / Apply) and form-level error banner for the instrument settings forms. */
export function FormShell({ onSubmit, onRevert, dirty, submitting, blockedReason, formError, children, applyLabel = 'Apply changes' }: FormShellProps) {
  const submit = (e: FormEvent) => {
    e.preventDefault();
    onSubmit();
  };
  return (
    <form onSubmit={submit} noValidate className="space-y-4">
      {formError && (
        <div role="alert" className="flex items-start gap-2 rounded border border-danger/40 bg-danger-soft px-3 py-2 text-xs text-danger-text">
          <TriangleAlert aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{formError}</span>
        </div>
      )}
      {children}
      <div className="flex items-center justify-between gap-3 border-t border-border pt-3">
        <p className="text-xs text-ink-3" aria-live="polite">
          {blockedReason ?? (dirty ? 'Unsaved changes' : 'Up to date with the instrument')}
        </p>
        <div className="flex items-center gap-2">
          <Button variant="ghost" onClick={onRevert} disabled={!dirty || submitting}>
            Revert
          </Button>
          <Button type="submit" variant="primary" loading={submitting} disabledReason={blockedReason ?? (!dirty ? 'No changes to apply' : null)}>
            {applyLabel}
          </Button>
        </div>
      </div>
    </form>
  );
}
