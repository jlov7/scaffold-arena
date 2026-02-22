import { mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'

const frontendDir = resolve(import.meta.dirname, '..')
const repoDir = resolve(frontendDir, '..')
const trackerPath = join(repoDir, '.codex', 'UX_REARCH_EXECUTION_TRACKER.md')
const lighthouseDir = join(frontendDir, '.lighthouseci')
const playwrightLastRunPath = join(frontendDir, 'test-results', '.last-run.json')
const outputPath = process.argv[2]
  ? resolve(process.argv[2])
  : join(repoDir, 'output', 'weekly-ux-regression-report.md')

function readJson(path) {
  try {
    return JSON.parse(readFileSync(path, 'utf8'))
  } catch {
    return null
  }
}

function parseTracker(text) {
  const lines = text.split('\n')
  let total = 0
  let completed = 0
  const workstreamOpen = {}

  let currentWorkstream = null
  for (const line of lines) {
    const wsMatch = line.match(/^###\s+(WS\d+)\s+—\s+(.+)$/)
    if (wsMatch) {
      currentWorkstream = wsMatch[1]
      continue
    }
    const taskMatch = line.match(/^- \[(x| )\]\s+(WS\d+-T\d+|LV-T\d+)/)
    if (!taskMatch) continue
    total += 1
    if (taskMatch[1] === 'x') {
      completed += 1
      continue
    }
    if (currentWorkstream) {
      workstreamOpen[currentWorkstream] = (workstreamOpen[currentWorkstream] ?? 0) + 1
    } else {
      workstreamOpen.Uncategorized = (workstreamOpen.Uncategorized ?? 0) + 1
    }
  }
  const topOpen = Object.entries(workstreamOpen)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5)

  return { total, completed, topOpen }
}

function readLighthouseScores() {
  try {
    const files = readdirSync(lighthouseDir)
      .filter((name) => name.startsWith('lhr-') && name.endsWith('.json'))
      .sort()
    if (files.length === 0) {
      return null
    }
    const recent = files.slice(-2)
    const samples = recent
      .map((file) => readJson(join(lighthouseDir, file)))
      .filter(Boolean)
      .map((report) => ({
        url: report.finalDisplayedUrl ?? report.finalUrl ?? 'unknown',
        performance: Number(report.categories?.performance?.score ?? NaN),
        accessibility: Number(report.categories?.accessibility?.score ?? NaN),
      }))
    if (samples.length === 0) {
      return null
    }
    const avg = (key) => {
      const values = samples
        .map((sample) => sample[key])
        .filter((value) => Number.isFinite(value))
      if (values.length === 0) return null
      return values.reduce((sum, value) => sum + value, 0) / values.length
    }
    return {
      samples,
      performanceAvg: avg('performance'),
      accessibilityAvg: avg('accessibility'),
    }
  } catch {
    return null
  }
}

function pct(value) {
  if (!Number.isFinite(value)) return 'n/a'
  return `${(value * 100).toFixed(1)}%`
}

function generate() {
  const trackerRaw = readFileSync(trackerPath, 'utf8')
  const tracker = parseTracker(trackerRaw)
  const completionRatio =
    tracker.total === 0 ? 0 : tracker.completed / tracker.total
  const lighthouse = readLighthouseScores()
  const playwrightLastRun = readJson(playwrightLastRunPath)

  const now = new Date()
  const date = now.toISOString().slice(0, 10)
  const ts = now.toISOString()

  const lines = [
    '# Weekly UX Regression Report',
    '',
    `Generated: ${ts}`,
    '',
    '## Executive Summary',
    '',
    `- UX tracker completion: **${tracker.completed}/${tracker.total} (${pct(completionRatio)})**`,
    `- Playwright run status: **${playwrightLastRun?.status ?? 'unknown'}**`,
    `- Lighthouse avg performance: **${lighthouse ? pct(lighthouse.performanceAvg) : 'n/a'}**`,
    `- Lighthouse avg accessibility: **${lighthouse ? pct(lighthouse.accessibilityAvg) : 'n/a'}**`,
    '',
    '## HEART Scorecard (Weekly)',
    '',
    '| Dimension | Signal | Current indicator | Owner |',
    '| --- | --- | --- | --- |',
    '| Happiness | Qualitative “guidance was clear” feedback | `ux_feedback_submitted` sentiment mix (see Telemetry Dashboard) | UX + Product |',
    '| Engagement | Guided flow completion depth | Onboarding + conversion funnels in-app | Product |',
    '| Adoption | Activation completion rate | `activation_completed` / first-session users | Product + Engineering |',
    '| Retention | Repeat weekly usage of compare/export actions | `comparison_completed`, `report_exported` trend | Product Ops |',
    '| Task Success | Recovery and completion reliability | blocker recovery rate + run completion | Engineering |',
    '',
    '## Highest Open UX Risk Areas',
    '',
    ...(tracker.topOpen.length === 0
      ? ['- No open workstreams detected in tracker.']
      : tracker.topOpen.map(([ws, count]) => `- ${ws}: ${count} open tasks`)),
    '',
    '## Lighthouse Route Samples',
    '',
    ...(lighthouse?.samples?.length
      ? lighthouse.samples.map(
          (sample) =>
            `- ${sample.url}: performance ${pct(sample.performance)}, accessibility ${pct(sample.accessibility)}`,
        )
      : ['- No Lighthouse samples found in `frontend/.lighthouseci`.']),
    '',
    '## Required Weekly Actions',
    '',
    '1. Review this report in UX council and assign owners for top open workstreams.',
    '2. Review friction telemetry (`onboarding_blocker_detected/resolved`) and adjust guidance copy if recovery drops.',
    '3. Confirm no regression in mobile viewport suite (320/360/390/412/768/1024).',
    '4. Re-run launch checklist if Lighthouse accessibility average falls below 95%.',
    '',
    `## Week Key`,
    '',
    `- ISO week reference date: ${date}`,
  ]

  mkdirSync(dirname(outputPath), { recursive: true })
  writeFileSync(outputPath, `${lines.join('\n')}\n`, 'utf8')
  console.log(`Generated UX regression report at ${outputPath}`)
}

generate()
