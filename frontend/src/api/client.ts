import type { AppMeta, AutopsyResult } from '../types'

const BASE = '/api'

async function fetchJSON<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${url}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText)
    throw new Error(`${res.status}: ${text}`)
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

export function getEventStreamUrl(runId: string): string {
  return `${BASE}/runs/${runId}/events`
}
