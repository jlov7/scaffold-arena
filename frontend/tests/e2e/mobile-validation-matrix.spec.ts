import { expect, test, type Page } from '@playwright/test'

import { mockDefaultApi } from '../support/mockApi'

const DEVICES = [
  { name: 'iphone14-390', width: 390, height: 844 },
  { name: 'small-android-360', width: 360, height: 780 },
  { name: 'small-mobile-320', width: 320, height: 712 },
] as const

const JOURNEYS = [
  'setup_and_navigation',
  'help_and_recovery',
  'results_review',
  'settings_controls',
] as const

async function openNavView(page: Page, label: string): Promise<void> {
  const nav = page.getByRole('navigation', { name: 'Primary' })
  await expect(nav).toBeVisible()

  const candidateLocators = [
    nav.getByRole('button', { name: `Open ${label} view` }),
    nav.getByRole('button', { name: label, exact: true }),
  ]

  for (const locator of candidateLocators) {
    const count = await locator.count()
    for (let index = 0; index < count; index += 1) {
      const candidate = locator.nth(index)
      if (await candidate.isVisible()) {
        await candidate.click()
        return
      }
    }
  }

  const moreTrigger = nav.locator('summary', { hasText: 'More' })
  if (await moreTrigger.first().isVisible()) {
    await moreTrigger.first().click()
    const menuCandidate =
      nav.getByRole('button', { name: `Open ${label} view` }).first()
    if (await menuCandidate.isVisible()) {
      await menuCandidate.click()
      return
    }
    const menuTextCandidate = nav.getByRole('button', { name: label, exact: true }).first()
    if (await menuTextCandidate.isVisible()) {
      await menuTextCandidate.click()
      return
    }
    return
  }
  throw new Error(`Unable to open ${label} view from mobile navigation.`)
}

async function openSettings(page: Page): Promise<void> {
  await openNavView(page, 'Settings')
}

for (const device of DEVICES) {
  for (const journey of JOURNEYS) {
    test(`mobile validation proxy: ${device.name} / ${journey}`, async ({
      page,
    }) => {
      await page.setViewportSize({ width: device.width, height: device.height })
      await mockDefaultApi(page)
      await page.goto('/arena')

      if (journey === 'setup_and_navigation') {
        await expect(page.getByRole('heading', { name: 'SCAFFOLD ARENA' })).toBeVisible()
        await expect(
          page.getByRole('region', { name: 'Mobile journey progress' }),
        ).toBeVisible()
        const overflow = await page.evaluate(
          () => document.documentElement.scrollWidth - window.innerWidth,
        )
        expect(overflow).toBeLessThanOrEqual(2)
        return
      }

      if (journey === 'help_and_recovery') {
        await page.getByRole('button', { name: 'Help', exact: true }).click()
        const helpDialog = page.getByRole('dialog', { name: 'Help Center' })
        await expect(helpDialog).toBeVisible()
        await expect(helpDialog.getByText('Extraction recovery playbook')).toBeVisible()
        return
      }

      if (journey === 'results_review') {
        await openNavView(page, 'History')
        await page
          .getByRole('region', { name: 'Run history' })
          .getByRole('button')
          .first()
          .click()
        await openNavView(page, 'Results')
        await expect(page.getByRole('heading', { name: 'Results', exact: true })).toBeVisible()
        await expect(page.getByText('Role summary: Evaluator')).toBeVisible()
        return
      }

      await openSettings(page)
      await expect(page.getByText('Settings & Preferences')).toBeVisible()
      await expect(
        page
          .getByRole('button', {
            name: /Go to task setup|Run arena now|Open results workspace|Export report|Open executive summary/i,
          })
          .first(),
      ).toBeVisible()
    })
  }
}
