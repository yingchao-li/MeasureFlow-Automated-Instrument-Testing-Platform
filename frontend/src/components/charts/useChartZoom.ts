import { useCallback, useMemo, useRef, useState } from 'react';
import type { MouseHandlerDataParam } from 'recharts';

export type Domain = [number, number];

function toNumber(v: unknown): number | null {
  if (typeof v === 'number' && Number.isFinite(v)) return v;
  if (typeof v === 'string' && v.trim() !== '' && Number.isFinite(Number(v))) return Number(v);
  return null;
}

export interface ChartZoom {
  /** Current X domain (zoomed or full). */
  domain: Domain | null;
  zoomed: boolean;
  /** Current drag selection to draw as a ReferenceArea. */
  selection: { x1: number; x2: number } | null;
  reset: () => void;
  zoomIn: () => void;
  zoomOut: () => void;
  /** Spread onto the Recharts chart component. */
  handlers: {
    onMouseDown: (s: MouseHandlerDataParam) => void;
    onMouseMove: (s: MouseHandlerDataParam) => void;
    onMouseUp: () => void;
    onMouseLeave: () => void;
  };
}

/**
 * Drag-to-zoom on a numeric X axis. The chart must use a numeric `activeLabel`
 * (XAxis type="number" with a dataKey shared by all rows).
 */
export function useChartZoom(full: Domain | null): ChartZoom {
  const [zoom, setZoom] = useState<Domain | null>(null);
  const [selection, setSelection] = useState<{ x1: number; x2: number } | null>(null);
  const selRef = useRef(selection);
  selRef.current = selection;

  const domain = useMemo<Domain | null>(() => {
    if (!full) return null;
    if (!zoom) return full;
    const lo = Math.max(zoom[0], full[0]);
    const hi = Math.min(zoom[1], full[1]);
    return hi > lo ? [lo, hi] : full;
  }, [full, zoom]);

  const onMouseDown = useCallback((s: MouseHandlerDataParam) => {
    const x = toNumber(s.activeLabel);
    if (x !== null) setSelection({ x1: x, x2: x });
  }, []);
  const onMouseMove = useCallback((s: MouseHandlerDataParam) => {
    const cur = selRef.current;
    if (!cur) return;
    const x = toNumber(s.activeLabel);
    if (x !== null && x !== cur.x2) setSelection({ x1: cur.x1, x2: x });
  }, []);
  const onMouseUp = useCallback(() => {
    const cur = selRef.current;
    setSelection(null);
    if (!cur || cur.x1 === cur.x2) return;
    setZoom([Math.min(cur.x1, cur.x2), Math.max(cur.x1, cur.x2)]);
  }, []);
  const onMouseLeave = useCallback(() => setSelection(null), []);

  const reset = useCallback(() => setZoom(null), []);
  const zoomIn = useCallback(() => {
    if (!domain) return;
    const c = (domain[0] + domain[1]) / 2;
    const half = (domain[1] - domain[0]) / 4;
    setZoom([c - half, c + half]);
  }, [domain]);
  const zoomOut = useCallback(() => {
    if (!domain || !full) return;
    const c = (domain[0] + domain[1]) / 2;
    const half = domain[1] - domain[0];
    const lo = Math.max(full[0], c - half);
    const hi = Math.min(full[1], c + half);
    setZoom(lo <= full[0] && hi >= full[1] ? null : [lo, hi]);
  }, [domain, full]);

  return {
    domain,
    zoomed: zoom !== null && domain !== null && full !== null && (domain[0] !== full[0] || domain[1] !== full[1]),
    selection,
    reset,
    zoomIn,
    zoomOut,
    handlers: { onMouseDown, onMouseMove, onMouseUp, onMouseLeave },
  };
}
