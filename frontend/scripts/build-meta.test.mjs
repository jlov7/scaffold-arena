import assert from 'node:assert/strict'
import test from 'node:test'

import { buildMeta, resolveGitSha } from './build-meta.mjs'

test('prefers explicit and standard deployment SHA variables', () => {
  const resolveHead = () => 'f'.repeat(40)
  assert.equal(resolveGitSha({ VITE_GIT_SHA: 'a'.repeat(40), GITHUB_SHA: 'b'.repeat(40) }, resolveHead), 'a'.repeat(40))
  assert.equal(resolveGitSha({ VERCEL_GIT_COMMIT_SHA: 'b'.repeat(40), GITHUB_SHA: 'c'.repeat(40) }, resolveHead), 'b'.repeat(40))
  assert.equal(resolveGitSha({ RAILWAY_GIT_COMMIT_SHA: 'c'.repeat(40), GITHUB_SHA: 'd'.repeat(40) }, resolveHead), 'c'.repeat(40))
  assert.equal(resolveGitSha({ GITHUB_SHA: 'c'.repeat(40), SOURCE_VERSION: 'd'.repeat(40) }, resolveHead), 'c'.repeat(40))
  assert.equal(resolveGitSha({ SOURCE_VERSION: 'd'.repeat(40) }, resolveHead), 'd'.repeat(40))
})

test('uses the full Git head and truthful dev fallback', () => {
  assert.equal(resolveGitSha({}, () => 'e'.repeat(40)), 'e'.repeat(40))
  assert.equal(resolveGitSha({ VITE_GIT_SHA: 'short-sha' }, () => 'e'.repeat(40)), 'e'.repeat(40))
  assert.equal(resolveGitSha({ VITE_GIT_SHA: 'short-sha' }, () => 'also-short'), 'dev')
  assert.equal(resolveGitSha({}, () => null), 'dev')
})

test('uses the official Railway environment name', () => {
  assert.equal(buildMeta({
    appVersion: '0.9.1',
    environment: { RAILWAY_ENVIRONMENT_NAME: 'staging' },
    resolveHead: () => 'a'.repeat(40),
  }).build_environment, 'staging')
})

test('emits a public, versioned build receipt', () => {
  assert.deepEqual(buildMeta({
    appVersion: '0.9.1',
    environment: { VERCEL_ENV: 'production', VERCEL_GIT_COMMIT_SHA: 'a'.repeat(40) },
    now: new Date('2026-08-18T18:00:00.000Z'),
  }), {
    schema_version: 'build-meta.v1',
    app_version: '0.9.1',
    protocol_version: '1.0',
    git_sha: 'a'.repeat(40),
    build_environment: 'production',
    build_time: '2026-08-18T18:00:00.000Z',
  })
})

test('uses SOURCE_DATE_EPOCH for a reproducible build timestamp', () => {
  assert.equal(buildMeta({
    appVersion: '0.9.1',
    environment: { SOURCE_DATE_EPOCH: '1787076000' },
    now: new Date('2026-08-18T18:00:00.000Z'),
    resolveHead: () => 'dev',
  }).build_time, '2026-08-18T18:00:00.000Z')
})
