import { expect, test } from '@playwright/test'

import { mockDefaultApi } from '../support/mockApi'

test.beforeEach(async ({ page }) => {
  await mockDefaultApi(page)
  await page.goto('/arena')
})

test('tree findability: top 8 intents resolve with first-click success', async ({
  page,
}) => {
  // 1) Find help
  await page.getByRole('button', { name: 'Help', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'Help Center' })).toBeVisible()
  await page.keyboard.press('Escape')

  // 2) Start tour
  await page.getByRole('button', { name: 'Take the tour', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'Guided Tour' })).toBeVisible()
  await page.keyboard.press('Escape')

  // 3) Open settings
  await page.getByRole('button', { name: 'Open Settings view' }).click()
  await expect(page).toHaveURL(/\/settings/)
  await expect(page.getByText('Settings & Preferences')).toBeVisible()

  // 4) Review results workspace
  await page.getByRole('button', { name: 'Open Results view' }).click()
  await expect(page).toHaveURL(/\/results/)
  await expect(page.getByRole('heading', { name: 'Results workspace' })).toBeVisible()

  // 5) Open history
  await page.getByRole('button', { name: 'Open History view' }).click()
  await expect(page).toHaveURL(/\/history/)
  await expect(page.getByRole('region', { name: 'Run history' })).toBeVisible()

  // 6) Open leaderboard
  await page.getByRole('button', { name: 'Open Leaderboard view' }).click()
  await expect(page).toHaveURL(/\/leaderboard/)
  await expect(page.getByRole('region', { name: 'Leaderboard' })).toBeVisible()

  // 7) Return to arena run action
  await page.getByRole('button', { name: 'Open Arena view' }).click()
  await expect(page).toHaveURL(/\/arena/)
  await expect(
    page.getByRole('region', { name: 'Primary actions' }).getByRole('button', { name: 'Run arena' }),
  ).toBeVisible()

  // 8) Reach export action from a historical run context
  await page.getByRole('button', { name: 'Open History view' }).click()
  await page
    .getByRole('region', { name: 'Run history' })
    .getByRole('button')
    .first()
    .click()
  await page.getByRole('button', { name: 'Open Arena view' }).click()
  const advancedMode = page.getByRole('button', { name: 'Advanced', exact: true })
  if ((await advancedMode.count()) > 0) {
    await advancedMode.click()
  }
  await expect(
    page.getByRole('region', { name: 'Primary actions' }).getByRole('button', { name: 'Export report' }),
  ).toBeVisible()
})
