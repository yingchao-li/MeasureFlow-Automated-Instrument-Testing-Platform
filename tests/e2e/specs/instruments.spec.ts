import { expect, test } from './fixtures';

test('connect all, query *IDN? in the SCPI console, disconnect all', async ({ page }) => {
  await page.goto('/instruments');
  await expect(page.getByText('0 of 3 connected')).toBeVisible();

  await page.getByRole('button', { name: 'Connect all', exact: true }).first().click();
  await expect(page.getByText('3 of 3 connected')).toBeVisible();

  await page.getByRole('tab', { name: 'SCPI console' }).click();
  const input = page.getByLabel('SCPI command');
  await input.fill('*IDN?');
  await input.press('Enter');
  await expect(page.getByRole('log', { name: 'SCPI transcript' })).toContainText('MeasureFlow,VAA-2000');

  await page.getByRole('button', { name: 'Disconnect all', exact: true }).click();
  await expect(page.getByText('0 of 3 connected')).toBeVisible();
});

test('an invalid SCPI command is reported, not silently swallowed', async ({ page }) => {
  await page.goto('/instruments');
  await page.getByRole('button', { name: 'Connect all', exact: true }).first().click();
  await expect(page.getByText('3 of 3 connected')).toBeVisible();
  await page.getByRole('tab', { name: 'SCPI console' }).click();
  const input = page.getByLabel('SCPI command');
  await input.fill('BOGUS:COMMAND?');
  await input.press('Enter');
  const transcript = page.getByRole('log', { name: 'SCPI transcript' });
  await expect(transcript.getByTestId('scpi-entry')).toHaveCount(1);
  await expect(transcript).not.toContainText('MeasureFlow,');
});

test('overview shows live measurements after connecting', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: 'Connect all', exact: true }).first().click();
  await expect(page.getByRole('status', { name: /Connection: Operational/ })).toBeVisible();
  await expect(page.getByLabel('Live signal').getByRole('status').filter({ hasText: /^Live\b/ })).toBeVisible();
  await expect(page.getByText(/Waveform of 1024 samples, peak amplitude/)).toBeAttached();
});
