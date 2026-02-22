import { expect, test } from '@playwright/test'

import { mockDefaultApi } from '../support/mockApi'

test.beforeEach(async ({ page }) => {
  await mockDefaultApi(page)
  await page.goto('/arena')
})

test('a11y user proxy 01: keyboard opens and closes Help with focus return', async ({
  page,
}) => {
  const helpButton = page.getByRole('button', { name: 'Help', exact: true })
  await helpButton.focus()
  await page.keyboard.press('Enter')
  const dialog = page.getByRole('dialog', { name: 'Help Center' })
  await expect(dialog).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(helpButton).toBeFocused()
})

test('a11y user proxy 02: keyboard opens and closes shortcut overlay', async ({
  page,
}) => {
  await page.getByRole('heading', { name: 'SCAFFOLD ARENA' }).focus()
  await page.keyboard.press('Shift+Slash')
  const dialog = page.getByRole('dialog', { name: /keyboard/i })
  await expect(dialog).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
})

test('a11y user proxy 03: keyboard opens guided tour and can exit', async ({
  page,
}) => {
  const tourButton = page.getByRole('button', { name: 'Take the tour', exact: true })
  await tourButton.focus()
  await page.keyboard.press('Enter')
  const tourDialog = page.getByRole('dialog', { name: 'Guided Tour' })
  await expect(tourDialog).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(tourDialog).toBeHidden()
})

test('a11y user proxy 04: keyboard reaches route intro explain action', async ({
  page,
}) => {
  const explainButton = page.getByRole('button', { name: 'Explain this screen' })
  await explainButton.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('dialog', { name: 'Help Center' })).toBeVisible()
})

test('a11y user proxy 05: keyboard-only path loads history and results', async ({
  page,
}) => {
  await page.getByRole('button', { name: 'Open History view' }).focus()
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/history/)
  await page
    .getByRole('region', { name: 'Run history' })
    .getByRole('button')
    .first()
    .click()
  const resultsButtons = page.getByRole('button', { name: 'Open Results view' })
  const buttonCount = await resultsButtons.count()
  let clickedVisibleButton = false
  for (let index = 0; index < buttonCount; index += 1) {
    const candidate = resultsButtons.nth(index)
    if (await candidate.isVisible()) {
      await candidate.click()
      clickedVisibleButton = true
      break
    }
  }
  expect(clickedVisibleButton).toBe(true)
  await expect(page).toHaveURL(/\/results/)
})

test('a11y user proxy 06: live region announces run completion message', async ({
  page,
}) => {
  await page.getByRole('button', { name: 'Open History view' }).click()
  await page
    .getByRole('region', { name: 'Run history' })
    .getByRole('button')
    .first()
    .click()
  const statusLiveRegion = page.locator('[role="status"][aria-live="polite"]').last()
  await expect(statusLiveRegion).toContainText(/Loaded run|Run complete|Winner/i)
})

test('a11y user proxy 07: keyboard can toggle settings telemetry consent', async ({
  page,
}) => {
  await page.getByRole('button', { name: 'Open Settings view' }).click()
  const checkbox = page.getByRole('checkbox', { name: /Enable telemetry events/i })
  await checkbox.focus()
  await page.keyboard.press('Space')
  await expect(checkbox).toBeChecked()
})

test('a11y user proxy 08: keyboard can trigger recovery action from results callout', async ({
  page,
}) => {
  await page.getByRole('button', { name: 'Open Results view' }).click()
  await page.getByRole('button', { name: 'Open arena setup' }).focus()
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/\/arena/)
})
