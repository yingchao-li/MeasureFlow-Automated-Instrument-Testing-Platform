import { useMemo } from 'react';
import { useTheme } from '@/context/ThemeContext';

export interface ChartTheme {
  grid: string;
  axis: string;
  text: string;
  surface: string;
  border: string;
  /** Colour-blind-safe categorical series colours (theme aware). */
  series: string[];
  /** Categories such as firmware versions: no green, amber or red, so they never read as PASS/FAIL. */
  categories: string[];
  success: string;
  warn: string;
  danger: string;
  neutral: string;
  primary: string;
}

const FALLBACK: Record<'light' | 'dark', ChartTheme> = {
  light: {
    grid: 'rgb(228 225 218)',
    axis: 'rgb(104 109 118)',
    text: 'rgb(28 30 33)',
    surface: 'rgb(251 250 248)',
    border: 'rgb(228 225 218)',
    series: ['rgb(38 104 180)', 'rgb(190 84 8)', 'rgb(0 128 96)', 'rgb(168 78 138)', 'rgb(86 112 150)', 'rgb(142 112 0)'],
    categories: ['rgb(38 104 180)', 'rgb(168 78 138)', 'rgb(6 132 158)', 'rgb(86 112 150)'],
    success: 'rgb(28 138 86)',
    warn: 'rgb(196 112 8)',
    danger: 'rgb(200 54 48)',
    neutral: 'rgb(112 117 126)',
    primary: 'rgb(49 90 158)',
  },
  dark: {
    grid: 'rgb(38 43 48)',
    axis: 'rgb(136 143 152)',
    text: 'rgb(230 232 234)',
    surface: 'rgb(21 24 27)',
    border: 'rgb(38 43 48)',
    series: ['rgb(104 160 232)', 'rgb(240 140 70)', 'rgb(56 196 150)', 'rgb(224 140 190)', 'rgb(150 170 204)', 'rgb(226 192 74)'],
    categories: ['rgb(104 160 232)', 'rgb(224 140 190)', 'rgb(96 200 222)', 'rgb(150 170 204)'],
    success: 'rgb(62 186 128)',
    warn: 'rgb(236 152 46)',
    danger: 'rgb(238 98 90)',
    neutral: 'rgb(140 147 157)',
    primary: 'rgb(122 162 226)',
  },
};

function read(style: CSSStyleDeclaration, name: string, fallback: string): string {
  const v = style.getPropertyValue(`--${name}`).trim();
  return v ? `rgb(${v})` : fallback;
}

/**
 * Resolve the CSS design tokens to concrete colour strings. SVG attributes inside Recharts cannot
 * reliably use var(), so charts read the computed values and re-read them when the theme changes.
 */
export function useChartTheme(): ChartTheme {
  const { resolved } = useTheme();
  return useMemo(() => {
    const fb = FALLBACK[resolved];
    if (typeof document === 'undefined') return fb;
    const style = getComputedStyle(document.documentElement);
    return {
      grid: read(style, 'chart-grid', fb.grid),
      axis: read(style, 'chart-axis', fb.axis),
      text: read(style, 'text', fb.text),
      surface: read(style, 'surface', fb.surface),
      border: read(style, 'border', fb.border),
      series: fb.series.map((f, i) => read(style, `chart-${i + 1}`, f)),
      categories: [read(style, 'chart-1', fb.categories[0] as string), read(style, 'chart-4', fb.categories[1] as string), read(style, 'chart-7', fb.categories[2] as string), read(style, 'chart-5', fb.categories[3] as string)],
      success: read(style, 'success', fb.success),
      warn: read(style, 'warn', fb.warn),
      danger: read(style, 'danger', fb.danger),
      neutral: read(style, 'neutral', fb.neutral),
      primary: read(style, 'primary', fb.primary),
    };
    // `resolved` changes after data-theme is applied (ThemeProvider effect), so recompute then.
  }, [resolved]);
}
