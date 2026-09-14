import assert from 'node:assert/strict'
import test from 'node:test'

import { parseArguments, smoke } from './prod-smoke.mjs'

const sha = 'a'.repeat(40)
const build = { app_version: '0.9.1', protocol_version: '1.0', git_sha: sha, build_environment: 'production', build_time: '2026-08-18T18:00:00.000Z' }

test('parses independent frontend and API URLs', () => {
  assert.deepEqual(parseArguments(['--frontend-url', 'https://web.example/', '--api-url', 'https://api.example/api/', '--expected-sha', sha]), { frontendBaseUrl: 'https://web.example', apiBaseUrl: 'https://api.example/api', expectedSha: sha })
})

test('defaults the API URL to the frontend API path', () => {
  assert.equal(parseArguments(['--frontend-url', 'https://web.example/']).apiBaseUrl, 'https://web.example/api')
})

test('checks public homepage, frontend build receipt, health, and API metadata without a token', async () => {
  const requests = []
  const fetchImpl = async (url) => {
    requests.push(url)
    const bodies = {
      'https://web.example/': {},
      'https://web.example/build-meta.json': build,
      'https://api.example/api/health': { status: 'ok' },
      'https://api.example/api/meta': { build },
    }
    return { ok: true, status: 200, statusText: 'OK', json: async () => bodies[url] }
  }
  await smoke({ frontendBaseUrl: 'https://web.example', apiBaseUrl: 'https://api.example/api', expectedSha: sha, fetchImpl })
  assert.deepEqual(requests, ['https://web.example/', 'https://web.example/build-meta.json', 'https://api.example/api/health', 'https://api.example/api/meta'])
})

test('rejects an API revision mismatch', async () => {
  const fetchImpl = async (url) => {
    const bodies = {
      'https://web.example/': {},
      'https://web.example/build-meta.json': build,
      'https://api.example/api/health': { status: 'ok' },
      'https://api.example/api/meta': { build: { ...build, git_sha: 'b'.repeat(40) } },
    }
    return { ok: true, status: 200, statusText: 'OK', json: async () => bodies[url] }
  }
  await assert.rejects(smoke({ frontendBaseUrl: 'https://web.example', apiBaseUrl: 'https://api.example/api', expectedSha: sha, fetchImpl }), /API build metadata SHA mismatch/)
})

test('requires complete receipts when exact SHA validation is requested', async () => {
  for (const [target, incompleteBuild, message] of [
    ['frontend', { ...build, git_sha: 'dev' }, /full hexadecimal commit ID/],
    ['api', { ...build, build_time: 'unknown' }, /known build_time/],
    ['api', { ...build, build_environment: 'development' }, /must not use the development build environment/],
  ]) {
    const fetchImpl = async (url) => {
      const bodies = {
        'https://web.example/': {},
        'https://web.example/build-meta.json': target === 'frontend' ? incompleteBuild : build,
        'https://api.example/api/health': { status: 'ok' },
        'https://api.example/api/meta': { build: target === 'api' ? incompleteBuild : build },
      }
      return { ok: true, status: 200, statusText: 'OK', json: async () => bodies[url] }
    }
    await assert.rejects(smoke({ frontendBaseUrl: 'https://web.example', apiBaseUrl: 'https://api.example/api', expectedSha: sha, fetchImpl }), message)
  }
})
