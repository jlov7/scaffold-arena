import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'

import { expect, test } from '@playwright/test'

import { mockDefaultApi } from '../support/mockApi'

const OUTPUT_DIR = resolve(process.cwd(), '../docs/assets/screenshots/design-qa')

test('captures design QA evidence pack (desktop + mobile)', async ({ page }) => {
  await mkdir(OUTPUT_DIR, { recursive: true })
  await mockDefaultApi(page)

  await page.setViewportSize({ width: 1366, height: 900 })
  await page.goto('/arena')
  await page.screenshot({
    path: resolve(OUTPUT_DIR, 'arena-desktop.png'),
    fullPage: true,
  })

  await page.getByRole('button', { name: 'Open Results view' }).click()
  await page.screenshot({
    path: resolve(OUTPUT_DIR, 'results-desktop.png'),
    fullPage: true,
  })

  await page.getByRole('button', { name: 'Open History view' }).click()
  await page.screenshot({
    path: resolve(OUTPUT_DIR, 'history-desktop.png'),
    fullPage: true,
  })

  await page.getByRole('button', { name: 'Open Leaderboard view' }).click()
  await page.screenshot({
    path: resolve(OUTPUT_DIR, 'leaderboard-desktop.png'),
    fullPage: true,
  })

  await page.getByRole('button', { name: 'Open Settings view' }).click()
  await page.screenshot({
    path: resolve(OUTPUT_DIR, 'settings-desktop.png'),
    fullPage: true,
  })

  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/arena')
  await page.screenshot({
    path: resolve(OUTPUT_DIR, 'arena-mobile.png'),
    fullPage: true,
  })

  await expect(page.getByRole('heading', { name: 'SCAFFOLD ARENA' })).toBeVisible()
})
