/** MeasureFlow mark: a measured signal (polyline) carried through a rounded square. Pure SVG, no external asset. */
export function LogoMark({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden focusable="false" className="shrink-0">
      <rect width="32" height="32" rx="7" className="fill-primary" />
      <path d="M6 19.5 11 11l5 10 5-10.5 5 7" fill="none" className="stroke-primary-fg" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function Wordmark({ collapsed }: { collapsed?: boolean }) {
  return (
    <div className="flex items-center gap-2.5">
      <LogoMark />
      {!collapsed && (
        <span className="text-[15px] font-semibold tracking-[-0.02em] text-ink">
          Measure<span className="text-ink-2">Flow</span>
        </span>
      )}
    </div>
  );
}
