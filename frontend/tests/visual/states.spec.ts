import { expect, test } from '@playwright/test'

import { mockDefaultApi } from '../support/mockApi'

test('captures major route snapshots (desktop)', async ({ page }) => {
  await mockDefaultApi(page)
  await page.setViewportSize({ width: 1280, height: 800 })

  await page.goto('/arena')
  const arena = await page.screenshot({ fullPage: true })
  expect(arena.byteLength).toBeGreaterThan(10_000)

  await page.getByRole('button', { name: 'Open History view' }).click()
  const history = await page.screenshot({ fullPage: true })
  expect(history.byteLength).toBeGreaterThan(10_000)

  await page.getByRole('button', { name: 'Open Leaderboard view' }).click()
  const leaderboard = await page.screenshot({ fullPage: true })
  expect(leaderboard.byteLength).toBeGreaterThan(10_000)

  await page.getByRole('button', { name: 'Open Settings view' }).click()
  const settings = await page.screenshot({ fullPage: true })
  expect(settings.byteLength).toBeGreaterThan(10_000)
})

test('captures major route snapshots (mobile)', async ({ page }) => {
  await mockDefaultApi(page)
  await page.setViewportSize({ width: 390, height: 844 })

  await page.goto('/arena')
  const arena = await page.screenshot({ fullPage: true })
  expect(arena.byteLength).toBeGreaterThan(8_000)

  await page.getByRole('button', { name: 'Open Settings view' }).click()
  const settings = await page.screenshot({ fullPage: true })
  expect(settings.byteLength).toBeGreaterThan(8_000)
})

test('captures state-family snapshots (blocked and empty)', async ({ page }) => {
  await mockDefaultApi(page)
  await page.route('**/api/runs', async (route) => {
    await route.fulfill({
      status: 503,
      contentType: 'text/plain',
      body: 'service unavailable',
    })
  })
  await page.route('**/api/runs?*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ runs: [] }),
    })
  })
  await page.setViewportSize({ width: 1280, height: 800 })

  await page.goto('/arena')
  const configureButtons = [
    page.getByRole('button', { name: 'Start with configure lane' }),
    page.getByRole('button', { name: 'Go to configure lane' }),
    page.getByRole('button', { name: /^Configure$/ }),
  ]
  for (const locator of configureButtons) {
    if (await locator.first().isVisible()) {
      await locator.first().click()
      break
    }
  }
  const runButtons = [
    page.getByRole('button', { name: 'Run from configure lane' }),
    page.getByRole('button', { name: 'Run arena' }),
  ]
  for (const locator of runButtons) {
    if (await locator.first().isVisible()) {
      await locator.first().click()
      break
    }
  }
  await expect(page.getByText(/recovery playbook/i)).toBeVisible()
  const blocked = await page.screenshot({ fullPage: true })
  expect(blocked.byteLength).toBeGreaterThan(10_000)

  await page.getByRole('button', { name: 'Open Results view' }).click()
  await expect(page.getByText('Run the arena first')).toBeVisible()
  const emptyResults = await page.screenshot({ fullPage: true })
  expect(emptyResults.byteLength).toBeGreaterThan(10_000)
})
