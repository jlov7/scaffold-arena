import { ApiProblem, type ApiProblemBody } from './types'

const DEFAULT_BASE_URL = (import.meta.env.VITE_API_V1_BASE_URL ?? '/api/v1').replace(/\/$/, '')
const DIGEST = /^sha256:[a-f0-9]{64}$/

export interface XRaySnapshotSummary {
  snapshot_id: string
  source_name: string
  source_uri: string | null
  source_revision: string | null
  captured_at: string
  source_digest: string
  claim_ceiling: string
  idempotent_replay: boolean
  execution_started: false
  network_requested: false
}

export interface XRaySnapshotList {
  snapshots: XRaySnapshotSummary[]
  claim_ceiling: string
}

export interface ListXRaySnapshotsOptions {
  baseUrl?: string
  fetch?: typeof fetch
  projectId?: string
  signal?: AbortSignal
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}

function optionalString(value: unknown): string | null {
  return value === null || value === undefined ? null : typeof value === 'string' ? value : ''
}

function snapshot(value: unknown): XRaySnapshotSummary | null {
  if (!isRecord(value)) return null
  const sourceUri = optionalString(value.source_uri)
  const sourceRevision = optionalString(value.source_revision)
  if (
    typeof value.snapshot_id !== 'string' || !value.snapshot_id ||
    typeof value.source_name !== 'string' || !value.source_name ||
    sourceUri === '' || sourceRevision === '' ||
    typeof value.captured_at !== 'string' || !value.captured_at ||
    typeof value.source_digest !== 'string' || !DIGEST.test(value.source_digest) ||
    typeof value.claim_ceiling !== 'string' || !value.claim_ceiling ||
    typeof value.idempotent_replay !== 'boolean' ||
    value.execution_started !== false ||
    value.network_requested !== false
  ) return null

  return {
    snapshot_id: value.snapshot_id,
    source_name: value.source_name,
    source_uri: sourceUri,
    source_revision: sourceRevision,
    captured_at: value.captured_at,
    source_digest: value.source_digest,
    claim_ceiling: value.claim_ceiling,
    idempotent_replay: value.idempotent_replay,
    execution_started: false,
    network_requested: false,
  }
}

async function problemBody(response: Response): Promise<ApiProblemBody> {
  try {
    const value = await response.json()
    return isRecord(value) ? value as ApiProblemBody : {}
  } catch {
    return {}
  }
}

async function snapshotBody(response: Response): Promise<unknown> {
  try {
    return await response.json()
  } catch {
    throw new TypeError('Malformed X-Ray snapshot registry response.')
  }
}

export async function listXRaySnapshots(options: ListXRaySnapshotsOptions = {}): Promise<XRaySnapshotList> {
  const request = options.fetch ?? fetch
  const baseUrl = (options.baseUrl ?? DEFAULT_BASE_URL).replace(/\/$/, '')
  const headers = new Headers({ Accept: 'application/json' })
  if (options.projectId) headers.set('X-Arena-Project-ID', options.projectId)

  const response = await request(`${baseUrl}/xray/snapshots`, {
    method: 'GET',
    cache: 'no-store',
    credentials: 'include',
    headers,
    signal: options.signal,
  })
  if (!response.ok) {
    throw new ApiProblem(response.status, await problemBody(response), 'Captured X-Ray sources could not be loaded.')
  }

  const value = await snapshotBody(response)
  if (!isRecord(value) || !Array.isArray(value.snapshots) || typeof value.claim_ceiling !== 'string') {
    throw new TypeError('Malformed X-Ray snapshot registry response.')
  }
  const snapshots = value.snapshots.map(snapshot)
  if (snapshots.some((item) => item === null)) {
    throw new TypeError('Malformed X-Ray snapshot registry response.')
  }
  return { snapshots: snapshots as XRaySnapshotSummary[], claim_ceiling: value.claim_ceiling }
}
