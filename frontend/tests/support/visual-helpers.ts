import type { Page, TestInfo } from '@playwright/test'

/**
 * Wait for all web fonts to finish loading.
 * Prevents screenshots from capturing fallback system fonts.
 */
export async function waitForFonts(page: Page): Promise<void> {
  await page.waitForFunction(() => document.fonts.ready.then(() => true), {
    timeout: 10_000,
  })
}

/**
 * Wait for a component to signal readiness via window.__READY.
 * Used by components with async initialization (simulations, data loading).
 */
export async function waitForSettlement(
  page: Page,
  timeout = 15_000,
): Promise<void> {
  await page.waitForFunction(() => window.__READY === true, { timeout })
}

/**
 * Extract the constellation debug state.
 * Returns geometry, overlap, and clipping data for programmatic assertions.
 */
export async function getDebugState(page: Page) {
  return page.evaluate(() => {
    if (typeof window.__constellationDebug !== 'function') {
      throw new Error('window.__constellationDebug is not available')
    }
    return window.__constellationDebug()
  })
}

/**
 * Read the watermark text from a debug overlay element.
 */
export async function getWatermarkText(page: Page): Promise<string> {
  const el = page.locator('#constellation-watermark')
  return (await el.textContent()) ?? ''
}

/**
 * Attach debug state as a JSON artifact on test failure.
 * Call in afterEach to capture diagnostic data automatically.
 */
export async function attachDebugOnFailure(
  page: Page,
  testInfo: TestInfo,
): Promise<void> {
  if (testInfo.status !== testInfo.expectedStatus) {
    try {
      const debug = await getDebugState(page)
      await testInfo.attach('constellation-debug', {
        body: JSON.stringify(debug, null, 2),
        contentType: 'application/json',
      })
    } catch {
      /* component may not have loaded */
    }
  }
}
