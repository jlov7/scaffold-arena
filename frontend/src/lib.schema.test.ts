import { describe, expect, it } from 'vitest'

import {
  parseRunDetailsResponse,
  parseRunListResponse,
} from './lib/schema'

describe('schema parsing', () => {
  it('parses run list response', () => {
    const parsed = parseRunListResponse({
      runs: [
        {
          run_id: 'run_1',
          kind: 'arena',
          task_id: 'extraction',
          model_id: 'claude-sonnet-4-6',
          status: 'completed',
        },
      ],
    })

    expect(parsed.runs[0].run_id).toBe('run_1')
  })

  it('throws for malformed run details', () => {
    expect(() => parseRunDetailsResponse({ nope: true })).toThrow(
      /Invalid run details payload/i,
    )
  })
})
