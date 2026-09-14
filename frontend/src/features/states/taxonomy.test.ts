import { describe, expect, it } from 'vitest'

import { describeResultsWorkspaceState } from './taxonomy'

describe('describeResultsWorkspaceState', () => {
  it('returns blocked state first when blocker is active', () => {
    const state = describeResultsWorkspaceState({
      isRunning: true,
      hasResults: true,
      hasError: true,
      hasBlocker: true,
    })
    expect(state.kind).toBe('blocked')
  })

  it('returns empty state when no results are loaded', () => {
    const state = describeResultsWorkspaceState({
      isRunning: false,
      hasResults: false,
      hasError: false,
      hasBlocker: false,
    })
    expect(state.kind).toBe('empty')
  })
})
