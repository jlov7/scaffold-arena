import { fileURLToPath } from 'node:url'
import { isFullCommitSha } from './build-meta.mjs'

export function parseArguments(argumentsList) {
  const values = { frontendBaseUrl: '', apiBaseUrl: '', expectedSha: '' }
  for (let index = 0; index < argumentsList.length; index += 1) {
    const argument = argumentsList[index]
    if (argument === '--frontend-url') values.frontendBaseUrl = argumentsList[++index] ?? ''
    else if (argument === '--api-url') values.apiBaseUrl = argumentsList[++index] ?? ''
    else if (argument === '--expected-sha') values.expectedSha = argumentsList[++index] ?? ''
    else throw new Error(`Unknown argument: ${argument}`)
  }
  if (!values.frontendBaseUrl) throw new Error('--frontend-url is required')
  const frontendBaseUrl = normalizeUrl(values.frontendBaseUrl)
  return {
    frontendBaseUrl,
    apiBaseUrl: normalizeUrl(values.apiBaseUrl || `${frontendBaseUrl}/api`),
    expectedSha: values.expectedSha.trim(),
  }
}

export async function smoke({ frontendBaseUrl, apiBaseUrl, expectedSha = '', fetchImpl = fetch }) {
  await check(`${frontendBaseUrl}/`, 'Homepage', fetchImpl)
  const frontendMeta = await checkJson(`${frontendBaseUrl}/build-meta.json`, 'Frontend build metadata', fetchImpl)
  validateBuildMeta(frontendMeta, 'Frontend build metadata', expectedSha)
  const health = await checkJson(`${apiBaseUrl}/health`, 'API health', fetchImpl)
  if (health.status !== 'ok') throw new Error('API health did not report status=ok')
  const apiMeta = await checkJson(`${apiBaseUrl}/meta`, 'API metadata', fetchImpl)
  validateBuildMeta(apiMeta.build, 'API build metadata', expectedSha)
}

function normalizeUrl(value) {
  return value.trim().replace(/\/$/, '')
}

async function check(url, label, fetchImpl) {
  const response = await fetchImpl(url)
  if (!response.ok) throw new Error(`${label} failed: ${response.status} ${response.statusText}`)
  return response
}

async function checkJson(url, label, fetchImpl) {
  const response = await check(url, label, fetchImpl)
  try {
    return await response.json()
  } catch {
    throw new Error(`${label} did not return JSON`)
  }
}

function validateBuildMeta(value, label, expectedSha) {
  if (!value || typeof value !== 'object') throw new Error(`${label} is missing`)
  for (const key of ['app_version', 'protocol_version', 'git_sha', 'build_environment', 'build_time']) {
    if (typeof value[key] !== 'string' || !value[key]) throw new Error(`${label} is missing ${key}`)
  }
  if (!expectedSha) return
  if (!isFullCommitSha(expectedSha)) throw new Error('--expected-sha must be a full hexadecimal commit ID')
  if (!isFullCommitSha(value.git_sha)) throw new Error(`${label} must contain a full hexadecimal commit ID for exact deployment validation`)
  if (value.build_time === 'unknown') throw new Error(`${label} must contain a known build_time for exact deployment validation`)
  if (value.build_environment.trim().toLowerCase() === 'development') {
    throw new Error(`${label} must not use the development build environment for exact deployment validation`)
  }
  if (value.git_sha !== expectedSha) {
    throw new Error(`${label} SHA mismatch: expected ${expectedSha}, received ${value.git_sha}`)
  }
}

function usage() {
  console.log('Usage: pnpm smoke:prod -- --frontend-url <url> [--api-url <url>] [--expected-sha <sha>]')
}

async function main() {
  try {
    const args = process.argv.slice(2).filter((argument) => argument !== '--')
    if (args.includes('--help') || args.includes('-h')) return usage()
    await smoke({ ...parseArguments(args) })
    console.log('Production smoke checks passed.')
  } catch (error) {
    console.error('Production smoke checks failed.')
    console.error(error instanceof Error ? error.message : String(error))
    process.exitCode = 1
  }
}

if (process.argv[1] === fileURLToPath(import.meta.url)) await main()
