import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useViewNavigation } from './useViewNavigation'

const VIEW_STORAGE_KEY = 'scaffold_arena_last_view'

describe('useViewNavigation', () => {
  beforeEach(() => {
    const storage = new Map<string, string>()
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => {
        storage.set(key, value)
      },
      removeItem: (key: string) => {
        storage.delete(key)
      },
    })
    window.localStorage.removeItem(VIEW_STORAGE_KEY)
    window.history.replaceState({}, '', '/arena')
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('normalizes root path to arena', () => {
    window.history.replaceState({}, '', '/')
    const { result } = renderHook(() => useViewNavigation())

    expect(result.current.activeView).toBe('arena')
    expect(window.location.pathname).toBe('/arena')
  })

  it('restores stored non-arena view when no run_id param', () => {
    window.localStorage.setItem(VIEW_STORAGE_KEY, '/leaderboard')
    const { result } = renderHook(() => useViewNavigation())

    expect(result.current.activeView).toBe('leaderboard')
    expect(window.location.pathname).toBe('/leaderboard')
  })

  it('supports restoring the results workspace', () => {
    window.localStorage.setItem(VIEW_STORAGE_KEY, '/results')
    const { result } = renderHook(() => useViewNavigation())

    expect(result.current.activeView).toBe('results')
    expect(window.location.pathname).toBe('/results')
  })

  it('pushes path when navigating to a view', () => {
    const { result } = renderHook(() => useViewNavigation())

    act(() => {
      result.current.navigateToView('history')
    })

    expect(result.current.activeView).toBe('history')
    expect(window.location.pathname).toBe('/history')
  })
})
