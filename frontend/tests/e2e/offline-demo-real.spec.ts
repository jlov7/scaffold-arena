import { createHash } from 'node:crypto'
import { accessSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { constants } from 'node:fs'
import { execFileSync } from 'node:child_process'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, test } from '@playwright/test'

test.setTimeout(90_000)
test.skip(!process.env.RUN_REAL_OFFLINE_DEMO, 'requires an isolated local fixture-only backend')

const viewports = {
  desktop: { width: 1440, height: 900 },
  mobile: { width: 390, height: 844 },
} as const
const viewportName = process.env.REAL_OFFLINE_DEMO_VIEWPORT as keyof typeof viewports | undefined
const captureDirectory = process.env.REAL_OFFLINE_DEMO_CAPTURE_DIR
const backendURL = process.env.REAL_OFFLINE_DEMO_BACKEND_URL
const testDirectory = dirname(fileURLToPath(import.meta.url))

if (process.env.RUN_REAL_OFFLINE_DEMO && (!viewportName || !viewports[viewportName] || !captureDirectory || !backendURL)) {
  throw new Error('RUN_REAL_OFFLINE_DEMO requires a supported viewport, writable capture directory, and owned local backend URL.')
}

function sha256(bytes: Buffer): string {
  return createHash('sha256').update(bytes).digest('hex')
}

function requiredPath(path: string): Buffer {
  return readFileSync(path)
}

test(`real personal offline fixture completes, analyzes, and exports at ${viewportName} width`, async ({ page, browserName }) => {
  if (!viewportName || !captureDirectory) throw new Error('The real offline demo environment was not configured.')
  const viewport = viewports[viewportName]
  mkdirSync(captureDirectory, { recursive: true })
  accessSync(captureDirectory, constants.W_OK)
  await page.setViewportSize({ width: viewport.width, height: viewport.height })
  const runtimeErrors: string[] = []
  page.on('pageerror', (error) => runtimeErrors.push(error.message))
  await page.goto('/workbench/studies')
  await expect(page.locator('h1.sa-stage-heading')).toHaveText('Study Canvas')
  const importBundledDemo = page.getByRole('button', { name: 'Import bundled demo' })
  if (await importBundledDemo.isVisible()) {
    await importBundledDemo.click()
    await page.reload()
  }
  await expect(page.getByRole('button', { name: 'Select' })).toBeVisible()
  await page.getByRole('button', { name: 'Select' }).click()
  await expect(page).toHaveURL(/\/workbench\/design.*study_pack_id=offline-demo-v1/)

  await page.getByLabel('I have explicit owner approval to create this new, unfrozen ExperimentSpec.').check()
  await page.getByRole('button', { name: 'Create unfrozen experiment' }).click()
  await expect(page).toHaveURL(/\/workbench\/preflight/)
  await page.getByRole('button', { name: 'Freeze experiment' }).click()
  await expect(page.getByRole('button', { name: 'Experiment frozen' })).toBeVisible()
  await page.getByRole('button', { name: 'Preflight experiment' }).click()
  await expect(page.getByText('Preflight passed the local protocol admissibility checks.')).toBeVisible()
  await page.getByRole('button', { name: 'Continue to Run Cockpit' }).click()
  await expect(page.getByRole('heading', { name: 'Run Cockpit' })).toBeVisible()

  await page.getByRole('button', { name: 'Run bundled offline demo' }).click()
  await expect(page.getByRole('heading', { name: 'Execution control' })).toBeVisible({ timeout: 30_000 })
  await expect(page.getByRole('heading', { name: 'Execution control' }).locator('..').getByText('completed', { exact: true })).toBeVisible({ timeout: 30_000 })
  const firstExecutionId = new URL(page.url()).searchParams.get('execution_id')
  expect(firstExecutionId).toBeTruthy()
  // A deliberate second run in this same mounted cockpit must dispatch a
  // new execution. Reloading here would conceal idempotency-key reuse.
  await page.getByRole('button', { name: 'Run bundled offline demo' }).click()
  await expect.poll(() => new URL(page.url()).searchParams.get('execution_id')).not.toBe(firstExecutionId)
  const secondExecutionId = new URL(page.url()).searchParams.get('execution_id')
  expect(secondExecutionId).toBeTruthy()
  await expect(page.getByRole('heading', { name: 'Execution control' }).locator('..').getByText('completed', { exact: true })).toBeVisible({ timeout: 30_000 })
  await page.getByRole('button', { name: 'Select', exact: true }).first().click()
  await expect.poll(() => new URL(page.url()).searchParams.get('execution_id')).toBe(firstExecutionId)
  await page.getByRole('button', { name: 'Run bundled offline demo' }).click()
  await expect.poll(() => new URL(page.url()).searchParams.get('execution_id')).not.toBe(firstExecutionId)
  const thirdExecutionId = new URL(page.url()).searchParams.get('execution_id')
  expect(thirdExecutionId).toBeTruthy()
  expect(thirdExecutionId).not.toBe(secondExecutionId)
  await expect(page.getByRole('heading', { name: 'Execution control' }).locator('..').getByText('completed', { exact: true })).toBeVisible({ timeout: 30_000 })
  // Reload remains the explicit durable recovery control after interruption.
  await page.getByRole('button', { name: 'Reload' }).click()
  await expect(page.getByRole('heading', { name: 'Execution control' }).locator('..').getByText('completed', { exact: true })).toBeVisible()
  await page.evaluate(() => window.scrollTo(0, 0))
  const screenshotPath = resolve(captureDirectory, `offline-demo-${viewportName}.png`)
  await page.screenshot({ path: screenshotPath, fullPage: false })
  const screenshotRoute = page.url()

  if (viewportName === 'mobile') {
    await page.setViewportSize({ width: 320, height: 844 })
    const analyze = page.getByRole('button', { name: 'Analyze selected execution' })
    await analyze.focus()
    await expect(analyze).toBeFocused()
    expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(2)
  }

  await page.getByRole('button', { name: 'Analyze selected execution' }).click()
  await expect(page.getByRole('heading', { name: 'Analyze persisted execution' })).toBeVisible()
  await page.getByRole('button', { name: 'Create immutable analysis' }).click()
  await expect(page.getByRole('heading', { name: 'Verified report integrity and claim ceiling' })).toBeVisible({ timeout: 30_000 })
  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export CSV' }).first().click()
  await (await download).saveAs(resolve(captureDirectory, `offline-demo-analysis-${viewportName}.csv`))

  const selected = new URL(page.url())
  const experimentId = selected.searchParams.get('experiment_id')
  const executionId = selected.searchParams.get('execution_id')
  expect(experimentId).toBeTruthy()
  expect(executionId).toBeTruthy()

  const repositoryRoot = resolve(testDirectory, '../../..')
  const testPath = resolve(testDirectory, 'offline-demo-real.spec.ts')
  const studyPackPath = resolve(repositoryRoot, 'backend/adapters_v1/offline_fixture/study_pack/study-pack.json')
  const adapterPath = resolve(repositoryRoot, 'backend/adapters_v1/offline_fixture/adapter.py')
  const playwrightPackagePath = resolve(repositoryRoot, 'frontend/node_modules/@playwright/test/package.json')
  const browserVersion = page.context().browser()?.version() ?? 'UNKNOWN'
  const backendRevision = execFileSync('git', ['-C', repositoryRoot, 'rev-parse', 'HEAD'], { encoding: 'utf8' }).trim()
  const provenance = {
    evidence_kind: 'local_offline_fixture_browser_smoke',
    claim_boundary: 'This proves only that the named local synthetic fixture journey rendered and completed. It is not benchmark, provider, usability, or model-performance evidence.',
    png_sha256: sha256(requiredPath(screenshotPath)),
    test_source_sha256: sha256(requiredPath(testPath)),
    backend_revision: backendRevision,
    bundled_fixture_sha256: {
      study_pack: sha256(requiredPath(studyPackPath)),
      adapter: sha256(requiredPath(adapterPath)),
    },
    browser: { name: browserName, version: browserVersion },
    playwright_version: JSON.parse(requiredPath(playwrightPackagePath).toString()).version,
    backend_url: backendURL,
    route: screenshotRoute,
    viewport: { name: viewportName, width: viewport.width, height: viewport.height },
    captured_at: new Date().toISOString(),
    asserted_ids: { experiment_id: experimentId, execution_id: executionId, first_execution_id: firstExecutionId, second_execution_id: secondExecutionId, third_execution_id: thirdExecutionId },
  }
  writeFileSync(`${screenshotPath}.provenance.json`, `${JSON.stringify(provenance, null, 2)}\n`, { encoding: 'utf8', flag: 'wx' })

  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)).toBeLessThanOrEqual(2)

  await page.goto(`/workbench/execute?study_pack_id=offline-demo-v1&study_pack_version=1.0.0&experiment_id=${experimentId}&execution_id=missing-run`)
  await expect(page.getByText('Execution recovery failed')).toBeVisible()
  expect(runtimeErrors).toEqual([])
})
