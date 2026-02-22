import { expect, test, type Page } from '@playwright/test'

import { mockDefaultApi } from '../support/mockApi'

test.beforeEach(async ({ page }) => {
  await mockDefaultApi(page)
})

async function triggerRunStartFailure(
  page: Page,
  setup: () => Promise<void>,
) {
  await setup()
  await page.goto('/arena')
  await page.getByRole('button', { name: 'Run arena' }).first().click()
  return page.getByRole('alert').filter({ hasText: /Failed to start run/i }).first()
}

test('recovery class 01: auth 401 guides API token remediation', async ({ page }) => {
  const toast = await triggerRunStartFailure(page, async () => {
    await page.route('**/api/runs', async (route) => {
      await route.fulfill({
        status: 401,
        contentType: 'text/plain',
        body: 'unauthorized',
      })
    })
  })
  await expect(toast).toBeVisible()
  await expect(toast).toContainText(/api token|session settings/i)
})

test('recovery class 02: auth 403 guides API token remediation', async ({ page }) => {
  const toast = await triggerRunStartFailure(page, async () => {
    await page.route('**/api/runs', async (route) => {
      await route.fulfill({
        status: 403,
        contentType: 'text/plain',
        body: 'forbidden',
      })
    })
  })
  await expect(toast).toBeVisible()
  await expect(toast).toContainText(/api token|session settings/i)
})

test('recovery class 03: 429 guides rate-limit retry strategy', async ({ page }) => {
  const toast = await triggerRunStartFailure(page, async () => {
    await page.route('**/api/runs', async (route) => {
      await route.fulfill({
        status: 429,
        contentType: 'text/plain',
        body: 'rate limit exceeded',
      })
    })
  })
  await expect(toast).toBeVisible()
  await expect(toast).toContainText(/wait a moment|retry/i)
})

test('recovery class 04: validation 400 guides input review', async ({ page }) => {
  const toast = await triggerRunStartFailure(page, async () => {
    await page.route('**/api/runs', async (route) => {
      await route.fulfill({
        status: 400,
        contentType: 'text/plain',
        body: 'validation failed',
      })
    })
  })
  await expect(toast).toBeVisible()
  await expect(toast).toContainText(/review your inputs/i)
})

test('recovery class 05: validation 413 guides payload reduction', async ({ page }) => {
  const toast = await triggerRunStartFailure(page, async () => {
    await page.route('**/api/runs', async (route) => {
      await route.fulfill({
        status: 413,
        contentType: 'text/plain',
        body: 'request entity too large',
      })
    })
  })
  await expect(toast).toBeVisible()
  await expect(toast).toContainText(/review your inputs/i)
})

test('recovery class 06: validation 422 guides schema/input correction', async ({
  page,
}) => {
  const toast = await triggerRunStartFailure(page, async () => {
    await page.route('**/api/runs', async (route) => {
      await route.fulfill({
        status: 422,
        contentType: 'text/plain',
        body: 'invalid schema',
      })
    })
  })
  await expect(toast).toBeVisible()
  await expect(toast).toContainText(/review your inputs/i)
})

test('recovery class 07: server 500 suggests short retry loop', async ({ page }) => {
  const toast = await triggerRunStartFailure(page, async () => {
    await page.route('**/api/runs', async (route) => {
      await route.fulfill({
        status: 500,
        contentType: 'text/plain',
        body: 'internal server error',
      })
    })
  })
  await expect(toast).toBeVisible()
  await expect(toast).toContainText(/temporary server issue|retry shortly/i)
})

test('recovery class 08: server 503 suggests short retry loop', async ({ page }) => {
  const toast = await triggerRunStartFailure(page, async () => {
    await page.route('**/api/runs', async (route) => {
      await route.fulfill({
        status: 503,
        contentType: 'text/plain',
        body: 'service unavailable',
      })
    })
  })
  await expect(toast).toBeVisible()
  await expect(toast).toContainText(/temporary server issue|retry shortly/i)
})

test('recovery class 09: network timeout/abort gives connectivity guidance', async ({
  page,
}) => {
  const toast = await triggerRunStartFailure(page, async () => {
    await page.route('**/api/runs', async (route) => {
      await route.abort('timedout')
    })
  })
  await expect(toast).toBeVisible()
  await expect(toast).toContainText(/network connection|retry/i)
})

test('recovery class 10: network failure gives connectivity guidance', async ({
  page,
}) => {
  const toast = await triggerRunStartFailure(page, async () => {
    await page.route('**/api/runs', async (route) => {
      await route.abort('failed')
    })
  })
  await expect(toast).toBeVisible()
  await expect(toast).toContainText(/network connection|retry/i)
})

test('recovery class 11: unknown error still provides fallback retry guidance', async ({
  page,
}) => {
  const toast = await triggerRunStartFailure(page, async () => {
    await page.route('**/api/runs', async (route) => {
      await route.fulfill({
        status: 418,
        contentType: 'text/plain',
        body: "I'm a teapot",
      })
    })
  })
  await expect(toast).toBeVisible()
  await expect(toast).toContainText(/retry the action|inspect logs/i)
})

test('recovery class 12: missing token path points to settings recovery', async ({
  page,
}) => {
  await page.goto('/arena')

  await expect(
    page.getByText('Open settings and configure a valid API token.'),
  ).toBeVisible()
  await page.getByRole('button', { name: /^Help$/ }).click()
  const helpDialog = page.getByRole('dialog', { name: 'Help Center' })
  await expect(helpDialog.getByRole('button', { name: 'Open settings now' })).toBeVisible()
})
