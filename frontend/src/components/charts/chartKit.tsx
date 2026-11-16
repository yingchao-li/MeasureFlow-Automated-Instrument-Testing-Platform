import type { ReactNode } from 'react';
import { Minus, Plus, RotateCcw } from 'lucide-react';
import { cn, IconButton } from '@/components/ui';
import type { ChartTheme } from './useChartTheme';
import type { ChartZoom } from './useChartZoom';

/** Shared axis styling: 11px mono ticks, hairline axis, no tick marks. */
export function axisStyle(t: ChartTheme) {
  return {
    tick: { fill: t.axis, fontSize: 11, fontFamily: 'JetBrains Mono, ui-monospace, monospace' },
    axisLine: { stroke: t.grid },
    tickLine: false as const,
  };
}

export function axisLabel(t: ChartTheme, value: string, position: 'insideBottom' | 'insideLeft' | 'insideRight' = 'insideBottom') {
  return {
    value,
    position,
    fill: t.axis,
    fontSize: 11,
    offset: position === 'insideBottom' ? -4 : 8,
    ...(position === 'insideLeft' ? { angle: -90, style: { textAnchor: 'middle' as const } } : {}),
  };
}

interface TooltipEntry {
  name?: string | number;
  value?: unknown;
  color?: string;
  dataKey?: unknown;
  payload?: Record<string, unknown>;
}

export interface ChartTooltipProps {
  active?: boolean;
  payload?: ReadonlyArray<TooltipEntry>;
  label?: string | number;
  /** Heading above the rows, e.g. "t = 1.25 ms". Default: String(label). */
  title?: (label: string | number | undefined, payload: ReadonlyArray<TooltipEntry>) => ReactNode;
  /** Format a row; return null to hide the row. */
  row?: (entry: TooltipEntry) => ReactNode;
}

/** Tooltip card in the app's tokens: mono, tabular, hairline border. */
export function ChartTooltip({ active, payload, label, title, row }: ChartTooltipProps) {
  if (!active || !payload || payload.length === 0) return null;
  const rows = payload
    .map((e, i) => ({ e, node: row ? row(e) : defaultRow(e), key: `${String(e.dataKey ?? e.name)}-${i}` }))
    .filter((r) => r.node !== null);
  if (rows.length === 0) return null;
  return (
    <div className="pointer-events-none rounded-md border border-border-strong bg-surface px-2.5 py-1.5 text-xs shadow-pop">
      <p className="mono mb-1 font-medium text-ink">{title ? title(label, payload) : String(label ?? '')}</p>
      <ul className="space-y-0.5">
        {rows.map(({ e, node, key }) => (
          <li key={key} className="flex items-center gap-2 text-ink-2">
            {e.color && <span aria-hidden className="inline-block h-2 w-2 shrink-0 rounded-sm" style={{ background: e.color }} />}
            <span className="mono">{node}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function defaultRow(e: TooltipEntry): ReactNode {
  const v = typeof e.value === 'number' ? e.value.toPrecision(5) : String(e.value ?? '');
  return `${e.name ?? ''}${e.name ? ': ' : ''}${v}`;
}

export interface LegendItem {
  key: string;
  label: string;
  color: string;
  /** Marker shape so series differ by more than colour. */
  shape?: 'square' | 'circle' | 'diamond' | 'line';
  hidden?: boolean;
}

/** Legend that doubles as series visibility toggles (buttons with aria-pressed). */
export function LegendToggles({ items, onToggle, label = 'Series' }: { items: ReadonlyArray<LegendItem>; onToggle?: (key: string) => void; label?: string }) {
  return (
    <ul aria-label={label} className="flex flex-wrap items-center gap-1">
      {items.map((it) => {
        const content = (
          <>
            <Swatch color={it.color} shape={it.shape} dim={it.hidden} />
            <span className={cn(it.hidden && 'line-through')}>{it.label}</span>
          </>
        );
        return (
          <li key={it.key}>
            {onToggle ? (
              <button
                type="button"
                aria-pressed={!it.hidden}
                onClick={() => onToggle(it.key)}
                className={cn('inline-flex h-6 items-center gap-1.5 rounded px-1.5 text-xs transition-colors hover:bg-hover', it.hidden ? 'text-ink-3' : 'text-ink-2')}
              >
                {content}
              </button>
            ) : (
              <span className="inline-flex h-6 items-center gap-1.5 px-1.5 text-xs text-ink-2">{content}</span>
            )}
          </li>
        );
      })}
    </ul>
  );
}

function Swatch({ color, shape = 'square', dim }: { color: string; shape?: LegendItem['shape']; dim?: boolean }) {
  const style = { background: dim ? 'transparent' : color, borderColor: color };
  if (shape === 'line') return <span aria-hidden className="inline-block h-0.5 w-3.5 rounded-full" style={{ background: color, opacity: dim ? 0.4 : 1 }} />;
  if (shape === 'diamond') return <span aria-hidden className="inline-block h-2 w-2 rotate-45 border" style={style} />;
  return <span aria-hidden className={cn('inline-block h-2 w-2 border', shape === 'circle' ? 'rounded-full' : 'rounded-sm')} style={style} />;
}

/** Zoom in / out / reset buttons plus a hint. Dragging on the chart selects a range. */
export function ZoomControls({ zoom, hint = 'Drag to zoom · double-click to reset' }: { zoom: ChartZoom; hint?: string }) {
  return (
    <div className="flex items-center gap-1">
      <span className="mr-1 hidden text-[11px] text-ink-3 2xl:inline">{hint}</span>
      <IconButton label="Zoom in" size="sm" onClick={zoom.zoomIn} disabled={!zoom.domain}>
        <Plus aria-hidden className="h-3.5 w-3.5" />
      </IconButton>
      <IconButton label="Zoom out" size="sm" onClick={zoom.zoomOut} disabled={!zoom.zoomed}>
        <Minus aria-hidden className="h-3.5 w-3.5" />
      </IconButton>
      <IconButton label="Reset zoom" size="sm" onClick={zoom.reset} disabled={!zoom.zoomed}>
        <RotateCcw aria-hidden className="h-3.5 w-3.5" />
      </IconButton>
    </div>
  );
}

/** Status marker for scatter-like points: PASS = circle, FAIL = diamond, other = square. Shape is redundant with colour. */
export function StatusMarker({ cx, cy, status, color, theme, r = 3.5 }: { cx?: number; cy?: number; status: string; color: string; theme: ChartTheme; r?: number }) {
  if (cx === undefined || cy === undefined || Number.isNaN(cx) || Number.isNaN(cy)) return null;
  if (status === 'FAIL') {
    const s = r + 1.5;
    return <path d={`M${cx} ${cy - s} L${cx + s} ${cy} L${cx} ${cy + s} L${cx - s} ${cy} Z`} fill={theme.warn} stroke={theme.surface} strokeWidth={1} />;
  }
  if (status === 'ERROR') return <rect x={cx - r} y={cy - r} width={r * 2} height={r * 2} fill={theme.danger} stroke={theme.surface} strokeWidth={1} />;
  return <circle cx={cx} cy={cy} r={r} fill={color} stroke={theme.surface} strokeWidth={1} />;
}
