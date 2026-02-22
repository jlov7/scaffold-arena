import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { expect, test } from '@playwright/test'

import {
  attachDebugOnFailure,
  getDebugState,
  getWatermarkText,
  waitForFonts,
  waitForSettlement,
} from '../support/visual-helpers'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)

const TEST_URL = '/constellation?seed=42&static=1&ticks=600&debug=1'
const FREEZE_CSS = resolve(__dirname, '../support/visual-freeze.css')

test.afterEach(async ({ page }, testInfo) => {
  await attachDebugOnFailure(page, testInfo)
})

test.describe('Constellation Visual Verification', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto(TEST_URL)
    await waitForFonts(page)
    await waitForSettlement(page)
  })

  /* ------------------------------------------------------------ */
  /*  Geometry assertions                                          */
  /* ------------------------------------------------------------ */

  test('geometry: no overlapping nodes', async ({ page }) => {
    const debug = await getDebugState(page)
    expect(debug.overlaps).toHaveLength(0)
  })

  test('geometry: all nodes within canvas bounds', async ({ page }) => {
    const debug = await getDebugState(page)
    expect(debug.clipped).toHaveLength(0)
  })

  test('geometry: no NaN or Infinity in coordinates', async ({ page }) => {
    const debug = await getDebugState(page)
    for (const node of debug.nodes) {
      expect(Number.isFinite(node.x), `${node.id}.x is not finite`).toBe(true)
      expect(Number.isFinite(node.y), `${node.id}.y is not finite`).toBe(true)
      expect(Number.isFinite(node.r), `${node.id}.r is not finite`).toBe(true)
    }
  })

  test('geometry: no zero-sized elements', async ({ page }) => {
    const debug = await getDebugState(page)
    for (const node of debug.nodes) {
      expect(node.r, `${node.id} has zero radius`).toBeGreaterThan(0)
    }
  })

  test('geometry: canvas DPR scaling is correct', async ({ page }) => {
    const debug = await getDebugState(page)
    expect(debug.canvas.w).toBe(debug.css.w * debug.dpr)
    expect(debug.canvas.h).toBe(debug.css.h * debug.dpr)
  })

  test('geometry: expected node count (8 agents)', async ({ page }) => {
    const debug = await getDebugState(page)
    expect(debug.nodes).toHaveLength(8)
  })

  test('geometry: simulation settled', async ({ page }) => {
    const debug = await getDebugState(page)
    expect(debug.settled).toBe(true)
  })

  /* ------------------------------------------------------------ */
  /*  Screenshot regression                                        */
  /* ------------------------------------------------------------ */

  test('screenshot: deterministic visual output', async ({ page }) => {
    await expect(page.locator('#constellation')).toHaveScreenshot(
      'constellation-seed42.png',
      {
        maxDiffPixelRatio: 0.01,
        animations: 'disabled',
        stylePath: FREEZE_CSS,
      },
    )
  })

  /* ------------------------------------------------------------ */
  /*  Watermark verification                                       */
  /* ------------------------------------------------------------ */

  test('watermark: displays correct metadata', async ({ page }) => {
    const text = await getWatermarkText(page)
    expect(text).toContain('seed:42')
    expect(text).toContain('DPR:')
    expect(text).toContain('SHA:')
    expect(text).toMatch(/\d+x\d+/) // viewport dimensions
  })

  test('watermark: DPR matches test environment', async ({ page }) => {
    const text = await getWatermarkText(page)
    // Visual project runs with deviceScaleFactor: 2
    expect(text).toContain('DPR:2')
  })
})
