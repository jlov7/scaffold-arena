import { describe, expect, it } from 'vitest'

import {
  classifyApiError,
  extractApiErrorDetail,
  formatApiErrorMessage,
  remediationForErrorKind,
} from './errors/classify'

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

describe('formatApiErrorMessage', () => {
  it('removes raw backend auth JSON from user-facing messages', () => {
    const message = formatApiErrorMessage(
      '401: {"detail":"Missing or invalid Authorization header"}',
    )

    expect(message).toMatch(/API token required/i)
    expect(message).toMatch(/Settings/i)
    expect(message).not.toContain('{"detail"')
  })

  it('distinguishes provider-key failures from local session-token failures', () => {
    const message = formatApiErrorMessage(
      '401: {"error":{"message":"invalid x-api-key"}}',
    )

    expect(message).toMatch(/Provider key rejected/i)
  })

  it('extracts backend details from JSON payloads', () => {
    expect(extractApiErrorDetail('422: {"detail":"bad request"}')).toBe(
      'bad request',
    )
  })
})
