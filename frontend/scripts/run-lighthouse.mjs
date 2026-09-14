import { mkdir, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { join } from 'node:path'
import { spawn as spawnProcess } from 'node:child_process'

export const PROFILES = {
  desktop: {
    label: 'desktop',
    configPreset: 'desktop',
    reportDirectory: 'lighthouse-reports',
    urls: ['/arena', '/settings'],
    settings: {},
    thresholds: {
      'categories:performance': { minScore: 0.9 },
      'categories:accessibility': { minScore: 0.95 },
      'first-contentful-paint': { maxNumericValue: 2000 },
      interactive: { maxNumericValue: 3000 },
      'cumulative-layout-shift': { maxNumericValue: 0.05 },
    },
  },
  mobile: {
    label: 'mobile',
    configPreset: 'perf',
    reportDirectory: 'lighthouse-reports/mobile',
    urls: ['/arena', '/settings'],
    settings: {
      formFactor: 'mobile',
      throttlingMethod: 'simulate',
      throttling: { rttMs: 150, throughputKbps: 1638, cpuSlowdownMultiplier: 4 },
    },
    thresholds: {
      'categories:performance': { minScore: 0.75 },
      'largest-contentful-paint': { maxNumericValue: 4000 },
      interactive: { maxNumericValue: 5000 },
    },
  },
}

export function parseProfile(argumentsList) {
  if (argumentsList.length !== 2 || argumentsList[0] !== '--profile' || !(argumentsList[1] in PROFILES)) {
    throw new Error('Usage: node scripts/run-lighthouse.mjs --profile <desktop|mobile>')
  }
  return PROFILES[argumentsList[1]]
}

export function evaluateThresholds(lhr, thresholds) {
  const failures = []
  for (const [metric, threshold] of Object.entries(thresholds)) {
    const value = metric.startsWith('categories:')
      ? lhr.categories?.[metric.slice('categories:'.length)]?.score
      : lhr.audits?.[metric]?.numericValue
    if (typeof value !== 'number') {
      failures.push(`${metric} is missing a numeric result`)
      continue
    }
    if (threshold.minScore !== undefined && value < threshold.minScore) {
      failures.push(`${metric} ${value} is below ${threshold.minScore}`)
    }
    if (threshold.maxNumericValue !== undefined && value > threshold.maxNumericValue) {
      failures.push(`${metric} ${value} exceeds ${threshold.maxNumericValue}`)
    }
  }
  return failures
}

export async function runWithPreview({ startPreview, runAudit }) {
  const preview = await startPreview()
  try {
    return await runAudit(preview.url)
  } finally {
    await preview.stop()
  }
}

export async function runProfile(profile, dependencies) {
  const results = await runWithPreview({
    startPreview: dependencies.startPreview,
    runAudit: async (baseUrl) => {
      const config = dependencies.loadConfig ? await dependencies.loadConfig(profile) : undefined
      const chrome = await dependencies.launchChrome()
      try {
        const reports = []
        for (const pathname of profile.urls) {
          const url = `${baseUrl}${pathname}`
          const result = await dependencies.lighthouse(url, { port: chrome.port, output: ['json', 'html'] }, config)
          if (!result?.lhr || !Array.isArray(result.report)) throw new Error(`Lighthouse returned no report for ${url}`)
          const failures = evaluateThresholds(result.lhr, profile.thresholds)
          reports.push({ url, result, failures })
        }
        await dependencies.writeReports(profile, reports)
        const failures = reports.flatMap(({ url, failures: itemFailures }) => itemFailures.map((failure) => `${url}: ${failure}`))
        if (failures.length) throw new Error(`Lighthouse ${profile.label} threshold failure:\n${failures.join('\n')}`)
        return reports
      } finally {
        await chrome.kill()
      }
    },
  })
  console.log(`Lighthouse ${profile.label} gate passed for ${results.length} routes.`)
  return results
}

export function createPreview({ spawn = spawnProcess, fetchImpl = fetch, waitMs = 100, timeoutMs = 30_000 } = {}) {
  return async () => {
    const viteBin = join(process.cwd(), 'node_modules', 'vite', 'bin', 'vite.js')
    const child = spawn(process.execPath, [viteBin, 'preview', '--host', '127.0.0.1', '--port', '4318'], {
      detached: process.platform !== 'win32',
      stdio: 'ignore',
    })
    let exited = false
    let exitError = null
    child.once('error', (error) => { exitError = error })
    child.once('exit', (code, signal) => {
      exited = true
      exitError ??= new Error(`Preview server exited before readiness (code=${code}, signal=${signal})`)
    })
    try {
      await waitForPreview({ fetchImpl, hasExited: () => exited, getError: () => exitError, waitMs, timeoutMs })
    } catch (error) {
      await stopPreview(child)
      throw error
    }
    return { url: 'http://127.0.0.1:4318', stop: () => stopPreview(child) }
  }
}

export async function waitForPreview({ fetchImpl, hasExited, getError, waitMs, timeoutMs }) {
  const started = Date.now()
  while (Date.now() - started < timeoutMs) {
    if (hasExited()) throw getError() ?? new Error('Preview server exited before readiness')
    try {
      const response = await fetchImpl('http://127.0.0.1:4318/')
      if (response.ok) return
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, waitMs))
  }
  throw new Error(`Preview server did not become ready within ${timeoutMs}ms`)
}

export async function stopPreview(child) {
  if (child.exitCode !== null || child.killed) return
  if (process.platform !== 'win32' && child.pid) process.kill(-child.pid, 'SIGTERM')
  else child.kill('SIGTERM')
}

export async function writeReports(profile, reports, { mkdirImpl = mkdir, writeFileImpl = writeFile } = {}) {
  await mkdirImpl(profile.reportDirectory, { recursive: true })
  for (const { url, result } of reports) {
    const name = new URL(url).pathname.replace(/^\//, '').replaceAll('/', '-') || 'root'
    const [json, html] = result.report
    await writeFileImpl(join(profile.reportDirectory, `${name}.report.json`), json)
    await writeFileImpl(join(profile.reportDirectory, `${name}.report.html`), html)
  }
}

async function main() {
  const profile = parseProfile(process.argv.slice(2))
  const [{ default: lighthouse }, chromeLauncher] = await Promise.all([import('lighthouse'), import('chrome-launcher')])
  await runProfile(profile, {
    lighthouse,
    loadConfig: async ({ configPreset, settings }) => {
      const { default: baseConfig } = await import(`lighthouse/core/config/${configPreset}-config.js`)
      return { ...baseConfig, settings: { ...baseConfig.settings, ...settings } }
    },
    launchChrome: () => chromeLauncher.launch({ chromeFlags: ['--headless=new'] }),
    startPreview: createPreview(),
    writeReports,
  })
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    console.error(error instanceof Error ? error.message : String(error))
    process.exitCode = 1
  })
}
