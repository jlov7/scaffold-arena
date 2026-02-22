import { test, expect, type Page } from '@playwright/test'

import { mockDefaultApi } from '../support/mockApi'

test.beforeEach(async ({ page }) => {
  await mockDefaultApi(page)
})

async function assertShellContract(page: Page) {
  await expect(page.getByRole('heading', { name: 'SCAFFOLD ARENA' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Help', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Take the tour', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: /theme$/i })).toBeVisible()

  await expect(page.getByRole('button', { name: 'Open Arena view' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Open Results view' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Open History view' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Open Leaderboard view' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Open Settings view' })).toBeVisible()

  await expect(page.getByText(/^Home\s+\/\s+/)).toBeVisible()
}

test('primary navigation switches between views and updates URL', async ({ page }) => {
  await page.goto('/arena')

  await assertShellContract(page)
  await page.getByRole('button', { name: 'Results' }).click()
  await expect(page).toHaveURL(/\/results/)
  await expect(page.getByRole('heading', { name: 'Results workspace' })).toBeVisible()
  await assertShellContract(page)
  await page.getByRole('button', { name: 'Open History view' }).click()
  await expect(page).toHaveURL(/\/history/)
  await expect(page.getByRole('region', { name: 'Run history' })).toBeVisible()
  await assertShellContract(page)

  await page.getByRole('button', { name: 'Open Leaderboard view' }).click()
  await expect(page).toHaveURL(/\/leaderboard/)
  await expect(page.getByRole('region', { name: 'Leaderboard' })).toBeVisible()
  await assertShellContract(page)

  await page.getByRole('button', { name: 'Open Settings view' }).click()
  await expect(page).toHaveURL(/\/settings/)
  await expect(page.getByText('Settings & Preferences')).toBeVisible()
  await assertShellContract(page)
})
