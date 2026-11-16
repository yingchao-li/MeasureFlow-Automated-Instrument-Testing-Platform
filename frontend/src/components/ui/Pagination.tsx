import { ChevronLeft, ChevronRight } from 'lucide-react';
import { IconButton } from './Button';

interface PaginationProps {
  page: number; // 0-based
  pageSize: number;
  total: number;
  onPage: (page: number) => void;
}

export function Pagination({ page, pageSize, total, onPage }: PaginationProps) {
  const pageCount = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : page * pageSize + 1;
  const to = Math.min(total, (page + 1) * pageSize);
  return (
    <nav aria-label="Pagination" className="flex items-center justify-between gap-3 border-t border-border px-4 py-2 text-xs text-ink-2">
      <p aria-live="polite" className="mono">
        {from}&ndash;{to} of {total}
      </p>
      <div className="flex items-center gap-1.5">
        <span className="mono text-ink-3">
          Page {Math.min(page + 1, pageCount)} / {pageCount}
        </span>
        <IconButton label="Previous page" variant="secondary" disabled={page <= 0} onClick={() => onPage(page - 1)}>
          <ChevronLeft aria-hidden className="h-4 w-4" />
        </IconButton>
        <IconButton label="Next page" variant="secondary" disabled={page >= pageCount - 1} onClick={() => onPage(page + 1)}>
          <ChevronRight aria-hidden className="h-4 w-4" />
        </IconButton>
      </div>
    </nav>
  );
}
