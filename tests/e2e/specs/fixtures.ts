import { expect, test as base, type Page } from '@playwright/test';
import { CONTROL_PORT, PORT } from '../playwright.config';

export const CONTROL = `http://127.0.0.1:${CONTROL_PORT}`;
export const API = `http://127.0.0.1:${PORT}`;

/** POST to the stack control API (reset, backend/stop, backend/start, simulator/kill, ...). */
export async function control(path: string): Promise<void> {
  const r = await fetch(CONTROL + path, { method: 'POST' });
  if (!r.ok) throw new Error(`control ${path} -> HTTP ${r.status}: ${await r.text()}`);
}

export async function connectAll(): Promise<void> {
  const r = await fetch(`${API}/api/instruments/connect`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: 'all' }) });
  if (!r.ok) throw new Error(`connect -> HTTP ${r.status}`);
}

type Fixtures = { consoleErrors: string[]; allowConsoleErrors: () => void };

/**
 * Every test starts from an empty history and fresh simulator, and fails if the page logged a console error or threw
 * (unless the test calls ``allowConsoleErrors()`` - used by the offline tests, where failed fetches are expected).
 */
export const test = base.extend<Fixtures & { _fresh: void }>({
  _fresh: [async ({}, use) => { await control('/reset'); await use(); }, { auto: true }],
  consoleErrors: async ({ page }, use) => {
    const errors: string[] = [];
    page.on('console', (m) => { if (m.type() === 'error') errors.push(`console.error: ${m.text()}`); });
    page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));
    await use(errors);
  },
  allowConsoleErrors: async ({ consoleErrors }, use) => {
    await use(() => { consoleErrors.length = 0; consoleErrors.push('__allowed__'); });
  },
});

test.afterEach(async ({ consoleErrors }) => {
  if (consoleErrors[0] === '__allowed__') return;
  expect(consoleErrors, 'browser console errors / uncaught exceptions').toEqual([]);
});

export { expect };

export async function startRun(page: Page, sequence: string, opts: { profile?: string; firmware?: string } = {}): Promise<void> {
  await page.goto('/sequences');
  await page.getByRole('radio', { name: new RegExp(`^${sequence}\\b`) }).click();
  if (opts.profile) await page.getByLabel('DUT profile').selectOption(opts.profile);
  if (opts.firmware) await page.getByLabel('DUT firmware').selectOption(opts.firmware);
  await page.getByRole('button', { name: 'Start run' }).click();
}
