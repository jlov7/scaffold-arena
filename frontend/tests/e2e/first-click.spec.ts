import { expect, test } from '@playwright/test'

import { mockDefaultApi } from '../support/mockApi'

test('first-click IA test matrix', async ({ page }) => {
  await mockDefaultApi(page)
  await page.goto('/arena')

  // Task 1: reach Settings in one click.
  await page.getByRole('button', { name: 'Open Settings view' }).click()
  await expect(page).toHaveURL(/\/settings/)
  await expect(page.getByText('Settings & Preferences')).toBeVisible()

  // Task 2: reach History in one click.
  await page.getByRole('button', { name: 'Open History view' }).click()
  await expect(page).toHaveURL(/\/history/)
  await expect(page.getByRole('region', { name: 'Run history' })).toBeVisible()

  // Task 3: reach Leaderboard in one click.
  await page.getByRole('button', { name: 'Open Leaderboard view' }).click()
  await expect(page).toHaveURL(/\/leaderboard/)
  await expect(page.getByRole('region', { name: 'Leaderboard' })).toBeVisible()

  // Task 4: reach Results in one click.
  await page.getByRole('button', { name: 'Open Results view' }).click()
  await expect(page).toHaveURL(/\/results/)
  await expect(
    page.getByRole('heading', { name: 'Results workspace' }),
  ).toBeVisible()
})

test('first-click IA still works at 320px with progressive nav', async ({ page }) => {
  await mockDefaultApi(page)
  await page.setViewportSize({ width: 320, height: 712 })
  await page.goto('/arena')

  // Primary destinations remain immediate.
  await page.getByRole('button', { name: 'Open Results view' }).click()
  await expect(page).toHaveURL(/\/results/)

  // Secondary destinations remain one-step through More.
  await page.locator('summary', { hasText: 'More' }).click()
  await page.getByRole('button', { name: 'Open Settings view' }).click()
  await expect(page).toHaveURL(/\/settings/)
})
