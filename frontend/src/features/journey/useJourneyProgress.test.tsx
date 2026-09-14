import { renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { useJourneyProgress } from './useJourneyProgress'

describe('useJourneyProgress', () => {
  it('returns setup state before first run', () => {
    const { result } = renderHook(() =>
      useJourneyProgress({
        isRunning: false,
        hasEverRun: false,
        finalResults: null,
        comparisonCount: 0,
        autopsyOpen: false,
        hasExported: false,
      }),
    )

    expect(result.current.stage).toBe('setup')
    expect(result.current.steps[0]?.status).toBe('current')
    expect(result.current.successCriteria).toMatch(/Task and model selected/i)
  })

  it('returns iterate when analysis actions have started', () => {
    const { result } = renderHook(() =>
      useJourneyProgress({
        isRunning: false,
        hasEverRun: true,
        finalResults: {
          bare: {
            output: 'ok',
            error: undefined,
            metrics: {
              input_tokens: 1,
              output_tokens: 1,
              cost_usd: 0.001,
              wall_time_ms: 1,
              num_api_calls: 1,
            },
            evaluation: {
              total_score: 88,
              breakdown: { schema: 88 },
              weights: { schema: { weight: 1, type: 'deterministic' } },
              notes: [],
            },
          },
        },
        comparisonCount: 1,
        autopsyOpen: false,
        hasExported: false,
      }),
    )

    expect(result.current.stage).toBe('iterate')
    expect(result.current.helpTitle.toLowerCase()).toContain(
      'turn findings into action',
    )
    expect(result.current.successCriteria).toMatch(/Comparison\/autopsy evidence/i)
  })
})
