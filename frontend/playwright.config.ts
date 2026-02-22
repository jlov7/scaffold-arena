import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests',
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
      testIgnore: ['**/visual/**'],
      use: {
        baseURL: 'http://127.0.0.1:4317',
        trace: 'on-first-retry',
        screenshot: 'only-on-failure',
      },
    },
    {
      name: 'visual',
      testDir: './tests/visual',
      use: {
        baseURL: 'http://127.0.0.1:4317',
        trace: 'on-first-retry',
        screenshot: 'only-on-failure',
        viewport: { width: 1440, height: 900 },
        deviceScaleFactor: 2,
        colorScheme: 'dark',
      },
    },
  ],

  webServer: {
    command: 'pnpm dev --host 127.0.0.1 --port 4317',
    url: 'http://127.0.0.1:4317',
    reuseExistingServer: false,
    timeout: 120_000,
  },
})
