import { expect, test } from '@playwright/test'

import { mockDefaultApi } from '../support/mockApi'

const VIEWPORTS = [
  { name: 'small-mobile-320', width: 320, height: 712 },
  { name: 'small-mobile-360', width: 360, height: 780 },
  { name: 'iphone14-390', width: 390, height: 844 },
  { name: 'mobile-plus-412', width: 412, height: 915 },
  { name: 'tablet-768', width: 768, height: 1024 },
  { name: 'tablet-1024', width: 1024, height: 1366 },
]

for (const viewport of VIEWPORTS) {
  test(`layout remains usable at ${viewport.name}`, async ({ page }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height })
    await mockDefaultApi(page)

    await page.goto('/arena')
    await expect(page.getByRole('heading', { name: 'SCAFFOLD ARENA' })).toBeVisible()

    const overflow = await page.evaluate(() =>
      document.documentElement.scrollWidth - window.innerWidth,
    )
    expect(overflow).toBeLessThanOrEqual(2)

    const settingsButton = page.getByRole('button', { name: 'Open Settings view' })
    if ((await settingsButton.count()) > 0 && (await settingsButton.first().isVisible())) {
      await settingsButton.first().click()
    } else {
      await page.locator('summary', { hasText: 'More' }).click()
      await page.getByRole('button', { name: 'Open Settings view' }).click()
    }
    await expect(page.getByText('Settings & Preferences')).toBeVisible()
  })
}

test('progressive mobile nav exposes secondary views behind More menu at 320px', async ({
  page,
}) => {
  await page.setViewportSize({ width: 320, height: 712 })
  await mockDefaultApi(page)
  await page.goto('/arena')

  await expect(page.getByRole('button', { name: 'Open Arena view' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Open Results view' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Open History view' })).toHaveCount(0)

  await page.getByText('More').click()
  await page.getByRole('button', { name: 'Open History view' }).click()
  await expect(page).toHaveURL(/\/history/)
  await expect(page.getByRole('region', { name: 'Run history' })).toBeVisible()
})
