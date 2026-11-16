import { Dialog, Kbd } from '@/components/ui';

const SHORTCUTS: Array<{ keys: string[]; action: string }> = [
  { keys: ['/'], action: 'Focus the SCPI console input (Instruments page)' },
  { keys: ['↑', '↓'], action: 'Command history in the SCPI console' },
  { keys: ['Enter'], action: 'Send command / submit form' },
  { keys: ['Esc'], action: 'Close dialog or drawer' },
  { keys: ['?'], action: 'Show this list' },
  { keys: ['Tab'], action: 'Move focus; every control is reachable by keyboard' },
];

export function ShortcutsDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Dialog open={open} onClose={onClose} title="Keyboard shortcuts" description="MeasureFlow is fully operable without a mouse.">
      <ul className="divide-y divide-border px-5">
        {SHORTCUTS.map((s) => (
          <li key={s.action} className="flex items-center justify-between gap-4 py-2.5">
            <span className="text-sm text-ink-2">{s.action}</span>
            <span className="flex shrink-0 gap-1">
              {s.keys.map((k) => (
                <Kbd key={k}>{k}</Kbd>
              ))}
            </span>
          </li>
        ))}
      </ul>
    </Dialog>
  );
}
