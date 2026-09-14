import { describe, expect, it, vi } from 'vitest'

import { listXRaySnapshots } from './xraySnapshots'

const digest = `sha256:${'a'.repeat(64)}`

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('listXRaySnapshots', () => {
  it('loads the exact durable project-scoped capture registry contract without caches', async () => {
    const request = vi.fn().mockResolvedValue(response({
      snapshots: [{
        snapshot_id: 'capture-one',
        source_name: 'Captured repository',
        source_uri: 'capture://repository',
        source_revision: 'abc123',
        captured_at: '2026-08-20T12:00:00Z',
        source_digest: digest,
        claim_ceiling: 'captured input only',
        idempotent_replay: false,
        execution_started: false,
        network_requested: false,
      }],
      claim_ceiling: 'captured input only',
    }))

    const result = await listXRaySnapshots({
      baseUrl: 'https://api.example.test/api/v1',
      fetch: request,
      projectId: 'project-one',
    })

    expect(request).toHaveBeenCalledWith(
      'https://api.example.test/api/v1/xray/snapshots',
      expect.objectContaining({
        method: 'GET',
        cache: 'no-store',
        credentials: 'include',
        headers: expect.any(Headers),
      }),
    )
    const headers = request.mock.calls[0][1].headers as Headers
    expect(headers.get('X-Arena-Project-ID')).toBe('project-one')
    expect(headers.get('Accept')).toBe('application/json')
    expect(result.snapshots[0]).toEqual(expect.objectContaining({
      snapshot_id: 'capture-one',
      source_digest: digest,
      execution_started: false,
      network_requested: false,
    }))
  })

  it('rejects fields that falsely imply stronger capture metadata', async () => {
    const request = vi.fn().mockResolvedValue(response({
      snapshots: [{
        snapshot_id: 'capture-one',
        source_name: 'Captured repository',
        source_uri: null,
        source_revision: null,
        captured_at: '2026-08-20T12:00:00Z',
        source_digest: digest,
        claim_ceiling: 'captured input only',
        idempotent_replay: false,
        execution_started: true,
        network_requested: false,
      }],
      claim_ceiling: 'captured input only',
    }))

    await expect(listXRaySnapshots({ fetch: request })).rejects.toThrow(
      'Malformed X-Ray snapshot registry response.',
    )
  })

  it('rejects malformed capture-registry responses instead of inventing an empty list', async () => {
    const request = vi.fn().mockResolvedValue(response({ snapshots: 'not-an-array' }))

    await expect(listXRaySnapshots({ fetch: request })).rejects.toThrow(
      'Malformed X-Ray snapshot registry response.',
    )
  })

  it('normalizes invalid JSON to the stable registry error', async () => {
    const request = vi.fn().mockResolvedValue(new Response('{not-json', {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))

    await expect(listXRaySnapshots({ fetch: request })).rejects.toThrow(
      'Malformed X-Ray snapshot registry response.',
    )
  })
})
