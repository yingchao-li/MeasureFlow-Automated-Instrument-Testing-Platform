import type { ReactElement } from 'react';
import { render, type RenderOptions } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { ThemeProvider } from '@/context/ThemeContext';
import { ToastProvider } from '@/context/ToastContext';

/** Render with the providers every component expects (theme, toasts, router). */
export function renderWithProviders(ui: ReactElement, { route = '/', ...options }: RenderOptions & { route?: string } = {}) {
  return render(ui, {
    wrapper: ({ children }) => (
      <ThemeProvider>
        <ToastProvider>
          <MemoryRouter initialEntries={[route]}>{children}</MemoryRouter>
        </ToastProvider>
      </ThemeProvider>
    ),
    ...options,
  });
}
