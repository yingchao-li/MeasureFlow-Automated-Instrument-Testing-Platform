import { expect, startRun, test } from './fixtures';

test('full pipeline on a healthy DUT passes all 13 measurements', async ({ page }) => {
  await startRun(page, 'Full Pipeline');
  await expect(page.getByText('Run PASSED')).toBeVisible();
  await expect(page.getByText('All 13 measurements within limits.')).toBeVisible();
  const results = page.getByRole('region', { name: 'Results' }).or(page.locator('section', { has: page.getByText('13 measurements') }));
  await expect(results.first().getByRole('row', { name: /Gain @ 1000 Hz/ })).toContainText('PASS');
  await expect(results.first().getByRole('row', { name: /THD @ 1000 Hz/ })).toContainText('≤ 1 %');
});

test('firmware 1.2.0 regression is reported as FAIL (a measurement result), not ERROR', async ({ page }) => {
  await startRun(page, 'THD Measurement', { firmware: '1.2.0' });
  await expect(page.getByText(/Run FAILED/)).toBeVisible();
  await expect(page.getByRole('row', { name: /THD @ 1000 Hz/ })).toContainText('FAIL');
});

test('LOWGAIN DUT fails the gain verification', async ({ page }) => {
  await startRun(page, 'Gain Verification', { profile: 'LOWGAIN' });
  await expect(page.getByText(/Run FAILED/)).toBeVisible();
});

test('out-of-range parameter is rejected before a run can start', async ({ page }) => {
  await page.goto('/sequences');
  await page.getByRole('radio', { name: /^Gain Verification/ }).click();
  await page.getByLabel('Stimulus frequency').fill('999999');
  await expect(page.getByText(/20 … 20000|out of range|must be/i).first()).toBeVisible();
  await expect(page.getByRole('button', { name: 'Start run' })).toBeDisabled();
});
