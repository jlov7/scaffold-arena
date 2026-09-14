import assert from 'node:assert/strict'
import test from 'node:test'

import { PROFILES, evaluateThresholds, parseProfile, runProfile, runWithPreview, waitForPreview } from './run-lighthouse.mjs'

const passingLhr = {
  categories: { performance: { score: 0.96 }, accessibility: { score: 0.99 } },
  audits: {
    'first-contentful-paint': { numericValue: 1000 },
    interactive: { numericValue: 2000 },
    'cumulative-layout-shift': { numericValue: 0.01 },
    'largest-contentful-paint': { numericValue: 3000 },
  },
}

test('parses the two supported profiles', () => {
  assert.equal(parseProfile(['--profile', 'desktop']), PROFILES.desktop)
  assert.throws(() => parseProfile(['--profile', 'tablet']), /Usage/)
})

test('evaluates passing and failing thresholds deterministically', () => {
  assert.deepEqual(evaluateThresholds(passingLhr, PROFILES.desktop.thresholds), [])
  const failures = evaluateThresholds({ ...passingLhr, categories: { ...passingLhr.categories, performance: { score: 0.89 } } }, PROFILES.desktop.thresholds)
  assert.deepEqual(failures, ['categories:performance 0.89 is below 0.9'])
})

test('stops the preview when audit succeeds and when it throws', async () => {
  let stops = 0
  const startPreview = async () => ({ url: 'http://localhost', stop: async () => { stops += 1 } })
  await runWithPreview({ startPreview, runAudit: async () => 'ok' })
  await assert.rejects(runWithPreview({ startPreview, runAudit: async () => { throw new Error('audit failed') } }), /audit failed/)
  assert.equal(stops, 2)
})

test('fails a profile after writing reports and still closes Chrome and preview', async () => {
  let previewStopped = false
  let chromeKilled = false
  let reportsWritten = false
  await assert.rejects(runProfile(PROFILES.desktop, {
    startPreview: async () => ({ url: 'http://localhost:4318', stop: async () => { previewStopped = true } }),
    launchChrome: async () => ({ port: 9222, kill: async () => { chromeKilled = true } }),
    lighthouse: async () => ({ lhr: { ...passingLhr, categories: { ...passingLhr.categories, performance: { score: 0.5 } } }, report: ['{}', '<html></html>'] }),
    writeReports: async () => { reportsWritten = true },
  }), /threshold failure/)
  assert.equal(reportsWritten, true)
  assert.equal(chromeKilled, true)
  assert.equal(previewStopped, true)
})

test('reports a preview process error without waiting for the full timeout', async () => {
  await assert.rejects(waitForPreview({
    fetchImpl: async () => ({ ok: false }),
    hasExited: () => true,
    getError: () => new Error('preview spawn failed'),
    waitMs: 0,
    timeoutMs: 1,
  }), /preview spawn failed/)
})
