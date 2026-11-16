import { connectAll, control, expect, test } from './fixtures';

test('backend outage shows the offline banner and recovers by itself', async ({ page, allowConsoleErrors }) => {
  allowConsoleErrors(); // failed fetches while the backend is down are logged by the browser
  await page.goto('/');
  await expect(page.getByRole('status', { name: /Connection:/ })).toBeVisible();

  await control('/backend/stop');
  await expect(page.getByRole('alert')).toContainText('Backend unreachable', { timeout: 30_000 });

  await control('/backend/start');
  await page.getByRole('button', { name: 'Retry now' }).click();
  await expect(page.getByRole('alert')).toHaveCount(0, { timeout: 30_000 });
});

test('simulator loss degrades the system status instead of crashing the UI', async ({ page, allowConsoleErrors }) => {
  allowConsoleErrors();
  await connectAll();
  await page.goto('/');
  await expect(page.getByRole('status', { name: /Connection: Operational/ })).toBeVisible();

  await control('/simulator/kill');
  await expect(page.getByText(/Degraded|Unavailable|Down/).first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole('heading', { name: 'Overview', level: 1 })).toBeVisible();
});
