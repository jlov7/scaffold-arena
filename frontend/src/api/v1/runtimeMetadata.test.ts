import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it, vi } from 'vitest'

import { fetchRuntimeMetadata, runtimeRevisionStatus } from './runtimeMetadata'

const frontendSha = 'a'.repeat(40)
const backendSha = 'b'.repeat(40)

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

describe('runtime metadata', () => {
  it('loads the backend build identity through the public operational endpoint without caches', async () => {
    const request = vi.fn().mockResolvedValue(response({
      schema_version: 'build-meta.v1',
      app_version: '0.9.1',
      protocol_version: '1.0',
      git_sha: frontendSha,
      build_environment: 'production',
      build_time: '2026-08-20T12:00:00.000Z',
    }))

    const result = await fetchRuntimeMetadata({
      baseUrl: 'https://api.example.test/api/v1',
      fetch: request,
    })

    expect(request).toHaveBeenCalledWith(
      'https://api.example.test/build-meta',
      expect.objectContaining({
        method: 'GET',
        cache: 'no-store',
        credentials: 'include',
        headers: expect.any(Headers),
      }),
    )
    expect(result.git_sha).toBe(frontendSha)
  })

  it('uses the same-origin operational endpoint for the default v1 base', async () => {
    const request = vi.fn().mockResolvedValue(response({
      schema_version: 'build-meta.v1',
      app_version: '0.9.1',
      protocol_version: '1.0',
      git_sha: 'dev',
      build_environment: 'development',
      build_time: 'unknown',
    }))

    await fetchRuntimeMetadata({ fetch: request })

    expect(request.mock.calls[0][0]).toBe('/build-meta')
  })

  it('proxies the same-origin operational endpoint during local development', () => {
    const config = readFileSync(resolve(process.cwd(), 'vite.config.ts'), 'utf8')
    expect(config).toContain("'/build-meta'")
    expect(config).toContain('target: apiProxyTarget')
  })

  it('fails closed on malformed build metadata', async () => {
    const request = vi.fn().mockResolvedValue(response({ git_sha: 'short' }))

    await expect(fetchRuntimeMetadata({ fetch: request })).rejects.toThrow(
      'Malformed backend build metadata response.',
    )
  })

  it('normalizes invalid JSON to the stable metadata error', async () => {
    const request = vi.fn().mockResolvedValue(new Response('{not-json', {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    }))

    await expect(fetchRuntimeMetadata({ fetch: request })).rejects.toThrow(
      'Malformed backend build metadata response.',
    )
  })

  it('reports exact revision coherence only when both complete commit identities match', () => {
    expect(runtimeRevisionStatus(frontendSha, frontendSha)).toMatchObject({
      state: 'coherent',
      tone: 'ready',
      label: 'Revision verified',
    })
    expect(runtimeRevisionStatus(frontendSha, backendSha)).toMatchObject({
      state: 'mismatch',
      tone: 'failure',
      label: 'Revision mismatch',
    })
    expect(runtimeRevisionStatus('dev', frontendSha)).toMatchObject({
      state: 'unknown',
      tone: 'warning',
      label: 'Revision unverified',
    })
  })
})
