import type { Config } from 'tailwindcss';

// Every colour is a CSS variable holding an "R G B" triplet (see src/styles/tokens.css)
// so that Tailwind's opacity modifiers keep working and light/dark share one set of class names.
const token = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

const config: Config = {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: ['selector', '[data-theme="dark"]'],
  theme: {
    // One radius scale: 4 / 6 / 8 px. Nothing larger except full for dots.
    borderRadius: {
      none: '0',
      sm: '4px',
      DEFAULT: '6px',
      md: '6px',
      lg: '8px',
      full: '9999px',
    },
    fontFamily: {
      sans: ['"Inter Variable"', 'Inter', 'ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
      mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
    },
    fontSize: {
      '2xs': ['11px', { lineHeight: '14px', letterSpacing: '0.01em' }],
      xs: ['12px', { lineHeight: '16px' }],
      sm: ['13px', { lineHeight: '20px' }],
      base: ['14px', { lineHeight: '20px' }],
      lg: ['16px', { lineHeight: '24px', letterSpacing: '-0.005em' }],
      xl: ['18px', { lineHeight: '24px', letterSpacing: '-0.01em' }],
      '2xl': ['22px', { lineHeight: '28px', letterSpacing: '-0.015em' }],
      '3xl': ['28px', { lineHeight: '32px', letterSpacing: '-0.02em' }],
    },
    boxShadow: {
      none: 'none',
      sm: '0 1px 2px 0 rgb(var(--shadow) / 0.06)',
      DEFAULT: '0 1px 2px 0 rgb(var(--shadow) / 0.06)',
      pop: '0 8px 24px -4px rgb(var(--shadow) / 0.18), 0 0 0 1px rgb(var(--border) / 1)',
    },
    extend: {
      colors: {
        canvas: token('canvas'),
        surface: token('surface'),
        sunken: token('sunken'),
        hover: token('hover'),
        border: token('border'),
        'border-strong': token('border-strong'),
        control: token('control-border'),
        ink: token('text'),
        'ink-2': token('text-2'),
        'ink-3': token('text-3'),
        primary: {
          DEFAULT: token('primary'),
          hover: token('primary-hover'),
          fg: token('primary-fg'),
          soft: token('primary-soft'),
          text: token('primary-text'),
        },
        ring: token('ring'),
        success: { DEFAULT: token('success'), soft: token('success-soft'), text: token('success-text') },
        warn: { DEFAULT: token('warn'), soft: token('warn-soft'), text: token('warn-text') },
        danger: { DEFAULT: token('danger'), soft: token('danger-soft'), text: token('danger-text') },
        neutral: { DEFAULT: token('neutral'), soft: token('neutral-soft'), text: token('neutral-text') },
        info: { DEFAULT: token('info'), soft: token('info-soft'), text: token('info-text') },
      },
      transitionDuration: { DEFAULT: '150ms' },
      transitionTimingFunction: { DEFAULT: 'cubic-bezier(0.2, 0, 0, 1)' },
      keyframes: {
        'fade-in': { from: { opacity: '0' }, to: { opacity: '1' } },
        'slide-in-right': { from: { transform: 'translateX(12px)', opacity: '0' }, to: { transform: 'none', opacity: '1' } },
        'pulse-soft': { '0%,100%': { opacity: '1' }, '50%': { opacity: '0.45' } },
      },
      animation: {
        'fade-in': 'fade-in 150ms ease-out both',
        'slide-in-right': 'slide-in-right 180ms cubic-bezier(0.2,0,0,1) both',
        'pulse-soft': 'pulse-soft 1.6s ease-in-out infinite',
      },
    },
  },
  plugins: [],
};

export default config;
