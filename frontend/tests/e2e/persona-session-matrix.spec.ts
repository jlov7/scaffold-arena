import { expect, test, type Page } from '@playwright/test'

import { mockDefaultApi } from '../support/mockApi'

const PERSONAS = ['Evaluator', 'Operator', 'Analyst', 'Executive'] as const
const SESSION_MODES = ['guided_results', 'advanced_arena', 'help_role'] as const

async function hydrateHistoricalRun(page: Page) {
  await page.goto('/history')
  await page
    .getByRole('region', { name: 'Run history' })
    .getByRole('button')
    .first()
    .click()
}

for (const persona of PERSONAS) {
  for (const mode of SESSION_MODES) {
    test(`persona session proxy: ${persona} / ${mode}`, async ({ page }) => {
      await mockDefaultApi(page)
      await hydrateHistoricalRun(page)
      await page.getByRole('button', { name: persona, exact: true }).click()

      if (mode === 'guided_results') {
        await page.getByRole('button', { name: 'Guided', exact: true }).click()
        await page.getByRole('button', { name: 'Open Results view' }).click()
        await expect(page.getByText(`Role summary: ${persona}`)).toBeVisible()
        return
      }

      if (mode === 'advanced_arena') {
        await page.getByRole('button', { name: 'Advanced', exact: true }).click()
        await page.getByRole('button', { name: 'Open Arena view' }).click()
        await expect(
          page.getByRole('region', { name: 'Primary actions' }),
        ).toBeVisible()
        return
      }

      await page.getByRole('button', { name: 'Help', exact: true }).click()
      const helpDialog = page.getByRole('dialog', { name: 'Help Center' })
      await expect(helpDialog.getByText(`Role path: ${persona}`)).toBeVisible()
      await page.keyboard.press('Escape')
      await expect(helpDialog).toBeHidden()
    })
  }
}
