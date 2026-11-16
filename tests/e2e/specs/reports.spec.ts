import { expect, startRun, test } from './fixtures';

test('a finished run appears in the history with CSV / HTML / PDF reports', async ({ page, request }) => {
  await startRun(page, 'Gain Verification');
  await expect(page.getByText('Run PASSED')).toBeVisible();
  const runId = ((await page.getByLabel('Execution').textContent()) ?? '').match(/run-\d{8}-\d{6}-[0-9a-f]{4}/)?.[0] ?? '';
  expect(runId).toMatch(/^run-/);

  await page.goto('/reports');
  const row = page.getByRole('row', { name: new RegExp(runId) });
  await expect(row).toContainText('PASS');

  const expected: Record<string, RegExp> = { csv: /text\/csv/, html: /text\/html/, pdf: /application\/pdf/ };
  for (const ext of ['csv', 'html', 'pdf']) {
    const href = await row.getByRole('link', { name: `Download ${ext.toUpperCase()} report for ${runId}` }).getAttribute('href');
    const res = await request.get(href!);
    expect(res.status(), ext).toBe(200);
    expect(res.headers()['content-type'], ext).toMatch(expected[ext]);
    expect((await res.body()).length, ext).toBeGreaterThan(100);
  }
});

test('run drawer shows parameters, results, steps and log of a stored run', async ({ page }) => {
  await startRun(page, 'Full Pipeline');
  await expect(page.getByText('Run PASSED')).toBeVisible();
  await page.goto('/reports');
  await page.getByRole('button', { name: /run-\d{8}-\d{6}/ }).first().click();
  for (const name of ['Parameters', 'Results', 'Steps', 'Log']) await expect(page.getByRole('region', { name, exact: true })).toBeVisible();
});

test('summary KPIs reflect persisted results', async ({ page }) => {
  await startRun(page, 'Full Pipeline');
  await expect(page.getByText('Run PASSED')).toBeVisible();
  await page.goto('/reports');
  await expect(page.getByText('13 of 13 measurements')).toBeVisible();
  await expect(page.getByText('1 pass · 0 fail · 0 error · 0 cancelled')).toBeVisible();
});
