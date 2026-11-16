import { Monitor, Moon, Sun } from 'lucide-react';
import { useTheme } from '@/context/ThemeContext';
import type { ThemeMode } from '@/lib/theme';
import { IconButton, Segmented } from '@/components/ui';

const NEXT: Record<ThemeMode, ThemeMode> = { light: 'dark', dark: 'system', system: 'light' };
const LABEL: Record<ThemeMode, string> = { light: 'Light', dark: 'Dark', system: 'System' };

/** Three-way theme switch; collapsed variant cycles light > dark > system. Persisted by ThemeProvider. */
export function ThemeToggle({ collapsed }: { collapsed?: boolean }) {
  const { mode, setMode } = useTheme();
  if (collapsed) {
    const Icon = mode === 'light' ? Sun : mode === 'dark' ? Moon : Monitor;
    return (
      <IconButton label={`Theme: ${LABEL[mode]} (click for ${LABEL[NEXT[mode]]})`} tooltipSide="right" onClick={() => setMode(NEXT[mode])}>
        <Icon aria-hidden className="h-4 w-4" />
      </IconButton>
    );
  }
  return (
    <Segmented<ThemeMode>
      label="Colour theme"
      size="sm"
      value={mode}
      onChange={setMode}
      options={[
        { value: 'light', ariaLabel: 'Light theme', label: <Sun aria-hidden className="h-3.5 w-3.5" /> },
        { value: 'dark', ariaLabel: 'Dark theme', label: <Moon aria-hidden className="h-3.5 w-3.5" /> },
        { value: 'system', ariaLabel: 'System theme', label: <Monitor aria-hidden className="h-3.5 w-3.5" /> },
      ]}
    />
  );
}
