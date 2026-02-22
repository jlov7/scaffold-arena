import { renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { useOnlineStatus } from './useOnlineStatus'

describe('useOnlineStatus', () => {
  it('tracks browser online state', () => {
    vi.spyOn(window.navigator, 'onLine', 'get').mockReturnValue(false)
    const { result } = renderHook(() => useOnlineStatus())
    expect(result.current).toBe(false)
  })
})
