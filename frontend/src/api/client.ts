import type { AppMeta, AutopsyResult, LeaderboardStats } from '../types'

const RAW_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim()
const BASE = RAW_BASE && RAW_BASE.length > 0 ? RAW_BASE.replace(/\/$/, '') : '/api'
const TOKEN_STORAGE_KEY = 'scaffold_arena_api_token'
const LLM_KEY_STORAGE_KEY = 'scaffold_arena_llm_api_key'
const LLM_KEY_STORAGE_MODE_KEY = 'scaffold_arena_llm_api_key_storage_mode'

let sessionLlmApiKey: string | null = null
let sessionApiToken: string | null = null

function clearLegacyBrowserSecrets(): void {
  try {
    localStorage.removeItem(TOKEN_STORAGE_KEY)
    localStorage.removeItem(LLM_KEY_STORAGE_KEY)
    localStorage.removeItem(LLM_KEY_STORAGE_MODE_KEY)
  } catch {
    // Storage is optional, and legacy secret cleanup is best-effort.
  }
}

clearLegacyBrowserSecrets()

function sanitizeErrorText(text: string): string {
  return text
    .replace(/Bearer\\s+[A-Za-z0-9._-]+/gi, 'Bearer [redacted]')
    .replace(/("?token"?\\s*:\\s*")[^"]+("?)/gi, '$1[redacted]$2')
}

function getApiToken(): string | null {
  return sessionApiToken
}

export function setApiToken(token: string): void {
  sessionApiToken = token.trim() || null
  clearLegacyBrowserSecrets()
}

export function getLlmApiKey(): string | null {
  clearLegacyBrowserSecrets()
  return sessionLlmApiKey
}

export function setLlmApiKey(key: string): void {
  sessionLlmApiKey = key.trim() || null
  clearLegacyBrowserSecrets()
}

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const token = getApiToken()
  const llmKey = getLlmApiKey()
  const headers: HeadersInit = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(llmKey ? { 'X-LLM-API-Key': llmKey } : {}),
    ...(init?.headers ?? {}),
  }
  const res = await fetch(`${BASE}${url}`, {
    ...init,
    headers,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(`${res.status}: ${sanitizeErrorText(text)}`)
  }
  return res.json()
}

export async function fetchMeta(): Promise<AppMeta> {
  return fetchJSON('/meta')
}

export async function createArenaRun(params: {
  task_id: string
  model_id: string
  scaffold_ids: string[]
  options?: Record<string, unknown>
  custom_task?: Record<string, unknown>
  idempotency_key?: string
}): Promise<{ run_id: string; stream_url: string; cancel_url: string; idempotent_replay?: boolean }> {
  const { idempotency_key, ...payload } = params
  const init: RequestInit = {
    method: 'POST',
    body: JSON.stringify(payload),
  }
  if (idempotency_key) {
    init.headers = { 'X-Idempotency-Key': idempotency_key }
  }
  return fetchJSON('/runs', init)
}

export async function cancelRun(runId: string): Promise<void> {
  await fetchJSON(`/runs/${runId}/cancel`, { method: 'POST' })
}

export async function createComparison(params: {
  task_id: string
  expensive_model_id: string
  cheap_model_id: string
  winning_scaffold_id: string
  control_scaffold_id?: string
  options?: Record<string, unknown>
}): Promise<{ run_id: string; stream_url: string }> {
  return fetchJSON('/comparisons', { method: 'POST', body: JSON.stringify(params) })
}

export async function createModelComparison(params: {
  task_id: string
  model_a_id: string
  model_b_id: string
  scaffold_id: string
  options?: Record<string, unknown>
}): Promise<{ run_id: string; stream_url: string }> {
  return fetchJSON('/model-comparisons', {
    method: 'POST',
    body: JSON.stringify(params),
  })
}

export async function runAutopsy(params: {
  task_id: string
  scaffold_id: string
  output: string
  evaluation: Record<string, unknown>
  metrics?: Record<string, unknown>
}): Promise<AutopsyResult> {
  return fetchJSON('/autopsy', { method: 'POST', body: JSON.stringify(params) })
}

export async function createPatchRerun(params: {
  task_id: string
  model_id: string
  scaffold_id: string
  base_config?: Record<string, unknown>
  patch?: Record<string, unknown>
}): Promise<{ run_id: string; stream_url: string }> {
  return fetchJSON('/patch-reruns', { method: 'POST', body: JSON.stringify(params) })
}

export async function generateReport(params: {
  task_id: string
  model_id: string
  results: Record<string, unknown>
  comparison?: Record<string, unknown> | null
  autopsy?: Record<string, unknown> | null
  patch_rerun?: Record<string, unknown> | null
}): Promise<{ markdown: string; pdf_base64: string | null }> {
  return fetchJSON('/reports', { method: 'POST', body: JSON.stringify(params) })
}

export async function fetchRuns(limit: number = 50): Promise<{ runs: Array<Record<string, unknown>> }> {
  return fetchJSON(`/runs?limit=${limit}`)
}

export async function fetchRunDetails(runId: string): Promise<Record<string, unknown>> {
  return fetchJSON(`/runs/${runId}`)
}

export interface RunPreflightCheck {
  id: string
  status: 'pass' | 'warn' | 'fail'
  message: string
  action?: string
}

export interface RunPreflightResult {
  ok: boolean
  can_run: boolean
  checked_at: number
  checks: RunPreflightCheck[]
}

export async function runPreflight(params: {
  task_id: string
  model_id: string
  scaffold_ids: string[]
  options?: Record<string, unknown>
}): Promise<RunPreflightResult> {
  return fetchJSON('/preflight', { method: 'POST', body: JSON.stringify(params) })
}

export async function fetchRunDiagnostics(runId: string): Promise<Record<string, unknown>> {
  return fetchJSON(`/runs/${runId}/diagnostics`)
}

export async function exportRunBundle(runId: string): Promise<Blob> {
  const token = getApiToken()
  const llmKey = getLlmApiKey()
  const headers: HeadersInit = {
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(llmKey ? { 'X-LLM-API-Key': llmKey } : {}),
  }
  const res = await fetch(`${BASE}/runs/${runId}/export-bundle`, {
    method: 'GET',
    headers,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(`${res.status}: ${sanitizeErrorText(text)}`)
  }
  return res.blob()
}

export async function fetchStats(limit: number = 1000): Promise<LeaderboardStats> {
  return fetchJSON(`/stats?limit=${limit}`)
}

export function getEventStreamUrl(runId: string): string {
  return `${BASE}/runs/${runId}/events`
}
