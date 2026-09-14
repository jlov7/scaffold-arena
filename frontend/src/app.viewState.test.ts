import { describe, expect, it } from 'vitest'

import { appViewFromPath, appPathForView } from './app/viewState'

describe('viewState', () => {
  it('maps known paths to views', () => {
    expect(appViewFromPath('/')).toBe('arena')
    expect(appViewFromPath('/arena')).toBe('arena')
    expect(appViewFromPath('/results')).toBe('results')
    expect(appViewFromPath('/history')).toBe('history')
    expect(appViewFromPath('/leaderboard')).toBe('leaderboard')
    expect(appViewFromPath('/settings')).toBe('settings')
  })

  it('falls back to arena for unknown paths', () => {
    expect(appViewFromPath('/nope')).toBe('arena')
  })

  it('maps views to canonical paths', () => {
    expect(appPathForView('arena')).toBe('/arena')
    expect(appPathForView('results')).toBe('/results')
    expect(appPathForView('history')).toBe('/history')
    expect(appPathForView('leaderboard')).toBe('/leaderboard')
    expect(appPathForView('settings')).toBe('/settings')
  })
})
