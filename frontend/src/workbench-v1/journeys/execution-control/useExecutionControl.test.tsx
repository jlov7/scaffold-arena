import { act, renderHook, waitFor } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { useExecutionControl } from './useExecutionControl'
import type { ArenaV1Client } from '../study-design-preflight/types'
import type { PreflightReport } from '../../../api/v1/client'

const detail = (id: string, status = 'completed') => ({ execution_id: id, experiment_id: 'exp', status, attempts: [], jobs: [], counts: { attempts: 0, jobs: 0 } })
const pass = { verdict: 'PASS' } as PreflightReport
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}
function client() {
  return {
    executions: {
      list: vi.fn(async () => ({ executions: [detail('A'), detail('B')], pagination: { next_offset: 2 as number | null } })),
      get: vi.fn(async (id: string) => detail(id)), events: async function* () {},
      create: vi.fn(async () => ({ execution_id: 'A' })), cancel: vi.fn(async () => ({})), resume: vi.fn(async () => ({})),
    },
    offlineDemo: { execute: vi.fn<(id: string, options: { idempotencyKey: string }) => Promise<{ execution_id: string }>>().mockResolvedValue({ execution_id: 'A' }) },
    attempts: { get: vi.fn(async () => ({})), trace: vi.fn(async () => ({})) },
  }
}

it.each(['route', 'project', 'newer choice'] as const)('fences a delayed choose against a newer %s', async (change) => {
  const c = client(); const selected = vi.fn()
  const { result, rerender } = renderHook(({ id, projectId }) => useExecutionControl({ client: c as unknown as ArenaV1Client, frozenExperimentId: 'exp', requestedExecutionId: id, projectId, preflightReport: pass, onExecutionSelected: selected }), { initialProps: { id: 'A', projectId: 'one' } })
  await waitFor(() => expect(result.current.selected?.execution_id).toBe('A'))
  const pending = deferred<ReturnType<typeof detail>>()
  c.executions.get.mockImplementationOnce(() => pending.promise)
  let choosing!: Promise<void>
  act(() => { choosing = result.current.choose('A') })
  if (change === 'newer choice') await act(async () => { await result.current.choose('B') })
  else rerender({ id: 'B', projectId: change === 'project' ? 'two' : 'one' })
  await waitFor(() => expect(result.current.selected?.execution_id).toBe('B'))
  selected.mockClear()
  await act(async () => { pending.resolve(detail('A')); await choosing })
  expect(result.current.selected?.execution_id).toBe('B')
  expect(selected).not.toHaveBeenCalled()
})

it.each(['page', 'attempt', 'trace', 'create', 'offline', 'cancel', 'resume'] as const)('discards delayed %s results after route navigation', async (action) => {
  const c = client(); const selected = vi.fn()
  const { result, rerender } = renderHook(({ id }) => useExecutionControl({ client: c as unknown as ArenaV1Client, frozenExperimentId: 'exp', requestedExecutionId: id, preflightReport: pass, onExecutionSelected: selected }), { initialProps: { id: 'A' } })
  await waitFor(() => expect(result.current.selected?.execution_id).toBe('A'))
  const pending = deferred<never>()
  let response: unknown = {}
  let operation!: Promise<unknown>
  act(() => {
    if (action === 'page') { c.executions.list.mockImplementationOnce(() => pending.promise); response = { executions: [detail('stale')], pagination: { next_offset: 99 } }; operation = result.current.loadMore() }
    if (action === 'attempt') { c.attempts.get.mockImplementationOnce(() => pending.promise); operation = result.current.inspectAttempt('old') }
    if (action === 'trace') { c.attempts.trace.mockImplementationOnce(() => pending.promise); operation = result.current.inspectTrace('old') }
    if (action === 'create') { c.executions.create.mockImplementationOnce(() => pending.promise); response = { execution_id: 'A' }; operation = result.current.create({} as never, 'key') }
    if (action === 'offline') { c.offlineDemo.execute.mockImplementationOnce(() => pending.promise); response = { execution_id: 'A' }; operation = result.current.createOfflineDemo() }
    if (action === 'cancel') { c.executions.cancel.mockImplementationOnce(() => pending.promise); operation = result.current.cancel() }
    if (action === 'resume') { c.executions.resume.mockImplementationOnce(() => pending.promise); operation = result.current.resume() }
  })
  rerender({ id: 'B' })
  await waitFor(() => expect(result.current.selected?.execution_id).toBe('B'))
  await act(async () => { pending.resolve(response as never); await operation })
  expect(result.current.selected?.execution_id).toBe('B')
  expect(result.current.attempt).toBeNull(); expect(result.current.trace).toBeNull()
  expect(result.current.executions.map((item) => item.execution_id)).not.toContain('stale')
  expect(result.current.nextOffset).toBe(2)
  expect(result.current.message).toBe('')
  expect(result.current.busy).toBe(false)
  expect(selected).not.toHaveBeenCalled()
})

it('uses a fresh key after completion while retaining an uncertain request key and scoping projects', async () => {
  const c = client()
  const { result, rerender } = renderHook(({ projectId }) => useExecutionControl({ client: c as unknown as ArenaV1Client, projectId, frozenExperimentId: 'exp', requestedExecutionId: 'A', preflightReport: pass }), { initialProps: { projectId: 'one' } })
  await waitFor(() => expect(result.current.selected?.status).toBe('completed'))
  await act(async () => { await result.current.createOfflineDemo() })
  c.offlineDemo.execute.mockRejectedValueOnce(new Error('uncertain transport'))
  await act(async () => { await result.current.createOfflineDemo() })
  await act(async () => { await result.current.createOfflineDemo() })
  const keys = c.offlineDemo.execute.mock.calls.map((call) => call[1].idempotencyKey)
  expect(keys[1]).not.toBe(keys[0]); expect(keys[2]).toBe(keys[1])
  rerender({ projectId: 'two' })
  await waitFor(() => expect(result.current.state).toBe('ready'))
  await act(async () => { await result.current.createOfflineDemo() })
  expect(c.offlineDemo.execute.mock.calls[3][1].idempotencyKey).not.toBe(keys[2])
})

it('retains the key for a nonterminal execution recovery', async () => {
  const c = client(); c.executions.get.mockImplementation(async (id) => detail(id, 'running'))
  const { result } = renderHook(() => useExecutionControl({ client: c as unknown as ArenaV1Client, frozenExperimentId: 'exp', preflightReport: pass }))
  await waitFor(() => expect(result.current.selected?.status).toBe('running'))
  await act(async () => { await result.current.createOfflineDemo() })
  await act(async () => { await result.current.createOfflineDemo() })
  expect(c.offlineDemo.execute.mock.calls[1][1].idempotencyKey).toBe(c.offlineDemo.execute.mock.calls[0][1].idempotencyKey)
})

it('starts C after A and B complete even when history selection returns to A', async () => {
  const c = client()
  c.offlineDemo.execute.mockResolvedValueOnce({ execution_id: 'A' }).mockResolvedValueOnce({ execution_id: 'B' }).mockResolvedValueOnce({ execution_id: 'C' })
  const { result } = renderHook(() => useExecutionControl({ client: c as unknown as ArenaV1Client, frozenExperimentId: 'exp', preflightReport: pass }))
  await waitFor(() => expect(result.current.state).toBe('ready'))
  await act(async () => { await result.current.createOfflineDemo() })
  await act(async () => { await result.current.createOfflineDemo() })
  expect(result.current.selected?.execution_id).toBe('B')
  await act(async () => { await result.current.choose('A') })
  await act(async () => { await result.current.createOfflineDemo() })
  expect(result.current.selected?.execution_id).toBe('C')
  expect(new Set(c.offlineDemo.execute.mock.calls.map((call) => call[1].idempotencyKey)).size).toBe(3)
})
