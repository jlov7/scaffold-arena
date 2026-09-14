import { defineConfig } from '@playwright/test'

const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? 'http://127.0.0.1:4317'
const webServerPort = new URL(baseURL).port || '4317'
const webServer = {
  command: `./node_modules/.bin/vite --host 127.0.0.1 --port ${webServerPort} --strictPort`,
  url: baseURL,
  reuseExistingServer: !process.env.CI,
  timeout: 120_000,
}

export default defineConfig({
  testDir: './tests',
  workers: process.env.CI ? 1 : undefined,
  use: {
    channel: 'chrome',
  },
  timeout: 30_000,
  expect: {
    timeout: 10_000,
    toHaveScreenshot: {
      maxDiffPixelRatio: 0.01,
      animations: 'disabled',
      threshold: 0.2,
    },
  },
  reporter: [['list'], ['html', { open: 'never' }]],

  projects: [
    {
      name: 'default',
      testDir: './tests',
      testIgnore: ['**/visual/**', '**/e2e/offline-demo-real.spec.ts'],
      use: {
        baseURL,
        trace: 'on-first-retry',
        screenshot: 'only-on-failure',
      },
    },
    {
      name: 'offline-demo',
      testDir: './tests/e2e',
      testMatch: 'offline-demo-real.spec.ts',
      use: {
        baseURL,
        trace: 'on-first-retry',
        screenshot: 'only-on-failure',
      },
    },
    {
      name: 'visual',
      testDir: './tests/visual',
      use: {
        baseURL,
        trace: 'on-first-retry',
        screenshot: 'only-on-failure',
        viewport: { width: 1440, height: 900 },
        deviceScaleFactor: 2,
        colorScheme: 'dark',
      },
    },
  ],

  ...(process.env.PLAYWRIGHT_EXTERNAL_WEB_SERVER ? {} : { webServer }),
})
