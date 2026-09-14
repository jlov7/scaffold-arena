import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useSSE } from './useSSE'

class MockEventSource {
  static instances: MockEventSource[] = []
  url: string
  onopen: ((event: Event) => void) | null = null
  onerror: ((event: Event) => void) | null = null

  constructor(url: string) {
    this.url = url
    MockEventSource.instances.push(this)
  }

  addEventListener() {}

  close() {}
}

describe('useSSE', () => {
  beforeEach(() => {
    MockEventSource.instances = []
    vi.useFakeTimers()
    vi.stubGlobal('EventSource', MockEventSource as unknown as typeof EventSource)
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('retries on disconnect and fails after max retries', () => {
    const retrying = vi.fn()
    const failed = vi.fn()

    renderHook(() =>
      useSSE('/events', () => {}, {
        onRetrying: retrying,
        onFailed: failed,
        maxRetries: 2,
      }),
    )

    const first = MockEventSource.instances[0]
    act(() => first.onerror?.(new Event('error')))
    expect(retrying).toHaveBeenLastCalledWith(1)

    act(() => vi.advanceTimersByTime(500))
    const second = MockEventSource.instances[1]
    act(() => second.onerror?.(new Event('error')))
    expect(retrying).toHaveBeenLastCalledWith(2)

    act(() => vi.advanceTimersByTime(1000))
    const third = MockEventSource.instances[2]
    act(() => third.onerror?.(new Event('error')))
    expect(failed).toHaveBeenCalledTimes(1)
  })
})
