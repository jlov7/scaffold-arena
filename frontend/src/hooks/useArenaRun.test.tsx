import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useArenaRun } from './useArenaRun'

const createArenaRunMock = vi.fn()
const cancelRunMock = vi.fn()
const fetchRunDetailsMock = vi.fn()
const fetchRunDiagnosticsMock = vi.fn()

vi.mock('../api/client', () => ({
  createArenaRun: (...args: unknown[]) => createArenaRunMock(...args),
  cancelRun: (...args: unknown[]) => cancelRunMock(...args),
  fetchRunDiagnostics: (...args: unknown[]) => fetchRunDiagnosticsMock(...args),
  fetchRunDetails: (...args: unknown[]) => fetchRunDetailsMock(...args),
  getEventStreamUrl: (runId: string) => `/api/runs/${runId}/events`,
}))

class MockEventSource {
  static instances: MockEventSource[] = []
  url: string
  onopen: ((event: Event) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  listeners: Record<string, Array<(event: MessageEvent) => void>> = {}

  constructor(url: string) {
    this.url = url
    MockEventSource.instances.push(this)
    queueMicrotask(() => {
      this.onopen?.(new Event('open'))
    })
  }

  addEventListener(type: string, cb: (event: MessageEvent) => void) {
    this.listeners[type] ??= []
    this.listeners[type].push(cb)
  }

  close() {}
}

describe('useArenaRun', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.useFakeTimers()
    MockEventSource.instances = []
    createArenaRunMock.mockReset()
    cancelRunMock.mockReset()
    fetchRunDetailsMock.mockReset()
    fetchRunDiagnosticsMock.mockReset()
    fetchRunDiagnosticsMock.mockResolvedValue({ timeline: [] })
    vi.stubGlobal('EventSource', MockEventSource as unknown as typeof EventSource)
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('sets running immediately and ignores rapid double-start', async () => {
    let resolveRun: ((value: unknown) => void) | null = null
    createArenaRunMock.mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveRun = resolve
        }),
    )

    const { result } = renderHook(() =>
      useArenaRun([
        { id: 'bare', name: 'Bare', subtitle: '' },
        { id: 'plan_execute_verify', name: 'Plan', subtitle: '' },
      ]),
    )

    act(() => {
      void result.current.startRun('extraction', 'claude-sonnet-4-6')
    })
    expect(result.current.isRunning).toBe(true)

    await act(async () => {
      const p2 = result.current.startRun('extraction', 'claude-sonnet-4-6')
      resolveRun?.({
        run_id: 'run_1',
        stream_url: '/api/runs/run_1/events',
        cancel_url: '/api/runs/run_1/cancel',
      })
      await p2
    })

    expect(createArenaRunMock).toHaveBeenCalledTimes(1)
  })

  it('reverts to idle and stores runError when create run fails', async () => {
    createArenaRunMock.mockRejectedValue(new Error('backend down'))

    const { result } = renderHook(() =>
      useArenaRun([{ id: 'bare', name: 'Bare', subtitle: '' }]),
    )

    await act(async () => {
      try {
        await result.current.startRun('extraction', 'claude-sonnet-4-6')
      } catch {
        // expected
      }
    })

    expect(result.current.isRunning).toBe(false)
    expect(result.current.runError).toContain('backend down')
  })

  it('deduplicates repeated start requests with same payload', async () => {
    createArenaRunMock.mockResolvedValue({
      run_id: 'run_1',
      stream_url: '/api/runs/run_1/events',
      cancel_url: '/api/runs/run_1/cancel',
    })

    const { result } = renderHook(() =>
      useArenaRun([{ id: 'bare', name: 'Bare', subtitle: '' }]),
    )

    await act(async () => {
      await result.current.startRun('extraction', 'claude-sonnet-4-6')
      await result.current.startRun('extraction', 'claude-sonnet-4-6')
    })

    expect(createArenaRunMock).toHaveBeenCalledTimes(1)
  })

  it('hydrates results from run details after stream retry exhaustion', async () => {
    createArenaRunMock.mockResolvedValue({
      run_id: 'run_1',
      stream_url: '/api/runs/run_1/events',
      cancel_url: '/api/runs/run_1/cancel',
    })
    fetchRunDetailsMock.mockResolvedValue({
      run_id: 'run_1',
      kind: 'arena',
      task_id: 'extraction',
      model_id: 'claude-sonnet-4-6',
      status: 'completed',
      winner_id: 'bare',
      results: {
        bare: {
          output: 'ok',
          metrics: {
            input_tokens: 1,
            output_tokens: 1,
            cost_usd: 0.001,
            wall_time_ms: 10,
            num_api_calls: 1,
          },
          evaluation: {
            total_score: 99,
            breakdown: { schema_validity: 99 },
            weights: { schema_validity: { weight: 1, type: 'deterministic' } },
            notes: [],
          },
        },
      },
    })

    const { result } = renderHook(() =>
      useArenaRun([{ id: 'bare', name: 'Bare', subtitle: '' }]),
    )

    await act(async () => {
      await result.current.startRun('extraction', 'claude-sonnet-4-6')
    })

    const source = MockEventSource.instances.at(-1)
    expect(source).toBeDefined()
    if (!source) return

    await act(async () => {
      for (let i = 0; i < 6; i++) {
        source.onerror?.(new Event('error'))
        vi.advanceTimersByTime(10_000)
      }
      await Promise.resolve()
    })

    expect(fetchRunDetailsMock).toHaveBeenCalledWith('run_1')
    expect(result.current.finalResults?.bare?.evaluation.total_score).toBe(99)
    expect(result.current.connectionState).toBe('idle')
    expect(result.current.runError).toBeNull()
  })

  it('hydrates from run details on first retry when stream closes before terminal event', async () => {
    createArenaRunMock.mockResolvedValue({
      run_id: 'run_1',
      stream_url: '/api/runs/run_1/events',
      cancel_url: '/api/runs/run_1/cancel',
    })
    fetchRunDetailsMock.mockResolvedValue({
      run_id: 'run_1',
      kind: 'arena',
      task_id: 'extraction',
      model_id: 'claude-sonnet-4-6',
      status: 'completed',
      winner_id: 'bare',
      results: {
        bare: {
          output: 'ok',
          metrics: {
            input_tokens: 1,
            output_tokens: 1,
            cost_usd: 0.001,
            wall_time_ms: 10,
            num_api_calls: 1,
          },
          evaluation: {
            total_score: 99,
            breakdown: { schema_validity: 99 },
            weights: { schema_validity: { weight: 1, type: 'deterministic' } },
            notes: [],
          },
        },
      },
    })

    const { result } = renderHook(() =>
      useArenaRun([{ id: 'bare', name: 'Bare', subtitle: '' }]),
    )

    await act(async () => {
      await result.current.startRun('extraction', 'claude-sonnet-4-6')
    })

    const source = MockEventSource.instances.at(-1)
    expect(source).toBeDefined()
    if (!source) return

    await act(async () => {
      source.onerror?.(new Event('error'))
      await Promise.resolve()
      await Promise.resolve()
    })

    expect(fetchRunDetailsMock).toHaveBeenCalledWith('run_1')
    expect(result.current.isRunning).toBe(false)
    expect(result.current.connectionState).toBe('idle')
    expect(result.current.finalResults?.bare?.evaluation.total_score).toBe(99)
  })
})
