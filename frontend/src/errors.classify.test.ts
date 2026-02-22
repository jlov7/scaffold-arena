import { describe, expect, it } from 'vitest'

import { classifyApiError, remediationForErrorKind } from './errors/classify'

describe('classifyApiError', () => {
  it('classifies auth errors', () => {
    expect(classifyApiError('401: Unauthorized').kind).toBe('auth')
  })

  it('classifies rate limits', () => {
    expect(classifyApiError('429: too many requests').kind).toBe('rate_limit')
  })

  it('classifies payload size errors', () => {
    expect(classifyApiError('413: too large').kind).toBe('validation')
  })

  it('classifies server errors', () => {
    expect(classifyApiError('500: boom').kind).toBe('server')
  })

  it('falls back to unknown', () => {
    expect(classifyApiError('strange').kind).toBe('unknown')
  })
})

describe('remediationForErrorKind', () => {
  it('returns actionable guidance', () => {
    expect(remediationForErrorKind('auth')).toMatch(/API token/i)
    expect(remediationForErrorKind('rate_limit')).toMatch(/wait/i)
  })
})
