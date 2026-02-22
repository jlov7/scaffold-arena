import { expect, test } from '@playwright/test'

import { mockDefaultApi } from '../support/mockApi'

test.beforeEach(async ({ page }) => {
  await mockDefaultApi(page)
})

test('resume deep-link journey restores prior run context', async ({ page }) => {
  await page.goto('/arena?run_id=run_hist_1')

  await expect(page.getByRole('heading', { name: 'Results workspace' })).toBeVisible()
  await expect(page.getByText('Role summary: Evaluator')).toBeVisible()
  await page.getByRole('button', { name: 'Open diagnostics lane' }).first().click()
  await expect(page.getByText('Output Diff')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Back to summary lane' })).toBeVisible()
})

test('history journey loads run and returns to actionable arena state', async ({ page }) => {
  await page.goto('/history')

  await page
    .getByRole('region', { name: 'Run history' })
    .getByRole('button')
    .first()
    .click()
  await page.getByRole('button', { name: 'Open Results view' }).click()

  await expect(
    page.getByRole('heading', { name: 'Results', exact: true }),
  ).toBeVisible()
  await expect(
    page.getByRole('button', { name: /export markdown and pdf report/i }),
  ).toHaveCount(1)
  await expect(page.getByRole('button', { name: /copy share link/i })).toHaveCount(1)
})

test('guided onboarding journey can be paused and resumed', async ({ page }) => {
  await page.goto('/arena')
  await expect(page.getByText('Getting started checklist')).toBeVisible()
  await page.getByRole('button', { name: 'Hide' }).click()
  await expect(page.getByText('Checklist hidden for a cleaner workspace.')).toBeVisible()
  await page.getByRole('button', { name: 'Resume checklist' }).click()
  await expect(page.getByText('Getting started checklist')).toBeVisible()
})

test('auth blocker journey routes to settings via help center', async ({ page }) => {
  await page.goto('/arena')
  await page.getByRole('button', { name: /^Help$/ }).click()
  const helpDialog = page.getByRole('dialog', { name: 'Help Center' })
  await expect(helpDialog).toBeVisible()
  await helpDialog.getByRole('button', { name: 'Open settings now' }).click()
  await expect(page).toHaveURL(/\/settings/)
})

test('results journey supports first autopsy walkthrough launch', async ({ page }) => {
  await page.goto('/history')
  await page
    .getByRole('region', { name: 'Run history' })
    .getByRole('button')
    .first()
    .click()
  await page.getByRole('button', { name: 'Open Results view' }).click()
  await expect(page.getByText('First autopsy walkthrough')).toBeVisible()
  await page.getByRole('button', { name: 'Start first autopsy' }).click()
  await expect(page.getByRole('button', { name: 'Close autopsy modal' })).toBeVisible()
})

test('advanced executive journey prioritizes export-first action ordering', async ({
  page,
}) => {
  await page.goto('/history')
  await page
    .getByRole('region', { name: 'Run history' })
    .getByRole('button')
    .first()
    .click()
  await page.getByRole('button', { name: 'Open Arena view' }).click()
  await page.getByRole('button', { name: 'Advanced', exact: true }).click()
  await page.getByRole('button', { name: 'Executive', exact: true }).click()

  const actions = page.getByRole('region', { name: 'Primary actions' }).getByRole('button')
  await expect(actions.nth(1)).toHaveText('Export report')
  await expect(actions.nth(2)).toHaveText('Run proof comparison')
})

test('persona journey cycles through role-tailored summaries', async ({ page }) => {
  await page.goto('/history')
  await page
    .getByRole('region', { name: 'Run history' })
    .getByRole('button')
    .first()
    .click()
  await page.getByRole('button', { name: 'Open Results view' }).click()

  for (const persona of ['Evaluator', 'Operator', 'Analyst', 'Executive'] as const) {
    await page.getByRole('button', { name: persona, exact: true }).click()
    await expect(page.getByText(`Role summary: ${persona}`)).toBeVisible()
  }
})

test('settings journey enforces clear-key confirmation guardrail', async ({
  page,
}) => {
  await page.goto('/settings')
  const keyInput = page.getByPlaceholder('sk-... or your provider API key')
  await keyInput.fill('sk-test-key')
  await expect(keyInput).toHaveValue('sk-test-key')

  page.once('dialog', async (dialog) => {
    await dialog.dismiss()
  })
  await page.getByRole('button', { name: 'Clear' }).click()
  await expect(keyInput).toHaveValue('sk-test-key')

  page.once('dialog', async (dialog) => {
    await dialog.accept()
  })
  await page.getByRole('button', { name: 'Clear' }).click()
  await expect(keyInput).toHaveValue('')
})

test('blocked-state journey can switch to safe fallback mode', async ({ page }) => {
  await page.goto('/arena')
  await expect(page.getByText('Safe fallback mode', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Enable safe fallback mode' }).click()
  await expect(page).toHaveURL(/\/history/)
})

test('mobile journey keeps navigation and setup discoverable', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/arena')
  await expect(page.getByRole('heading', { name: 'SCAFFOLD ARENA' })).toBeVisible()
  await page.getByRole('button', { name: 'Open Settings view' }).click()
  await expect(page.getByText('Settings & Preferences')).toBeVisible()
})
