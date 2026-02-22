import { renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { useReducedMotion } from './useReducedMotion'

describe('useReducedMotion', () => {
  it('returns true when prefers-reduced-motion is set', () => {
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({
      matches: true,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }))

    const { result } = renderHook(() => useReducedMotion())
    expect(result.current).toBe(true)
  })
})
