import { readFileSync } from 'node:fs';

const tokensCss = readFileSync(`${process.cwd()}/src/styles/tokens.css`, 'utf8');

type Rgb = [number, number, number];

/** Parse the "R G B" triplets of one theme block out of tokens.css. */
function parseTheme(selectorPattern: RegExp): Record<string, Rgb> {
  const match = selectorPattern.exec(tokensCss);
  if (!match) throw new Error(`theme block not found: ${selectorPattern}`);
  const out: Record<string, Rgb> = {};
  const decl = /--([a-z0-9-]+):\s*(\d+)\s+(\d+)\s+(\d+)\s*;/g;
  let m: RegExpExecArray | null;
  while ((m = decl.exec(match[1] ?? ''))) {
    out[m[1] as string] = [Number(m[2]), Number(m[3]), Number(m[4])];
  }
  return out;
}

const themes: Record<string, Record<string, Rgb>> = {
  light: parseTheme(/:root,\s*:root\[data-theme='light'\]\s*\{([\s\S]*?)\n\}/),
  dark: parseTheme(/:root\[data-theme='dark'\]\s*\{([\s\S]*?)\n\}/),
};

function luminance([r, g, b]: Rgb): number {
  const lin = (v: number) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

export function contrast(a: Rgb, b: Rgb): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

/** [foreground token, background token, minimum ratio, purpose] */
const textPairs: Array<[string, string, number]> = [
  ['text', 'surface', 4.5],
  ['text', 'canvas', 4.5],
  ['text', 'sunken', 4.5],
  ['text', 'hover', 4.5],
  ['text-2', 'surface', 4.5],
  ['text-2', 'canvas', 4.5],
  ['text-2', 'sunken', 4.5],
  ['text-3', 'surface', 4.5],
  ['text-3', 'canvas', 4.5],
  ['text-3', 'sunken', 4.5],
  ['primary-fg', 'primary', 4.5],
  ['primary-fg', 'primary-hover', 4.5],
  ['primary-text', 'surface', 4.5],
  ['primary-text', 'primary-soft', 4.5],
  ['success-text', 'success-soft', 4.5],
  ['success-text', 'surface', 4.5],
  ['warn-text', 'warn-soft', 4.5],
  ['warn-text', 'surface', 4.5],
  ['danger-text', 'danger-soft', 4.5],
  ['danger-text', 'surface', 4.5],
  ['neutral-text', 'neutral-soft', 4.5],
  ['neutral-text', 'surface', 4.5],
  ['info-text', 'info-soft', 4.5],
  ['text', 'primary-soft', 4.5],
];

/** Non-text UI: control borders, status dots/bars, focus ring, chart marks (WCAG 1.4.11, 3:1). */
const uiPairs: Array<[string, string, number]> = [
  ['control-border', 'surface', 3],
  ['ring', 'surface', 3],
  ['ring', 'canvas', 3],
  ['success', 'surface', 3],
  ['warn', 'surface', 3],
  ['danger', 'surface', 3],
  ['neutral', 'surface', 3],
  ['info', 'surface', 3],
  ['chart-1', 'surface', 3],
  ['chart-2', 'surface', 3],
  ['chart-3', 'surface', 3],
  ['chart-4', 'surface', 3],
  ['chart-5', 'surface', 3],
  ['chart-6', 'surface', 3],
  ['chart-7', 'surface', 3],
  ['chart-axis', 'surface', 4.5],
];

describe.each(Object.keys(themes))('%s theme tokens meet WCAG AA', (name) => {
  const t = themes[name] as Record<string, Rgb>;
  it.each(textPairs)('text %s on %s >= %s:1', (fg, bg, min) => {
    const ratio = contrast(t[fg] as Rgb, t[bg] as Rgb);
    expect(ratio, `${fg} on ${bg} = ${ratio.toFixed(2)}`).toBeGreaterThanOrEqual(min);
  });
  it.each(uiPairs)('ui %s on %s >= %s:1', (fg, bg, min) => {
    const ratio = contrast(t[fg] as Rgb, t[bg] as Rgb);
    expect(ratio, `${fg} on ${bg} = ${ratio.toFixed(2)}`).toBeGreaterThanOrEqual(min);
  });
  it('defines the same tokens in both themes', () => {
    expect(Object.keys(themes['light'] as object).sort()).toEqual(Object.keys(themes['dark'] as object).sort());
  });
});
