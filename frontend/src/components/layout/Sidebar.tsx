import { NavLink } from 'react-router-dom';
import { Cable, FileBarChart, Keyboard, LayoutDashboard, ListChecks, PanelLeftClose, PanelLeftOpen, type LucideIcon } from 'lucide-react';
import { useHealth } from '@/context/HealthContext';
import { HEALTH_STATUS } from '@/lib/status';
import { cn, IconButton, StatusDot, Tooltip } from '@/components/ui';
import { Wordmark } from './Logo';
import { ThemeToggle } from './ThemeToggle';

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
}

export const NAV_ITEMS: NavItem[] = [
  { to: '/', label: 'Overview', icon: LayoutDashboard, end: true },
  { to: '/instruments', label: 'Instruments', icon: Cable },
  { to: '/sequences', label: 'Test Sequences', icon: ListChecks },
  { to: '/reports', label: 'Reports', icon: FileBarChart },
];

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
  onShowShortcuts: () => void;
}

export function Sidebar({ collapsed, onToggle, onShowShortcuts }: SidebarProps) {
  return (
    <aside
      className={cn('flex shrink-0 flex-col border-r border-border bg-canvas transition-[width] duration-150 ease-out', collapsed ? 'w-14' : 'w-56')}
      aria-label="Sidebar"
    >
      <div className={cn('flex h-12 items-center border-b border-border', collapsed ? 'justify-center' : 'px-4')}>
        <Wordmark collapsed={collapsed} />
      </div>

      <nav aria-label="Primary" className="flex-1 px-2 py-3">
        <ul className="space-y-0.5">
          {NAV_ITEMS.map((item) => (
            <li key={item.to}>
              <Tooltip content={item.label} side="right" disabled={!collapsed}>
                <NavLink
                  to={item.to}
                  end={item.end}
                  aria-label={collapsed ? item.label : undefined}
                  className={({ isActive }) =>
                    cn(
                      'group relative flex h-8 items-center gap-2.5 rounded text-sm font-medium transition-colors',
                      collapsed ? 'justify-center' : 'px-2.5',
                      isActive ? 'bg-hover text-ink' : 'text-ink-2 hover:bg-hover hover:text-ink',
                    )
                  }
                >
                  {({ isActive }) => (
                    <>
                      {isActive && <span aria-hidden className="absolute -left-2 top-1.5 h-5 w-0.5 rounded-full bg-primary" />}
                      <item.icon aria-hidden className={cn('h-4 w-4 shrink-0', isActive ? 'text-primary' : 'text-ink-3 group-hover:text-ink-2')} strokeWidth={1.75} />
                      {!collapsed && <span className="truncate">{item.label}</span>}
                    </>
                  )}
                </NavLink>
              </Tooltip>
            </li>
          ))}
        </ul>
      </nav>

      <div className="space-y-3 border-t border-border p-2">
        <ConnectionIndicator collapsed={collapsed} />
        <div className={cn('flex items-center', collapsed ? 'flex-col gap-1' : 'justify-between px-1')}>
          <ThemeToggle collapsed={collapsed} />
          <div className={cn('flex items-center gap-0.5', collapsed && 'flex-col')}>
            <IconButton label="Keyboard shortcuts" tooltipSide={collapsed ? 'right' : 'top'} onClick={onShowShortcuts}>
              <Keyboard aria-hidden className="h-4 w-4" strokeWidth={1.75} />
            </IconButton>
            <IconButton label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'} tooltipSide={collapsed ? 'right' : 'top'} onClick={onToggle} aria-expanded={!collapsed}>
              {collapsed ? <PanelLeftOpen aria-hidden className="h-4 w-4" strokeWidth={1.75} /> : <PanelLeftClose aria-hidden className="h-4 w-4" strokeWidth={1.75} />}
            </IconButton>
          </div>
        </div>
      </div>
    </aside>
  );
}

/** Backend health + instruments online. Announced politely when it changes. */
function ConnectionIndicator({ collapsed }: { collapsed: boolean }) {
  const { health, offline, isLoading } = useHealth();
  const meta = offline ? { tone: 'danger' as const, label: 'Backend offline' } : health ? HEALTH_STATUS[health.status] : { tone: 'neutral' as const, label: isLoading ? 'Connecting…' : 'Unknown' };
  const detail = health && !offline ? `${health.instruments_online}/${health.instruments_total} instruments online` : offline ? 'Retrying automatically' : '';
  const summary = `${meta.label}${detail ? ` — ${detail}` : ''}`;

  const body = (
    <div role="status" aria-live="polite" aria-label={`Connection: ${summary}`} className={cn('flex items-center gap-2.5 rounded px-2 py-1.5', collapsed && 'justify-center px-0')}>
      <StatusDot tone={meta.tone} pulse={Boolean(health) && !offline && health?.status === 'ok'} />
      {!collapsed && (
        <div className="min-w-0 leading-tight">
          <p className="truncate text-xs font-medium text-ink">{meta.label}</p>
          {detail && <p className="mono truncate text-[11px] text-ink-3">{detail}</p>}
        </div>
      )}
    </div>
  );
  return collapsed ? (
    <Tooltip content={summary} side="right">
      {body}
    </Tooltip>
  ) : (
    body
  );
}
