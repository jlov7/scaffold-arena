import { mkdir } from 'node:fs/promises'
import { resolve } from 'node:path'

import { expect, test } from '@playwright/test'

import { mockDefaultApi } from '../support/mockApi'

const DOCUMENTATION_OUTPUT_DIR = resolve(process.cwd(), '../docs/assets/screenshots/design-qa')

test('captures design QA evidence pack (desktop + mobile)', async ({ page }, testInfo) => {
  const captureDocumentationAssets = process.env.CAPTURE_DESIGN_QA_EVIDENCE === '1'
  if (captureDocumentationAssets) {
    await mkdir(DOCUMENTATION_OUTPUT_DIR, { recursive: true })
  }
  const outputPath = (filename: string) => (
    captureDocumentationAssets
      ? resolve(DOCUMENTATION_OUTPUT_DIR, filename)
      : testInfo.outputPath(filename)
  )
  await mockDefaultApi(page)

  await page.setViewportSize({ width: 1366, height: 900 })
  await page.goto('/arena')
  await page.screenshot({
    path: outputPath('arena-desktop.png'),
    fullPage: true,
  })

  await page.getByRole('button', { name: 'Open Results view' }).click()
  await page.screenshot({
    path: outputPath('results-desktop.png'),
    fullPage: true,
  })

  await page.getByRole('button', { name: 'Open History view' }).click()
  await page.screenshot({
    path: outputPath('history-desktop.png'),
    fullPage: true,
  })

  await page.getByRole('button', { name: 'Open Leaderboard view' }).click()
  await page.screenshot({
    path: outputPath('leaderboard-desktop.png'),
    fullPage: true,
  })

  await page.getByRole('button', { name: 'Open Settings view' }).click()
  await page.screenshot({
    path: outputPath('settings-desktop.png'),
    fullPage: true,
  })

  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/arena')
  await page.screenshot({
    path: outputPath('arena-mobile.png'),
    fullPage: true,
  })

  await expect(page.getByRole('heading', { name: 'SCAFFOLD ARENA' })).toBeVisible()
})
