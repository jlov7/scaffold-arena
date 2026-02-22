import type { Page, Route } from '@playwright/test'

export async function mockMeta(page: Page): Promise<void> {
  await page.route('**/api/meta', async (route: Route) => {
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
}

export async function mockRunHistory(page: Page): Promise<void> {
  await page.route('**/api/runs?*', async (route: Route) => {
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
            created_at: 1,
            completed_at: 2,
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
}

export async function mockLeaderboard(page: Page): Promise<void> {
  await page.route('**/api/stats**', async (route: Route) => {
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
}

export async function mockRunDetails(page: Page): Promise<void> {
  await page.route('**/api/runs/run_hist_1', async (route: Route) => {
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

export async function seedTourSeen(page: Page): Promise<void> {
  await page.addInitScript(() => {
    window.localStorage.setItem('scaffold_arena_tour_seen', '1')
  })
}

export async function mockDefaultApi(page: Page): Promise<void> {
  await seedTourSeen(page)
  await mockMeta(page)
  await mockRunHistory(page)
  await mockLeaderboard(page)
  await mockRunDetails(page)
}
