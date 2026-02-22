import { beforeEach, describe, expect, it, vi } from 'vitest'

import { createArenaRun, fetchMeta, setApiToken } from './client'

describe('api client', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.stubEnv('VITE_API_TOKEN', '')
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
})
