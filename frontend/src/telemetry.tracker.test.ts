import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  getTelemetryConsent,
  setTelemetryConsent,
  trackEvent,
  resetTrackerForTests,
} from './telemetry/tracker'

describe('telemetry tracker', () => {
  beforeEach(() => {
    const store = new Map<string, string>()
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => void store.set(key, value),
      removeItem: (key: string) => void store.delete(key),
      clear: () => store.clear(),
    })
    resetTrackerForTests()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('defaults consent to disabled', () => {
    expect(getTelemetryConsent()).toBe(false)
  })

  it('tracks only when consent is enabled', () => {
    trackEvent('run_started', { task_id: 'extraction' })
    expect(window.__arenaTelemetryEvents).toHaveLength(0)

    setTelemetryConsent(true)
    trackEvent('run_started', { task_id: 'extraction' })
    expect(window.__arenaTelemetryEvents).toHaveLength(1)
  })
})
