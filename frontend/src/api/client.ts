import type { AppMeta, AutopsyResult, LeaderboardStats } from '../types'

const BASE = '/api'
const TOKEN_STORAGE_KEY = 'scaffold_arena_api_token'
const LLM_KEY_STORAGE_KEY = 'scaffold_arena_llm_api_key'

function sanitizeErrorText(text: string): string {
  return text
    .replace(/Bearer\\s+[A-Za-z0-9._-]+/gi, 'Bearer [redacted]')
    .replace(/("?token"?\\s*:\\s*")[^"]+("?)/gi, '$1[redacted]$2')
}

function getApiToken(): string | null {
  const envToken = import.meta.env.VITE_API_TOKEN as string | undefined
  if (envToken && envToken.trim().length > 0) return envToken.trim()
  try {
    const stored = localStorage.getItem(TOKEN_STORAGE_KEY)
    return stored && stored.trim().length > 0 ? stored.trim() : null
  } catch {
    return null
  }
}

export function setApiToken(token: string): void {
  try {
    if (!token.trim()) {
      localStorage.removeItem(TOKEN_STORAGE_KEY)
      return
    }
    localStorage.setItem(TOKEN_STORAGE_KEY, token.trim())
  } catch {
    // no-op when storage is unavailable
  }
}

export function getLlmApiKey(): string | null {
  try {
    const stored = localStorage.getItem(LLM_KEY_STORAGE_KEY)
    return stored && stored.trim().length > 0 ? stored.trim() : null
  } catch {
    return null
  }
}

export function setLlmApiKey(key: string): void {
  try {
    if (!key.trim()) {
      localStorage.removeItem(LLM_KEY_STORAGE_KEY)
      return
    }
    localStorage.setItem(LLM_KEY_STORAGE_KEY, key.trim())
  } catch {
    // no-op when storage is unavailable
  }
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
    headers,
    ...init,
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
}): Promise<{ run_id: string; stream_url: string; cancel_url: string }> {
  return fetchJSON('/runs', { method: 'POST', body: JSON.stringify(params) })
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

export async function fetchStats(limit: number = 1000): Promise<LeaderboardStats> {
  return fetchJSON(`/stats?limit=${limit}`)
}

export function getEventStreamUrl(runId: string): string {
  return `${BASE}/runs/${runId}/events`
}
