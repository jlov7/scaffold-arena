import { expect, test } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'

import { mockDefaultApi } from '../support/mockApi'

test.beforeEach(async ({ page }) => {
  await mockDefaultApi(page)
})

test('arena and settings have no critical/serious axe violations', async ({ page }) => {
  await page.goto('/arena')

  const arenaAxe = await new AxeBuilder({ page }).analyze()
  const arenaCritical = arenaAxe.violations.filter((v) =>
    ['critical', 'serious'].includes(v.impact ?? ''),
  )
  expect(arenaCritical, JSON.stringify(arenaCritical, null, 2)).toEqual([])

  await page.getByRole('button', { name: 'Open Settings view' }).click()
  const settingsAxe = await new AxeBuilder({ page }).analyze()
  const settingsCritical = settingsAxe.violations.filter((v) =>
    ['critical', 'serious'].includes(v.impact ?? ''),
  )
  expect(settingsCritical, JSON.stringify(settingsCritical, null, 2)).toEqual([])
})

test('critical controls meet WCAG target size minimum on mobile', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/arena')

  const controls = [
    { label: 'Open Arena view', locator: page.getByRole('button', { name: 'Open Arena view' }) },
    { label: 'Open History view', locator: page.getByRole('button', { name: 'Open History view' }) },
    {
      label: 'Open Leaderboard view',
      locator: page.getByRole('button', { name: 'Open Leaderboard view' }),
    },
    { label: 'Open Settings view', locator: page.getByRole('button', { name: 'Open Settings view' }) },
    { label: 'Open Results view', locator: page.getByRole('button', { name: 'Open Results view' }) },
    { label: 'Run arena', locator: page.getByRole('button', { name: 'Run arena', exact: true }) },
    { label: 'Take the tour', locator: page.getByRole('button', { name: 'Take the tour', exact: true }) },
    { label: 'Light theme', locator: page.getByRole('button', { name: 'Light theme', exact: true }) },
  ]

  for (const control of controls) {
    const { label, locator } = control
    if ((await locator.count()) === 0) continue
    await expect(locator).toBeVisible()
    const box = await locator.boundingBox()
    expect(box, `expected measurable target for ${label}`).not.toBeNull()
    expect(
      box!.height,
      `expected height >= 24px for ${label} per WCAG 2.2 target size`,
    ).toBeGreaterThanOrEqual(24)
    expect(
      box!.width,
      `expected width >= 24px for ${label} per WCAG 2.2 target size`,
    ).toBeGreaterThanOrEqual(24)
  }
})

test('reflow remains usable at 320px equivalent zoom width', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 900 })
  await page.goto('/arena')
  await expect(page.getByRole('heading', { name: 'SCAFFOLD ARENA' })).toBeVisible()

  const arenaOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  )
  expect(arenaOverflow).toBeLessThanOrEqual(2)

  const settingsButton = page.getByRole('button', { name: 'Open Settings view' })
  if ((await settingsButton.count()) > 0 && (await settingsButton.first().isVisible())) {
    await settingsButton.first().click()
  } else {
    await page.locator('summary', { hasText: 'More' }).click()
    await page.getByRole('button', { name: 'Open Settings view' }).click()
  }
  await expect(page.getByText('Settings & Preferences')).toBeVisible()
  const settingsOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  )
  expect(settingsOverflow).toBeLessThanOrEqual(2)
})
