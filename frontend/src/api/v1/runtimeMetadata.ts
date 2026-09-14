import { ApiProblem, type ApiProblemBody } from './types'

const DEFAULT_BASE_URL = (import.meta.env.VITE_API_V1_BASE_URL ?? '/api/v1').replace(/\/$/, '')
const FULL_COMMIT = /^(?:[0-9a-f]{40}|[0-9a-f]{64})$/i
const VERSIONED_API_SUFFIX = '/api/v1'

export interface RuntimeMetadata {
  schema_version: 'build-meta.v1'
  app_version: string
  protocol_version: string
  git_sha: string
  build_environment: string
  build_time: string
}

export type RuntimeRevisionState = 'checking' | 'coherent' | 'mismatch' | 'unknown' | 'offline'

export interface RuntimeRevisionStatus {
  state: RuntimeRevisionState
  label: string
  tone: 'ready' | 'info' | 'warning' | 'failure' | 'offline'
  message: string
  frontendSha: string
  backendSha: string | null
}

export interface FetchRuntimeMetadataOptions {
  baseUrl?: string
  fetch?: typeof fetch
  signal?: AbortSignal
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}

function isCommitIdentity(value: unknown): value is string {
  return typeof value === 'string' && (value === 'dev' || FULL_COMMIT.test(value))
}

function operationalMetadataUrl(configuredBase: string): string {
  const baseUrl = configuredBase.replace(/\/$/, '')
  const applicationRoot = baseUrl.endsWith(VERSIONED_API_SUFFIX)
    ? baseUrl.slice(0, -VERSIONED_API_SUFFIX.length)
    : baseUrl
  return `${applicationRoot}/build-meta`
}

async function problemBody(response: Response): Promise<ApiProblemBody> {
  try {
    const value = await response.json()
    return isRecord(value) ? value as ApiProblemBody : {}
  } catch {
    return {}
  }
}

async function metadataBody(response: Response): Promise<unknown> {
  try {
    return await response.json()
  } catch {
    throw new TypeError('Malformed backend build metadata response.')
  }
}

export async function fetchRuntimeMetadata(options: FetchRuntimeMetadataOptions = {}): Promise<RuntimeMetadata> {
  const request = options.fetch ?? fetch
  const response = await request(operationalMetadataUrl(options.baseUrl ?? DEFAULT_BASE_URL), {
    method: 'GET',
    cache: 'no-store',
    credentials: 'include',
    headers: new Headers({ Accept: 'application/json' }),
    signal: options.signal,
  })
  if (!response.ok) {
    throw new ApiProblem(response.status, await problemBody(response), 'Backend build metadata could not be loaded.')
  }

  const value = await metadataBody(response)
  if (
    !isRecord(value) ||
    value.schema_version !== 'build-meta.v1' ||
    typeof value.app_version !== 'string' || !value.app_version ||
    typeof value.protocol_version !== 'string' || !value.protocol_version ||
    !isCommitIdentity(value.git_sha) ||
    typeof value.build_environment !== 'string' || !value.build_environment ||
    typeof value.build_time !== 'string' || !value.build_time
  ) {
    throw new TypeError('Malformed backend build metadata response.')
  }

  return {
    schema_version: 'build-meta.v1',
    app_version: value.app_version,
    protocol_version: value.protocol_version,
    git_sha: value.git_sha,
    build_environment: value.build_environment,
    build_time: value.build_time,
  }
}

export function runtimeRevisionStatus(frontendSha: string, backendSha: string | null): RuntimeRevisionStatus {
  const frontendKnown = FULL_COMMIT.test(frontendSha)
  const backendKnown = Boolean(backendSha && FULL_COMMIT.test(backendSha))
  if (frontendKnown && backendKnown && frontendSha.toLowerCase() === backendSha!.toLowerCase()) {
    return {
      state: 'coherent',
      label: 'Revision verified',
      tone: 'ready',
      message: 'Frontend and backend report the same complete Git commit identity.',
      frontendSha,
      backendSha,
    }
  }
  if (frontendKnown && backendKnown) {
    return {
      state: 'mismatch',
      label: 'Revision mismatch',
      tone: 'failure',
      message: 'Frontend and backend report different Git revisions. Results may come from a mixed deployment and should not be treated as release-coherent.',
      frontendSha,
      backendSha,
    }
  }
  return {
    state: 'unknown',
    label: 'Revision unverified',
    tone: 'warning',
    message: 'At least one deployed component did not expose a complete Git commit identity, so revision coherence cannot be established.',
    frontendSha,
    backendSha,
  }
}

export function checkingRuntimeRevision(frontendSha: string): RuntimeRevisionStatus {
  return {
    state: 'checking',
    label: 'Checking revision',
    tone: 'info',
    message: 'Comparing the frontend build identity with the backend metadata endpoint.',
    frontendSha,
    backendSha: null,
  }
}

export function offlineRuntimeRevision(frontendSha: string, detail?: string): RuntimeRevisionStatus {
  return {
    state: 'offline',
    label: 'Revision unavailable',
    tone: 'offline',
    message: detail || 'Backend build metadata could not be reached, so deployment coherence is unknown.',
    frontendSha,
    backendSha: null,
  }
}
