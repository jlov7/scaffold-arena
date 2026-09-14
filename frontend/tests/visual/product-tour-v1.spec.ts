import { expect, test } from '@playwright/test'
import { resolve } from 'node:path'

import { mockWorkbenchV1 } from '../support/workbenchV1Mock'

type Surface = {
  id: string
  label: string
  route: string
  desktopFile: string
  mobileFile: string
  readyText: string
  altText: (viewport: 'desktop' | 'mobile') => string
  prepare?: (page: Parameters<typeof mockWorkbenchV1>[0]) => Promise<void>
}

const OUTPUT_DIR = resolve(process.cwd(), '../docs/assets/screenshots/v1/product-tour')

const SURFACES: Surface[] = [
  {
    id: 'harness-home-xray',
    label: 'Harness Home / X-Ray',
    route: '/workbench/xray',
    desktopFile: 'harness-home-xray-desktop.png',
    mobileFile: 'harness-home-xray-mobile.png',
    readyText: 'Captured source required',
    altText: (viewport) => `${viewport === 'desktop' ? 'Desktop' : 'Mobile'} blocked Harness Home / X-Ray showing Captured source required; inspection cannot discover or execute an uncaptured source.`,
  },
  {
    id: 'study-canvas',
    label: 'Study Canvas',
    route: '/workbench/studies',
    desktopFile: 'study-canvas-desktop.png',
    mobileFile: 'study-canvas-mobile.png',
    readyText: 'offline-demo-v1',
    altText: (viewport) => `${viewport === 'desktop' ? 'Desktop' : 'Mobile'} synthetic fixture Study Canvas showing offline-demo-v1 metadata and the not benchmark evidence boundary.`,
  },
  {
    id: 'run-cockpit',
    label: 'Run Cockpit',
    route: '/workbench/execute?experiment_id=fixture-created-experiment',
    desktopFile: 'run-cockpit-desktop.png',
    mobileFile: 'run-cockpit-mobile.png',
    readyText: 'Execution is blocked',
    altText: (viewport) => `${viewport === 'desktop' ? 'Desktop' : 'Mobile'} synthetic fixture Run Cockpit showing Execution HOLD because no durable preflight report or provider request exists.`,
  },
  {
    id: 'decision-canvas',
    label: 'Decision Canvas',
    route: '/workbench/analyze?experiment_id=fixture-created-experiment&execution_id=fixture-execution',
    desktopFile: 'decision-canvas-desktop.png',
    mobileFile: 'decision-canvas-mobile.png',
    readyText: 'No durable analysis report',
    altText: (viewport) => `${viewport === 'desktop' ? 'Desktop' : 'Mobile'} empty Decision Canvas showing no durable analysis report; no effect, winner, cost, or confidence is inferred.`,
  },
  {
    id: 'trace-counterfactual-lab',
    label: 'Trace / Counterfactual Lab',
    route: '/workbench/counterfactual',
    desktopFile: 'trace-counterfactual-desktop.png',
    mobileFile: 'trace-counterfactual-mobile.png',
    readyText: 'Provider-free fixture',
    altText: (viewport) => `${viewport === 'desktop' ? 'Desktop' : 'Mobile'} provider-free paired fixture replay in Trace / Counterfactual Lab showing HOLD, unknown usage, and no posted comment.`,
    prepare: async (page) => {
      await page.getByRole('button', { name: 'Run provider-free fixture replay' }).click()
      await expect(page.getByRole('heading', { name: 'Effect and uncertainty' })).toBeVisible()
      await page.getByRole('button', { name: 'Run Harness CI check' }).click()
      await expect(page.getByRole('heading', { name: 'Policy checks' })).toBeVisible()
      await expect(page.getByRole('status')).toContainText(/not posted a comment/i)
    },
  },
  {
    id: 'evidence-room',
    label: 'Evidence Room',
    route: '/workbench/evidence?execution_id=fixture-execution',
    desktopFile: 'evidence-room-desktop.png',
    mobileFile: 'evidence-room-mobile.png',
    readyText: 'No durable evidence or decision briefs',
    altText: (viewport) => `${viewport === 'desktop' ? 'Desktop' : 'Mobile'} empty Evidence Room showing Integrity is not truth and no durable evidence or decision briefs.`,
  },
]

async function preparePage(page: Parameters<typeof mockWorkbenchV1>[0], surface: Surface, viewport: 'desktop' | 'mobile') {
  const consoleErrors: string[] = []
  const pageErrors: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text())
  })
  page.on('pageerror', (error) => pageErrors.push(error.message))
  await page.route(/^https:\/\/fonts\.googleapis\.com\/.*/, (route) => route.fulfill({
    status: 200,
    contentType: 'text/css',
    body: '/* Product-tour capture uses stable local fallback fonts. */',
  }))
  await mockWorkbenchV1(page)
  await page.setViewportSize(viewport === 'desktop' ? { width: 1440, height: 900 } : { width: 390, height: 844 })
  await page.emulateMedia({ colorScheme: 'dark', reducedMotion: 'reduce' })
  await page.goto(surface.route)
  await expect(page).toHaveTitle(/Scaffold Arena/)
  await page.getByRole('button', { name: 'Lab', exact: true }).click()
  await expect(page.locator('h1.sa-stage-heading')).toHaveText(surface.label)
  await expect(page.getByText(surface.readyText, { exact: true })).toBeVisible()
  await expect(page.locator('body')).not.toBeEmpty()
  await expect(page.locator('vite-error-overlay, #vite-error-overlay, [data-vite-error-overlay]')).toHaveCount(0)
  await page.evaluate(() => document.fonts.ready.then(() => undefined))
  if (surface.prepare) await surface.prepare(page)
  await page.waitForLoadState('networkidle')
  if (surface.id === 'run-cockpit') {
    await expect(page.getByRole('heading', { name: 'No durable executions yet' })).toBeVisible()
  }
  await page.waitForTimeout(100)
  return { consoleErrors, pageErrors }
}

for (const surface of SURFACES) {
  for (const viewport of ['desktop', 'mobile'] as const) {
    test(`${surface.label} ${viewport} product-tour capture is fixture-bounded`, async ({ page }) => {
      const diagnostics = await preparePage(page, surface, viewport)
      expect(diagnostics.consoleErrors).toEqual([])
      expect(diagnostics.pageErrors).toEqual([])
      const filename = viewport === 'desktop' ? surface.desktopFile : surface.mobileFile
      await expect(page).toHaveScreenshot(`product-tour-${surface.id}-${viewport}.png`, { fullPage: true })
      if (process.env.CAPTURE_DOCUMENTATION_ASSETS === '1') {
        await page.screenshot({ path: resolve(OUTPUT_DIR, filename), fullPage: true, caret: 'hide', animations: 'disabled', scale: 'css' })
      }
    })
  }
}

test('product-tour capture set covers exactly six surfaces at desktop and mobile viewports', () => {
  expect(SURFACES).toHaveLength(6)
  expect([...new Set(SURFACES.map((surface) => surface.id))]).toHaveLength(6)
  expect(SURFACES.flatMap((surface) => [surface.desktopFile, surface.mobileFile])).toHaveLength(12)
})
