import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  getFeatureFlag,
  setFeatureFlagOverride,
  clearFeatureFlagOverride,
} from './experiments/flags'

describe('feature flags', () => {
  beforeEach(() => {
    const store = new Map<string, string>()
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => void store.set(key, value),
      removeItem: (key: string) => void store.delete(key),
      clear: () => store.clear(),
    })
  })

  it('returns defaults when no override exists', () => {
    expect(getFeatureFlag('enable_model_mode')).toBe(true)
  })

  it('supports runtime overrides', () => {
    setFeatureFlagOverride('enable_model_mode', false)
    expect(getFeatureFlag('enable_model_mode')).toBe(false)

    clearFeatureFlagOverride('enable_model_mode')
    expect(getFeatureFlag('enable_model_mode')).toBe(true)
  })
})
