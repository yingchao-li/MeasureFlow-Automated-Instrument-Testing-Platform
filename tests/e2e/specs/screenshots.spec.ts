import path from 'node:path';
import type { Page } from '@playwright/test';
import { API, control, expect, startRun, test } from './fixtures';

// Generates the README screenshots from the *real* UI against the real backend + simulated instruments:
//   MF_SCREENSHOTS=1 npx playwright test specs/screenshots.spec.ts
// Skipped in the normal E2E run so that the committed images only change on purpose.
test.skip(!process.env.MF_SCREENSHOTS, 'set MF_SCREENSHOTS=1 to regenerate the README screenshots');

const OUT = path.resolve(process.cwd(), '../../screenshots');
const post = async (p: string, body: unknown) => {
  const r = await fetch(API + p, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(`${p} -> HTTP ${r.status}: ${await r.text()}`);
  return r.json();
};
const runAndWait = async (body: Record<string, unknown>) => {
  await post('/api/tests/run', body);
  await expect.poll(async () => (await (await fetch(`${API}/api/tests/status?log_tail=0`)).json()).run?.status ?? 'none', { timeout: 20_000 }).toMatch(/^(PASS|FAIL|ERROR|CANCELLED)$/);
};
const setTheme = async (page: Page, theme: 'light' | 'dark') => {
  await page.getByRole('radio', { name: theme === 'dark' ? 'Dark theme' : 'Light theme' }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
  await page.waitForTimeout(400);
};
const shot = (page: Page, name: string, theme: string) => page.screenshot({ path: path.join(OUT, `${name}-${theme}.png`) });

test('empty state', async ({ page }) => {
  await page.goto('/');
  await setTheme(page, 'light');
  await expect(page.getByText('No test runs yet')).toBeVisible();
  await shot(page, 'overview-empty', 'light');
});

test.describe('populated system', () => {
  test.beforeEach(async () => {
    await post('/api/instruments/connect', { id: 'all' });
    await runAndWait({ sequence_id: 'full_pipeline', label: 'healthy DUT' });
    await runAndWait({ sequence_id: 'full_pipeline', dut: { firmware: '1.1.0' } });
    await runAndWait({ sequence_id: 'full_pipeline', dut: { firmware: '1.2.0' }, label: 'firmware regression' });
    await runAndWait({ sequence_id: 'full_pipeline', dut: { profile: 'NOISY' } });
    await runAndWait({ sequence_id: 'full_pipeline', dut: { profile: 'LOWGAIN' } });
    await runAndWait({ sequence_id: 'gain_verification', dut: { profile: 'HIGHTHD' } });
    await runAndWait({ sequence_id: 'thd_measurement', label: 'back to NORMAL DUT' }); // leave the DUT in its NORMAL profile for the live view
    await post('/api/instruments/command', { id: 'siggen', command: 'OUTP ON' });
  });

  for (const theme of ['light', 'dark'] as const) {
    test(`pages in ${theme} mode`, async ({ page }) => {
      await page.setViewportSize({ width: 1440, height: 1250 });

      await page.goto('/');
      await setTheme(page, theme);
      await expect(page.getByLabel('Live signal').getByRole('status').filter({ hasText: /^Live\b/ })).toBeVisible();
      await page.waitForTimeout(800);
      await shot(page, 'overview', theme);

      await page.goto('/instruments');
      await page.getByRole('tab', { name: 'SCPI console' }).click();
      const input = page.getByLabel('SCPI command');
      for (const cmd of ['*IDN?', 'MF:ACQ:INIT', 'MEAS:RMS?', 'MEAS:THD?', 'SYST:ERR?']) {
        await input.fill(cmd);
        await input.press('Enter');
        await page.waitForTimeout(150);
      }
      await shot(page, 'instruments', theme);

      await page.setViewportSize({ width: 1440, height: 1900 });
      await startRun(page, 'Full Pipeline', { profile: 'HIGHTHD' });
      await expect(page.getByText(/Run (PASSED|FAILED)/)).toBeVisible();
      await page.waitForTimeout(600);
      await shot(page, 'sequences', theme);

      await page.setViewportSize({ width: 1440, height: 1250 });
      await page.goto('/reports');
      await expect(page.getByRole('button', { name: /run-\d{8}-\d{6}/ }).first()).toBeVisible();
      await shot(page, 'reports', theme);
      await page.getByRole('tab', { name: 'Trends' }).click();
      await page.waitForTimeout(700);
      await shot(page, 'reports-trends', theme);
      await page.getByRole('tab', { name: 'Firmware comparison' }).click();
      await page.waitForTimeout(700);
      await shot(page, 'reports-firmware', theme);
    });
  }

  test('offline state', async ({ page, allowConsoleErrors }) => {
    allowConsoleErrors();
    await page.goto('/');
    await setTheme(page, 'light');
    await expect(page.getByRole('status', { name: /Connection: Operational/ })).toBeVisible();
    await control('/backend/stop');
    await expect(page.getByRole('alert')).toContainText('Backend unreachable', { timeout: 30_000 });
    await shot(page, 'overview-offline', 'light');
    await control('/backend/start');
  });
});
