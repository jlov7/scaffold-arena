import { describe, expect, it } from 'vitest'

import { COPY } from './content/copy'

describe('COPY contract', () => {
  it('defines core sections for app chrome and actions', () => {
    expect(COPY.app.title).toBeTruthy()
    expect(COPY.actions.runArena).toBeTruthy()
    expect(COPY.actions.exportJson).toBeTruthy()
    expect(COPY.errors.offlineRunBlocked).toBeTruthy()
  })

  it('uses stable key-based structure', () => {
    expect(Object.keys(COPY.app).length).toBeGreaterThan(2)
    expect(Object.keys(COPY.actions)).toContain('share')
  })
})
