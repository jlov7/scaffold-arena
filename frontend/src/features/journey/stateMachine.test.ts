import { describe, expect, it } from 'vitest'

import {
  CANONICAL_HAPPY_PATH,
  JOURNEY_TRANSITIONS,
  resolveJourneyStage,
} from './stateMachine'

describe('journey state machine', () => {
  it('defines canonical happy path ordering', () => {
    expect(CANONICAL_HAPPY_PATH).toEqual([
      'setup',
      'running',
      'review',
      'iterate',
    ])
    expect(JOURNEY_TRANSITIONS).toHaveLength(3)
  })

  it('resolves running with highest precedence', () => {
    const stage = resolveJourneyStage({
      isRunning: true,
      hasEverRun: true,
      finalResults: {
        bare: {
          output: 'ok',
          metrics: {
            input_tokens: 1,
            output_tokens: 1,
            cost_usd: 0.001,
            wall_time_ms: 1,
            num_api_calls: 1,
          },
          evaluation: {
            total_score: 90,
            breakdown: { schema: 90 },
            weights: { schema: { weight: 1, type: 'deterministic' } },
            notes: [],
          },
        },
      },
      comparisonCount: 1,
      autopsyOpen: true,
      hasExported: false,
    })
    expect(stage).toBe('running')
  })

  it('resolves iterate after review once analysis begins', () => {
    const stage = resolveJourneyStage({
      isRunning: false,
      hasEverRun: true,
      finalResults: {
        bare: {
          output: 'ok',
          metrics: {
            input_tokens: 1,
            output_tokens: 1,
            cost_usd: 0.001,
            wall_time_ms: 1,
            num_api_calls: 1,
          },
          evaluation: {
            total_score: 90,
            breakdown: { schema: 90 },
            weights: { schema: { weight: 1, type: 'deterministic' } },
            notes: [],
          },
        },
      },
      comparisonCount: 0,
      autopsyOpen: true,
      hasExported: false,
    })
    expect(stage).toBe('iterate')
  })
})
