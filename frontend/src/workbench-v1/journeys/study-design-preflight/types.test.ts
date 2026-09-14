import { describe, expect, it } from 'vitest'
import { designExpansion, expectedAttempts } from './types'

describe('study-design-preflight derivation', () => {
  it('derives the offline P/V/R/M template as 16 arms and 80 attempts', () => {
    const specification = {
      design: 'full',
      factors: [
        { levels: [false, true] },
        { levels: [false, true] },
        { levels: [false, true] },
        { levels: [false, true] },
      ],
      scenario_ids: ['candidate-clean', 'candidate-stress', 'positive-control', 'negative-control', 'anti-cheat-control'],
      harness_ids: ['offline-recorded'],
      model_endpoints: [],
      repetitions: 1,
    }

    expect(designExpansion(specification)).toBe(16)
    expect(expectedAttempts(specification)).toBe(80)
  })
})
