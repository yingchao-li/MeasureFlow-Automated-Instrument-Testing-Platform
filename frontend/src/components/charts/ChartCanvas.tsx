import { useLayoutEffect, useRef, useState, type ReactNode } from 'react';

interface ChartCanvasProps {
  height: number;
  /** Rendered with the measured pixel size. */
  children: (size: { width: number; height: number }) => ReactNode;
  onDoubleClick?: () => void;
  /** Width used when the container has not been measured (jsdom / hidden tabs). */
  fallbackWidth?: number;
}

/**
 * Measures its own width and hands explicit pixel sizes to Recharts
 * (deterministic, no ResponsiveContainer warnings; works with jsdom in tests).
 */
export function ChartCanvas({ height, children, onDoubleClick, fallbackWidth = 640 }: ChartCanvasProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const measure = () => setWidth(Math.floor(el.getBoundingClientRect().width));
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  return (
    <div ref={ref} style={{ height }} className="w-full select-none" onDoubleClick={onDoubleClick}>
      {children({ width: width > 0 ? width : fallbackWidth, height })}
    </div>
  );
}
