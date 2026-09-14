import { expect, test } from '@playwright/test'

import { mockDefaultApi } from '../support/mockApi'

function expectPng(image: Buffer, minimumWidth: number, minimumHeight: number) {
  expect(image.subarray(1, 4).toString()).toBe('PNG')
  expect(image.readUInt32BE(16)).toBeGreaterThanOrEqual(minimumWidth)
  expect(image.readUInt32BE(20)).toBeGreaterThanOrEqual(minimumHeight)
}

test('captures major route snapshots (desktop)', async ({ page }) => {
  await mockDefaultApi(page)
  await page.setViewportSize({ width: 1280, height: 800 })

  await page.goto('/arena')
  const arena = await page.screenshot({ fullPage: true })
  expectPng(arena, 1280, 800)

  await page.getByRole('button', { name: 'Open History view' }).click()
  const history = await page.screenshot({ fullPage: true })
  expectPng(history, 1280, 800)

  await page.getByRole('button', { name: 'Open Leaderboard view' }).click()
  const leaderboard = await page.screenshot({ fullPage: true })
  expectPng(leaderboard, 1280, 800)

  await page.getByRole('button', { name: 'Open Settings view' }).click()
  const settings = await page.screenshot({ fullPage: true })
  expectPng(settings, 1280, 800)
})

test('captures major route snapshots (mobile)', async ({ page }) => {
  await mockDefaultApi(page)
  await page.setViewportSize({ width: 390, height: 844 })

  await page.goto('/arena')
  const arena = await page.screenshot({ fullPage: true })
  expectPng(arena, 390, 844)

  await page.getByRole('button', { name: 'Open Settings view' }).click()
  const settings = await page.screenshot({ fullPage: true })
  expectPng(settings, 390, 844)
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
  const configureButton = page.getByRole('button', { name: 'Start with configure lane' })
  await expect(configureButton).toBeVisible()
  await configureButton.click()
  const runButton = page.getByRole('button', { name: 'Run from configure lane' })
  await expect(runButton).toBeEnabled()
  await runButton.click()
  await expect(page.getByRole('alert').filter({ hasText: /Failed to start run/i }).first()).toBeVisible()
  await expect(page.getByText('Safe fallback mode', { exact: true })).toBeVisible()
  const blocked = await page.screenshot({ fullPage: true })
  expectPng(blocked, 1280, 800)

  await page.getByRole('button', { name: 'Open Results view' }).click()
  await expect(page.getByText('Run the arena first')).toBeVisible()
  const emptyResults = await page.screenshot({ fullPage: true })
  expectPng(emptyResults, 1280, 800)
})
