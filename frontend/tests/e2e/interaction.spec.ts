import { expect, test, type Locator } from '@playwright/test'

import { mockDefaultApi } from '../support/mockApi'

test.beforeEach(async ({ page }) => {
  await mockDefaultApi(page)
})

async function moveToConfigureLane(page: import('@playwright/test').Page): Promise<void> {
  const candidates = [
    page.getByRole('button', { name: 'Start with configure lane' }),
    page.getByRole('button', { name: 'Go to configure lane' }),
    page.getByRole('button', { name: /configure lane/i }),
  ]
  for (const locator of candidates) {
    if (await locator.first().isVisible()) {
      await locator.first().click()
      return
    }
  }
}

test('keyboard shortcut opens and closes shortcut overlay', async ({ page }) => {
  await page.goto('/arena')
  await page.getByRole('heading', { name: 'SCAFFOLD ARENA' }).click()
  await page.keyboard.press('Shift+Slash')
  await expect(page.getByRole('dialog', { name: /keyboard/i })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog', { name: /keyboard/i })).toBeHidden()
})

test('pointer interaction reveals score breakdown tooltip', async ({ page }) => {
  await page.goto('/history')
  await page
    .getByRole('region', { name: 'Run history' })
    .getByRole('button')
    .first()
    .click()
  await page.getByRole('button', { name: 'Open Results view' }).click()
  await expect(page.getByRole('heading', { name: 'Results', exact: true })).toBeVisible()

  const scoreButton = page
    .locator('table')
    .getByRole('button')
    .filter({ hasText: /\d+\.\d+/ })
    .first()

  await scoreButton.hover()
  await expect(page.getByRole('tooltip')).toBeVisible()
})

test('help center routes primary action to settings for auth blockers', async ({ page }) => {
  await page.route('**/api/runs', async (route) => {
    await route.fulfill({
      status: 401,
      contentType: 'text/plain',
      body: 'unauthorized',
    })
  })
  await page.goto('/arena')
  await moveToConfigureLane(page)
  await page.getByRole('button', { name: /Run from configure lane|Run arena/i }).first().click()
  await page.getByRole('button', { name: /^Help$/ }).click()
  const helpDialog = page.getByRole('dialog', { name: 'Help Center' })
  await expect(helpDialog).toBeVisible()
  await helpDialog.getByRole('button', { name: 'Open settings now' }).click()
  await expect(page).toHaveURL(/\/settings/)
})

test('keyboard h opens help center for fast recovery flow', async ({ page }) => {
  await page.goto('/arena')
  await page.getByRole('heading', { name: 'SCAFFOLD ARENA' }).click()
  await page.keyboard.press('h')
  await expect(page.getByRole('dialog', { name: 'Help Center' })).toBeVisible()
})

test('explain this screen opens contextual help from route intro', async ({
  page,
}) => {
  await page.goto('/arena')
  await page.getByRole('button', { name: 'Explain this screen' }).click()
  await expect(page.getByRole('dialog', { name: 'Help Center' })).toBeVisible()
})

test('help dialog is keyboard operable and returns focus to trigger', async ({
  page,
}) => {
  await page.goto('/arena')
  const helpButton = page.getByRole('button', { name: 'Help', exact: true })
  await helpButton.focus()
  await page.keyboard.press('Enter')

  const helpDialog = page.getByRole('dialog', { name: 'Help Center' })
  await expect(helpDialog).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(helpDialog).toBeHidden()
  await expect(helpButton).toBeFocused()
})

test('mobile tap targets stay comfortably large on critical controls', async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem('scaffold_arena_tour_seen', '1')
    window.localStorage.setItem('scaffold_arena_experience_mode', 'advanced')
    window.localStorage.setItem('scaffold_arena_last_view', '/arena')
  })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/arena')
  await page.waitForLoadState('networkidle')
  await expect(page.getByRole('heading', { name: 'SCAFFOLD ARENA' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Help', exact: true })).toBeVisible()

  async function expectLocatorMinHeight(
    label: string,
    locator: Locator,
    minHeight: number = 43,
  ): Promise<void> {
    const target = locator.first()
    await expect(target, `${label} should be visible`).toBeVisible()
    const box = await target.boundingBox()
    expect(box, `${label} should have a measurable box`).not.toBeNull()
    expect(box!.height, `${label} height should be >= ${minHeight}px`).toBeGreaterThanOrEqual(minHeight)
  }

  await expectLocatorMinHeight('Help', page.getByRole('button', { name: 'Help', exact: true }))
  await expectLocatorMinHeight('Take the tour', page.getByRole('button', { name: 'Take the tour', exact: true }))
  await expectLocatorMinHeight('Theme toggle', page.getByRole('button', { name: /theme$/i }))

  await expectLocatorMinHeight('Open Arena view', page.getByRole('button', { name: 'Open Arena view' }))
  await expectLocatorMinHeight('Open Results view', page.getByRole('button', { name: 'Open Results view' }))
  await expectLocatorMinHeight('Open History view', page.getByRole('button', { name: 'Open History view' }))
  await expectLocatorMinHeight('Open Leaderboard view', page.getByRole('button', { name: 'Open Leaderboard view' }))
  await expectLocatorMinHeight('Open Settings view', page.getByRole('button', { name: 'Open Settings view' }))

  const primaryActions = page.getByRole('region', { name: 'Primary actions' })
  await expectLocatorMinHeight('Run arena', primaryActions.getByRole('button', { name: 'Run arena' }))
  const compareButton = primaryActions.getByRole('button', { name: 'Run proof comparison' })
  if ((await compareButton.count()) > 0) {
    await expectLocatorMinHeight('Run proof comparison', compareButton)
  }
  const exportButton = primaryActions.getByRole('button', { name: 'Export report' })
  if ((await exportButton.count()) > 0) {
    await expectLocatorMinHeight('Export report', exportButton)
  }
  const shareButton = primaryActions.getByRole('button', { name: 'Share run' })
  if ((await shareButton.count()) > 0) {
    await expectLocatorMinHeight('Share run', shareButton)
  }

  await page.getByRole('button', { name: 'Take the tour' }).click()
  await expectLocatorMinHeight('Skip', page.getByRole('button', { name: 'Skip' }))
  await expectLocatorMinHeight('Next', page.getByRole('button', { name: 'Next' }))
})

test('mobile help and guided tour content remains readable without horizontal overflow', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/arena')

  await page.getByRole('button', { name: 'Help', exact: true }).click()
  const helpDialog = page.getByRole('dialog', { name: 'Help Center' })
  await expect(helpDialog).toBeVisible()
  await expect(helpDialog.getByText(/success playbook|recovery playbook/i)).toBeVisible()

  const helpOverflow = await helpDialog.evaluate((el) => el.scrollWidth - el.clientWidth)
  expect(helpOverflow).toBeLessThanOrEqual(2)

  await helpDialog.evaluate((el) => {
    el.scrollTop = el.scrollHeight
  })
  await expect(helpDialog.getByText(/canonical run flow/i)).toBeVisible()
  await page.keyboard.press('Escape')

  await page.getByRole('button', { name: 'Take the tour', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'Guided Tour' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Skip' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Next' })).toBeVisible()
})

test('mobile-first progress component appears with compact step status', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/arena')

  await expect(
    page.getByRole('region', { name: 'Mobile journey progress' }),
  ).toBeVisible()
  await expect(page.getByText(/Step 1 of 4/i)).toBeVisible()
})

test('results workspace defaults to compact mode on mobile breakpoints', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/results')
  await expect(
    page.getByRole('button', { name: 'Disable compact mode' }),
  ).toBeVisible()
})

test('mobile contextual sticky CTA adapts outside arena workspace', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/settings')

  const sticky = page.getByRole('button', {
    name: /Go to task setup|Select model now|Run arena now|Open results workspace|Run proof comparison|Run business-case proof|Export report|Export decision brief|Open executive summary|Open evidence workspace|Run reliability pass|Run ops comparison|Export analysis report/i,
  })
  await expect(sticky.first()).toBeVisible()
})

test('guided mode supports checklist hide and resume', async ({ page }) => {
  await page.goto('/arena')
  await expect(page.getByText('Getting started checklist')).toBeVisible()

  await page.getByRole('button', { name: 'Hide' }).click()
  await expect(
    page.getByText('Checklist hidden for a cleaner workspace.'),
  ).toBeVisible()

  await page.getByRole('button', { name: 'Resume checklist' }).click()
  await expect(page.getByText('Getting started checklist')).toBeVisible()
})

test('results summary adapts to selected user profile', async ({ page }) => {
  await page.goto('/history')
  await page
    .getByRole('region', { name: 'Run history' })
    .getByRole('button')
    .first()
    .click()
  await page.getByRole('button', { name: 'Open Results view' }).click()

  await expect(page.getByText('Role summary: Evaluator')).toBeVisible()
  await expect(page.getByText('Evaluator readout')).toBeVisible()

  await page.getByRole('button', { name: 'Executive', exact: true }).click()
  await expect(page.getByText('Role summary: Executive')).toBeVisible()
  await expect(page.getByText('Executive readout')).toBeVisible()
})

test('executive profile prioritizes export-first CTA ordering in advanced mode', async ({
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

  const ctaButtons = page.getByRole('region', { name: 'Primary actions' }).getByRole('button')
  await expect(ctaButtons.nth(1)).toHaveText('Export report')
  await expect(ctaButtons.nth(2)).toHaveText('Run proof comparison')
})

test('results workspace provides first autopsy walkthrough and launch action', async ({
  page,
}) => {
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

test('all personas surface tailored results and help guidance', async ({ page }) => {
  await page.goto('/history')
  await page
    .getByRole('region', { name: 'Run history' })
    .getByRole('button')
    .first()
    .click()
  await page.getByRole('button', { name: 'Open Results view' }).click()

  const personas = ['Evaluator', 'Operator', 'Analyst', 'Executive'] as const
  for (const persona of personas) {
    await page.getByRole('button', { name: persona, exact: true }).click()
    await expect(page.getByText(`Role summary: ${persona}`)).toBeVisible()

    await page.getByRole('button', { name: /^Help$/ }).click()
    const helpDialog = page.getByRole('dialog', { name: 'Help Center' })
    await expect(helpDialog.getByText(`Role path: ${persona}`)).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(helpDialog).toBeHidden()
  }
})

test('clearing API key requires explicit confirmation guardrail', async ({ page }) => {
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
