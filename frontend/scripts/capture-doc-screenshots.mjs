import { spawn } from 'node:child_process'
import { mkdir } from 'node:fs/promises'
import path from 'node:path'

import { chromium } from 'playwright'

const HOST = '127.0.0.1'
const PORT = 4317
const BASE_URL = `http://${HOST}:${PORT}`
const FRONTEND_DIR = process.cwd()
const OUTPUT_DIR = path.resolve(FRONTEND_DIR, '..', 'docs', 'assets', 'screenshots')

function wait(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function waitForServer(url, timeoutMs = 30_000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      const res = await fetch(url)
      if (res.ok) return
    } catch {
      // continue polling
    }
    await wait(250)
  }
  throw new Error(`Timed out waiting for dev server: ${url}`)
}

function startDevServer() {
  const child = spawn('pnpm', ['dev', '--host', HOST, '--port', String(PORT)], {
    cwd: FRONTEND_DIR,
    stdio: 'ignore',
    detached: false,
  })
  return child
}

async function mockApi(page) {
  await page.route('**/api/meta', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        models: [
          {
            id: 'claude-sonnet-4-6',
            label: 'Claude Sonnet 4.6',
            input_usd_per_mtok: 3,
            output_usd_per_mtok: 15,
          },
          {
            id: 'claude-haiku-4-5',
            label: 'Claude Haiku 4.5',
            input_usd_per_mtok: 0.8,
            output_usd_per_mtok: 4,
          },
        ],
        tasks: [
          {
            id: 'extraction',
            name: 'Extraction',
            subtitle: 'Extract structured fields',
            type: 'extraction',
          },
        ],
        scaffolds: [
          { id: 'bare', name: 'Bare', subtitle: 'Control' },
          { id: 'plan_execute_verify', name: 'Plan Execute Verify', subtitle: 'PEV' },
          { id: 'tool_error_recovery', name: 'Tool Error Recovery', subtitle: 'Recover' },
          { id: 'memory_critique', name: 'Memory Critique', subtitle: 'Refine' },
        ],
        features: { llm_judge: false, pdf_export: false },
      }),
    })
  })

  await page.route('**/api/runs?*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        runs: [
          {
            run_id: 'run_hist_1',
            kind: 'arena',
            task_id: 'extraction',
            model_id: 'claude-sonnet-4-6',
            status: 'completed',
            created_at: 1710000000,
            completed_at: 1710000045,
            winner_id: 'plan_execute_verify',
            results: {
              plan_execute_verify: {
                output: 'ok',
                metrics: {
                  input_tokens: 1200,
                  output_tokens: 600,
                  cost_usd: 0.045,
                  wall_time_ms: 3200,
                  num_api_calls: 3,
                },
                evaluation: {
                  total_score: 92,
                  breakdown: { schema_validity: 95 },
                  weights: {
                    schema_validity: { weight: 1, type: 'deterministic' },
                  },
                  notes: [],
                },
              },
            },
          },
        ],
      }),
    })
  })

  await page.route('**/api/stats**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        run_count: 4,
        scaffolds: [
          {
            scaffold_id: 'plan_execute_verify',
            wins: 3,
            win_rate: 75,
            avg_score: 90,
            avg_cost: 0.06,
            samples: 4,
          },
        ],
        by_task: {
          extraction: [
            {
              scaffold_id: 'plan_execute_verify',
              avg_score: 90,
              samples: 4,
            },
          ],
        },
        distributions: [
          {
            scaffold_id: 'plan_execute_verify',
            bins: [
              { label: '0-20', count: 0 },
              { label: '20-40', count: 0 },
              { label: '40-60', count: 1 },
              { label: '60-80', count: 1 },
              { label: '80-100', count: 2 },
            ],
          },
        ],
      }),
    })
  })

  await page.route('**/api/runs/run_hist_1', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        run_id: 'run_hist_1',
        kind: 'arena',
        task_id: 'extraction',
        model_id: 'claude-sonnet-4-6',
        status: 'completed',
        winner_id: 'plan_execute_verify',
        results: {
          plan_execute_verify: {
            output: 'winner output',
            metrics: {
              input_tokens: 1200,
              output_tokens: 600,
              cost_usd: 0.045,
              wall_time_ms: 3200,
              num_api_calls: 3,
            },
            evaluation: {
              total_score: 92,
              breakdown: { schema_validity: 95 },
              weights: {
                schema_validity: { weight: 1, type: 'deterministic' },
              },
              notes: [],
            },
          },
          bare: {
            output: 'loser output',
            metrics: {
              input_tokens: 1200,
              output_tokens: 600,
              cost_usd: 0.03,
              wall_time_ms: 2200,
              num_api_calls: 1,
            },
            evaluation: {
              total_score: 71,
              breakdown: { schema_validity: 80 },
              weights: {
                schema_validity: { weight: 1, type: 'deterministic' },
              },
              notes: [],
            },
          },
        },
      }),
    })
  })
}

async function capture() {
  await mkdir(OUTPUT_DIR, { recursive: true })

  const devServer = startDevServer()
  let browser
  try {
    await waitForServer(BASE_URL)
    browser = await chromium.launch({ headless: true })

    const context = await browser.newContext({ viewport: { width: 1440, height: 960 } })
    const page = await context.newPage()

    await page.addInitScript(() => {
      window.localStorage.setItem('scaffold_arena_tour_seen', '1')
      window.localStorage.setItem('scaffold_arena_exp_tour_entry', 'cta_only')
    })
    await mockApi(page)

    await page.goto(`${BASE_URL}/arena`)
    await page.getByText('Arena workflow lane').waitFor({ state: 'visible' })
    await page.getByRole('button', { name: 'Configure', exact: true }).first().click()
    await page.screenshot({ path: path.join(OUTPUT_DIR, 'arena-desktop.png'), fullPage: true })

    await page.goto(`${BASE_URL}/arena?run_id=run_hist_1`)
    await page.getByRole('heading', { name: 'Results workspace' }).waitFor({
      state: 'visible',
    })
    await page.screenshot({ path: path.join(OUTPUT_DIR, 'results-summary-desktop.png'), fullPage: true })
    await page.getByRole('button', { name: 'Diagnostics', exact: true }).click()
    await page.getByText('Diagnostics lane').waitFor({ state: 'visible' })
    await page.screenshot({
      path: path.join(OUTPUT_DIR, 'results-diagnostics-desktop.png'),
      fullPage: true,
    })

    await page.goto(`${BASE_URL}/history`)
    await page.waitForTimeout(800)
    await page.screenshot({ path: path.join(OUTPUT_DIR, 'history-desktop.png'), fullPage: true })

    await page.goto(`${BASE_URL}/leaderboard`)
    await page.waitForTimeout(800)
    await page.screenshot({ path: path.join(OUTPUT_DIR, 'leaderboard-desktop.png'), fullPage: true })

    await page.goto(`${BASE_URL}/settings`)
    await page.waitForTimeout(800)
    await page.screenshot({ path: path.join(OUTPUT_DIR, 'settings-desktop.png'), fullPage: true })

    const mobile = await browser.newContext({ viewport: { width: 390, height: 844 } })
    const mobilePage = await mobile.newPage()
    await mobilePage.addInitScript(() => {
      window.localStorage.setItem('scaffold_arena_tour_seen', '1')
      window.localStorage.setItem('scaffold_arena_exp_tour_entry', 'cta_only')
    })
    await mockApi(mobilePage)
    await mobilePage.goto(`${BASE_URL}/arena`)
    await mobilePage.getByText('Arena workflow lane').waitFor({ state: 'visible' })
    await mobilePage.getByRole('button', { name: 'Configure', exact: true }).first().click()
    await mobilePage.screenshot({ path: path.join(OUTPUT_DIR, 'arena-mobile.png'), fullPage: true })

    const tourContext = await browser.newContext({ viewport: { width: 1280, height: 800 } })
    const tourPage = await tourContext.newPage()
    await tourPage.addInitScript(() => {
      window.localStorage.removeItem('scaffold_arena_tour_seen')
      window.localStorage.setItem('scaffold_arena_exp_tour_entry', 'auto_open')
    })
    await mockApi(tourPage)
    await tourPage.goto(`${BASE_URL}/arena`)
    await tourPage.getByRole('dialog', { name: 'Guided Tour' }).waitFor({ state: 'visible' })
    await tourPage.screenshot({ path: path.join(OUTPUT_DIR, 'guided-tour.png'), fullPage: true })

    await context.close()
    await mobile.close()
    await tourContext.close()
    console.log(`Saved documentation screenshots to ${OUTPUT_DIR}`)
  } finally {
    if (browser) {
      await browser.close()
    }
    devServer.kill('SIGTERM')
  }
}

capture().catch((error) => {
  console.error(error)
  process.exitCode = 1
})
