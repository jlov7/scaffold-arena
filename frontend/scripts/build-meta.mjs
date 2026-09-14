import { execFileSync } from 'node:child_process'

const SHA_ENVIRONMENT_KEYS = [
  'VITE_GIT_SHA',
  'VERCEL_GIT_COMMIT_SHA',
  'RAILWAY_GIT_COMMIT_SHA',
  'GITHUB_SHA',
  'SOURCE_VERSION',
]

export function resolveGitSha(environment = process.env, resolveHead = gitHead) {
  for (const key of SHA_ENVIRONMENT_KEYS) {
    const value = environment[key]?.trim()
    if (isFullCommitSha(value)) return value
  }
  const head = resolveHead()
  return isFullCommitSha(head) ? head : 'dev'
}

export function isFullCommitSha(value) {
  return typeof value === 'string' && /^(?:[0-9a-f]{40}|[0-9a-f]{64})$/i.test(value)
}

export function buildEnvironment(environment = process.env) {
  return (
    environment.VITE_BUILD_ENV?.trim() ||
    environment.VERCEL_ENV?.trim() ||
    environment.RAILWAY_ENVIRONMENT_NAME?.trim() ||
    environment.RAILWAY_ENVIRONMENT?.trim() ||
    environment.NODE_ENV?.trim() ||
    'development'
  )
}

export function buildTime(environment = process.env, now = new Date()) {
  const sourceDateEpoch = environment.SOURCE_DATE_EPOCH?.trim()
  if (sourceDateEpoch && /^\d+$/.test(sourceDateEpoch)) {
    return new Date(Number(sourceDateEpoch) * 1000).toISOString()
  }
  return environment.BUILD_TIME?.trim() || now.toISOString()
}

export function buildMeta({ appVersion, environment = process.env, now = new Date(), resolveHead = gitHead }) {
  return {
    schema_version: 'build-meta.v1',
    app_version: appVersion,
    protocol_version: '1.0',
    git_sha: resolveGitSha(environment, resolveHead),
    build_environment: buildEnvironment(environment),
    build_time: buildTime(environment, now),
  }
}

function gitHead() {
  try {
    return execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim() || null
  } catch {
    return null
  }
}
