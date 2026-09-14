import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  createArenaRun,
  fetchMeta,
  getLlmApiKey,
  setApiToken,
  setLlmApiKey,
} from './client'

describe('api client', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    const store = new Map<string, string>()
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => void store.set(key, value),
      removeItem: (key: string) => void store.delete(key),
      clear: () => store.clear(),
    })
  })

  it('sends bearer token and json body for POST requests', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        run_id: 'run_1',
        stream_url: '/api/runs/run_1/events',
        cancel_url: '/api/runs/run_1/cancel',
      }),
    })
    vi.stubGlobal('fetch', fetchMock)

    setApiToken('secret-token')

    await createArenaRun({
      task_id: 'extraction',
      model_id: 'claude-sonnet-4-6',
      scaffold_ids: ['bare'],
    })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const call = fetchMock.mock.calls[0]
    expect(call[0]).toBe('/api/runs')
    expect(call[1].headers.Authorization).toBe('Bearer secret-token')
    expect(call[1].body).toContain('"task_id":"extraction"')
  })

  it('throws status + message for failed responses', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: 'Server Error',
      text: async () => 'boom',
    })
    vi.stubGlobal('fetch', fetchMock)

    await expect(fetchMeta()).rejects.toThrow('500: boom')
  })

  it('keeps llm keys in memory and clears legacy browser storage', () => {
    localStorage.setItem('scaffold_arena_llm_api_key', 'legacy-key')
    localStorage.setItem('scaffold_arena_llm_api_key_storage_mode', 'persistent')
    setLlmApiKey('sk-session')
    expect(getLlmApiKey()).toBe('sk-session')
    expect(localStorage.getItem('scaffold_arena_llm_api_key')).toBeNull()
    expect(localStorage.getItem('scaffold_arena_llm_api_key_storage_mode')).toBeNull()
  })

  it('keeps legacy API tokens in memory and clears browser storage', () => {
    localStorage.setItem('scaffold_arena_api_token', 'legacy-token')
    setApiToken('session-token')

    expect(localStorage.getItem('scaffold_arena_api_token')).toBeNull()
  })

  it('sends idempotency key when provided for run creation', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        run_id: 'run_1',
        stream_url: '/api/runs/run_1/events',
        cancel_url: '/api/runs/run_1/cancel',
      }),
    })
    vi.stubGlobal('fetch', fetchMock)
    setApiToken('secret-token')

    await createArenaRun({
      task_id: 'extraction',
      model_id: 'claude-sonnet-4-6',
      scaffold_ids: ['bare'],
      idempotency_key: 'idem-1',
    })

    const call = fetchMock.mock.calls[0]
    expect(call[1].headers.Authorization).toBe('Bearer secret-token')
    expect(call[1].headers['X-Idempotency-Key']).toBe('idem-1')
  })
})
