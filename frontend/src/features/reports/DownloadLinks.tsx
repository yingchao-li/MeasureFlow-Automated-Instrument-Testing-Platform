import { Download, ExternalLink } from 'lucide-react';
import { reportUrl } from '@/api';
import { ButtonLink, cn } from '@/components/ui';

interface DownloadLinksProps {
  runId: string;
  /** `buttons` for the drawer, `inline` for table rows */
  variant?: 'buttons' | 'inline';
  className?: string;
}

/** CSV / HTML / PDF downloads are plain `<a download>`; "Open HTML" opens the report in a new tab. */
export function DownloadLinks({ runId, variant = 'inline', className }: DownloadLinksProps) {
  if (variant === 'buttons') {
    return (
      <div className={cn('flex flex-wrap items-center gap-2', className)}>
        {(['csv', 'html', 'pdf'] as const).map((ext) => (
          <ButtonLink key={ext} size="sm" href={reportUrl(runId, ext)} download={`${runId}.${ext}`} icon={<Download aria-hidden className="h-3.5 w-3.5" />} aria-label={`Download ${ext.toUpperCase()} report for ${runId}`}>
            {ext.toUpperCase()}
          </ButtonLink>
        ))}
        <ButtonLink size="sm" variant="ghost" href={reportUrl(runId, 'html')} target="_blank" rel="noopener noreferrer" icon={<ExternalLink aria-hidden className="h-3.5 w-3.5" />}>
          Open HTML
        </ButtonLink>
      </div>
    );
  }
  return (
    <div className={cn('flex items-center justify-end gap-1', className)} onClick={(e) => e.stopPropagation()}>
      {(['csv', 'html', 'pdf'] as const).map((ext) => (
        <a
          key={ext}
          href={reportUrl(runId, ext)}
          download={`${runId}.${ext}`}
          aria-label={`Download ${ext.toUpperCase()} report for ${runId}`}
          className="mono rounded border border-border-strong px-1.5 py-0.5 text-[10.5px] font-medium uppercase text-ink-2 transition-colors hover:bg-hover hover:text-ink"
        >
          {ext}
        </a>
      ))}
      <a
        href={reportUrl(runId, 'html')}
        target="_blank"
        rel="noopener noreferrer"
        aria-label={`Open HTML report for ${runId} in a new tab`}
        className="ml-0.5 rounded p-1 text-ink-3 transition-colors hover:bg-hover hover:text-ink"
      >
        <ExternalLink aria-hidden className="h-3.5 w-3.5" />
      </a>
    </div>
  );
}
