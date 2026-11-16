import { expect, test } from './fixtures';

const PAGES = [
  { link: 'Overview', path: '/', heading: 'Overview' },
  { link: 'Instruments', path: '/instruments', heading: 'Instruments' },
  { link: 'Test Sequences', path: '/sequences', heading: 'Test Sequences' },
  { link: 'Reports', path: '/reports', heading: 'Reports' },
];

test('sidebar navigates to all four pages without console errors', async ({ page }) => {
  await page.goto('/');
  for (const p of PAGES) {
    await page.getByRole('navigation', { name: 'Primary' }).getByRole('link', { name: p.link }).click();
    await expect(page).toHaveURL(new RegExp(`${p.path === '/' ? '/$' : p.path}$`));
    await expect(page.getByRole('heading', { name: p.heading, level: 1 })).toBeVisible();
  }
});

test('unknown route shows the not-found state with a way back', async ({ page }) => {
  await page.goto('/no-such-page');
  await expect(page.getByText('This page does not exist')).toBeVisible();
  await page.getByRole('link', { name: 'Back to Overview' }).click();
  await expect(page).toHaveURL(/\/$/);
});

test('fresh system shows empty states instead of fake data', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('No measurements yet')).toBeVisible();
  await expect(page.getByText('No test runs yet')).toBeVisible();
  await expect(page.getByText('No waveform')).toBeVisible();
  await page.goto('/reports');
  await expect(page.getByText('No test runs yet').first()).toBeVisible();
});

test('theme choice applies to the document and survives a reload', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('radio', { name: 'Dark theme' }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await page.reload();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  await page.getByRole('radio', { name: 'Light theme' }).click();
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
});
