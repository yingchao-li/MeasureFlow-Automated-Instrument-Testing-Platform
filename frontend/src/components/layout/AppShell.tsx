import { useCallback, useEffect, useState } from 'react';
import { Outlet } from 'react-router-dom';
import { useHotkey } from '@/hooks/useHotkey';
import { OfflineBanner } from './OfflineBanner';
import { ShortcutsDialog } from './ShortcutsDialog';
import { Sidebar } from './Sidebar';

const SIDEBAR_KEY = 'mf-sidebar-collapsed';

function initialCollapsed(): boolean {
  try {
    const v = localStorage.getItem(SIDEBAR_KEY);
    if (v === '1') return true;
    if (v === '0') return false;
  } catch {
    /* ignore */
  }
  return typeof window !== 'undefined' && window.innerWidth < 1180;
}

export function AppShell() {
  const [collapsed, setCollapsed] = useState(initialCollapsed);
  const [shortcuts, setShortcuts] = useState(false);

  const toggle = useCallback(() => {
    setCollapsed((c) => {
      try {
        localStorage.setItem(SIDEBAR_KEY, c ? '0' : '1');
      } catch {
        /* ignore */
      }
      return !c;
    });
  }, []);

  useHotkey('?', () => setShortcuts(true));
  useEffect(() => {
    document.title = 'MeasureFlow';
  }, []);

  return (
    <div className="flex h-full">
      <a href="#main" className="sr-only-focusable fixed left-3 top-3 z-[80] rounded bg-primary px-3 py-1.5 text-sm font-medium text-primary-fg">
        Skip to content
      </a>
      <Sidebar collapsed={collapsed} onToggle={toggle} onShowShortcuts={() => setShortcuts(true)} />
      <div className="flex min-w-0 flex-1 flex-col">
        <OfflineBanner />
        <main id="main" tabIndex={-1} className="relative min-h-0 flex-1 overflow-y-auto outline-none">
          <Outlet />
        </main>
      </div>
      <ShortcutsDialog open={shortcuts} onClose={() => setShortcuts(false)} />
    </div>
  );
}
