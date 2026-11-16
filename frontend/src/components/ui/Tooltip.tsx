import { cloneElement, useCallback, useId, useRef, useState, type ReactElement } from 'react';
import { createPortal } from 'react-dom';

interface TooltipProps {
  content: string;
  side?: 'top' | 'right' | 'bottom';
  children: ReactElement<{ 'aria-describedby'?: string; onMouseEnter?: (e: unknown) => void }>;
  disabled?: boolean;
}

/** Small portal tooltip shown on hover and keyboard focus. Not a replacement for accessible names. */
export function Tooltip({ content, side = 'top', children, disabled }: TooltipProps) {
  const id = useId();
  const [pos, setPos] = useState<{ x: number; y: number; side: 'top' | 'right' | 'bottom' } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  const show = useCallback(
    (el: Element) => {
      clearTimeout(timer.current);
      timer.current = setTimeout(() => {
        const r = el.getBoundingClientRect();
        const cx = Math.min(Math.max(r.left + r.width / 2, 90), Math.max(90, window.innerWidth - 90)); // keep inside the viewport
        // flip when there is no room on the preferred side
        const placed = side === 'top' && r.top < 40 ? 'bottom' : side === 'bottom' && r.bottom > window.innerHeight - 40 ? 'top' : side;
        if (placed === 'right') setPos({ x: r.right + 8, y: r.top + r.height / 2, side: placed });
        else if (placed === 'bottom') setPos({ x: cx, y: r.bottom + 8, side: placed });
        else setPos({ x: cx, y: r.top - 8, side: placed });
      }, 350);
    },
    [side],
  );
  const hide = useCallback(() => {
    clearTimeout(timer.current);
    setPos(null);
  }, []);

  if (disabled) return children;

  const child = cloneElement(children, {
    'aria-describedby': pos ? id : children.props['aria-describedby'],
    onMouseEnter: (e: unknown) => show((e as { currentTarget: Element }).currentTarget),
    onMouseLeave: hide,
    onFocus: (e: unknown) => show((e as { currentTarget: Element }).currentTarget),
    onBlur: hide,
    onKeyDown: (e: { key: string }) => e.key === 'Escape' && hide(),
  } as never);

  const placedSide = pos?.side ?? side;
  const transform = placedSide === 'right' ? 'translate(0,-50%)' : placedSide === 'bottom' ? 'translate(-50%,0)' : 'translate(-50%,-100%)';
  return (
    <>
      {child}
      {pos &&
        createPortal(
          <div
            id={id}
            role="tooltip"
            style={{ left: pos.x, top: pos.y, transform }}
            className="pointer-events-none fixed z-[70] max-w-xs whitespace-nowrap rounded bg-ink px-2 py-1 text-xs font-medium text-surface shadow-pop"
          >
            {content}
          </div>,
          document.body,
        )}
    </>
  );
}
