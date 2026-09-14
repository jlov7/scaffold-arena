import { expect, test } from '@playwright/test'
import { resolve } from 'node:path'

import { fixturePack, mockWorkbenchV1 } from '../support/workbenchV1Mock'

test('captures intentional Workbench v1 desktop and mobile visual baselines', async ({ page }) => {
  await mockWorkbenchV1(page)
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto(`/workbench/design?study_pack_id=${fixturePack.study_pack_id}&study_pack_version=${fixturePack.version}`)
  await expect(page.locator('h1.sa-stage-heading')).toHaveText('Compare')
  await page.evaluate(() => document.fonts.ready.then(() => undefined))
  await expect(page).toHaveScreenshot('workbench-v1-design-desktop.png', { fullPage: true })
  if (process.env.CAPTURE_DOCUMENTATION_ASSETS === '1') {
    await page.screenshot({
      path: resolve(process.cwd(), '../docs/assets/screenshots/v1/workbench-v1-design-desktop.png'),
      fullPage: true,
    })
  }

  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await expect(page.locator('h1.sa-stage-heading')).toHaveText('Compare')
  await page.evaluate(() => document.fonts.ready.then(() => undefined))
  await expect(page).toHaveScreenshot('workbench-v1-studies-mobile.png', { fullPage: true })
  if (process.env.CAPTURE_DOCUMENTATION_ASSETS === '1') {
    await page.screenshot({
      path: resolve(process.cwd(), '../docs/assets/screenshots/v1/workbench-v1-studies-mobile.png'),
      fullPage: true,
    })
  }
})
