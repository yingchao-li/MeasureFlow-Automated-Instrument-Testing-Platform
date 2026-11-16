import { defineConfig } from '@playwright/test';

// A private simulator + C++ backend (temp data dir, loopback only) is started by experiments/stack.py --serve.
// Its control API (reset / stop / kill the backend or simulator) is what the offline-state tests use.
export const PORT = Number(process.env.MF_E2E_PORT ?? 18080);
export const CONTROL_PORT = Number(process.env.MF_E2E_CONTROL_PORT ?? 18081);
const SIM_PORT = Number(process.env.MF_E2E_SIM_PORT ?? 18090);
const PYTHON = process.env.MF_PYTHON ?? 'python3';

// Browser: Playwright's own Chromium by default; PW_CHANNEL=chrome or PW_CHROME_PATH=/path/to/chrome to use an installed browser.
const chromeArgs = process.env.PW_NO_SANDBOX === '1' || process.getuid?.() === 0 ? ['--no-sandbox'] : [];

export default defineConfig({
  testDir: './specs',
  fullyParallel: false,
  workers: 1, // one shared backend; tests reset it in beforeEach
  retries: process.env.CI ? 1 : 0,
  timeout: 45_000,
  expect: { timeout: 8_000 },
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : [['list']],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    viewport: { width: 1440, height: 900 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    channel: process.env.PW_CHANNEL || undefined,
    launchOptions: { executablePath: process.env.PW_CHROME_PATH || undefined, args: chromeArgs },
  },
  webServer: {
    command: `${PYTHON} ../../experiments/stack.py --serve --backend-port ${PORT} --control-port ${CONTROL_PORT} --sim-base-port ${SIM_PORT}`,
    url: `http://127.0.0.1:${PORT}/api/health`,
    reuseExistingServer: false,
    timeout: 60_000,
    gracefulShutdown: { signal: 'SIGTERM', timeout: 10_000 },
  },
});
