import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ThemeProvider } from '@/context/ThemeContext';
import { readStoredMode, resolveTheme, THEME_KEY } from '@/lib/theme';
import { ThemeToggle } from './ThemeToggle';

function mockSystemDark(dark: boolean) {
  const listeners = new Set<() => void>();
  const mq = {
    matches: dark,
    media: '(prefers-color-scheme: dark)',
    addEventListener: (_: string, l: () => void) => listeners.add(l),
    removeEventListener: (_: string, l: () => void) => listeners.delete(l),
  };
  vi.stubGlobal('matchMedia', () => mq);
  return {
    flip(next: boolean) {
      mq.matches = next;
      listeners.forEach((l) => l());
    },
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
  document.documentElement.removeAttribute('data-theme');
});

describe('theme toggle', () => {
  it('applies and persists the chosen mode, and a new session reads it back', async () => {
    mockSystemDark(false);
    const user = userEvent.setup();
    const { unmount } = render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>,
    );
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');

    await user.click(screen.getByRole('radio', { name: 'Dark theme' }));
    expect(localStorage.getItem(THEME_KEY)).toBe('dark');
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    expect(document.documentElement.style.colorScheme).toBe('dark');
    expect(screen.getByRole('radio', { name: 'Dark theme' })).toBeChecked();

    unmount();
    expect(readStoredMode()).toBe('dark');
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>,
    );
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    expect(screen.getByRole('radio', { name: 'Dark theme' })).toBeChecked();
  });

  it('"system" follows the OS preference live and is stored as such', async () => {
    const os = mockSystemDark(true);
    const user = userEvent.setup();
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>,
    );
    // default with no stored value is system -> dark here
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    await user.click(screen.getByRole('radio', { name: 'Light theme' }));
    expect(document.documentElement.getAttribute('data-theme')).toBe('light');
    await user.click(screen.getByRole('radio', { name: 'System theme' }));
    expect(localStorage.getItem(THEME_KEY)).toBe('system');
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark');
    os.flip(false);
    await vi.waitFor(() => expect(document.documentElement.getAttribute('data-theme')).toBe('light'));
  });

  it('ignores garbage in storage and supports keyboard arrows on the radio group', async () => {
    mockSystemDark(false);
    localStorage.setItem(THEME_KEY, 'purple');
    expect(readStoredMode()).toBe('system');
    const user = userEvent.setup();
    render(
      <ThemeProvider>
        <ThemeToggle />
      </ThemeProvider>,
    );
    screen.getByRole('radio', { name: 'System theme' }).focus();
    await user.keyboard('{ArrowLeft}');
    expect(localStorage.getItem(THEME_KEY)).toBe('dark');
  });

  it('resolveTheme maps system to the OS preference', () => {
    expect(resolveTheme('system', true)).toBe('dark');
    expect(resolveTheme('system', false)).toBe('light');
    expect(resolveTheme('light', true)).toBe('light');
  });
});
