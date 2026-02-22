import { describe, expect, it } from 'vitest'

import {
  getTaskPlaybook,
  resolveHelpBlocker,
  type HelpBlocker,
} from './playbook'

describe('resolveHelpBlocker', () => {
  it('prioritizes offline over all other states', () => {
    expect(
      resolveHelpBlocker({
        isOnline: false,
        connectionState: 'failed',
        hasApiToken: false,
        errorMessage: 'HTTP 401 unauthorized',
      }),
    ).toBe('offline')
  })

  it('returns auth when token missing even if no explicit error', () => {
    expect(
      resolveHelpBlocker({
        isOnline: true,
        connectionState: 'connected',
        hasApiToken: false,
        errorMessage: null,
      }),
    ).toBe('auth')
  })

  it('classifies explicit error messages', () => {
    expect(
      resolveHelpBlocker({
        isOnline: true,
        connectionState: 'connected',
        hasApiToken: true,
        errorMessage: 'HTTP 429 rate limit exceeded',
      }),
    ).toBe('rate_limit')
  })
})

describe('getTaskPlaybook', () => {
  function pickStepTexts(taskId: string, blocker: HelpBlocker): string[] {
    return getTaskPlaybook(taskId, blocker).steps.map((step) => step.text)
  }

  it('returns extraction-specific schema guidance', () => {
    const steps = pickStepTexts('extraction', 'validation')
    expect(steps.join(' ')).toMatch(/schema/i)
    expect(steps.join(' ')).toMatch(/required field/i)
  })

  it('returns risk-specific severity guidance', () => {
    const steps = pickStepTexts('risk', 'none')
    expect(steps.join(' ')).toMatch(/severity/i)
    expect(steps.join(' ')).toMatch(/false positives?/i)
  })

  it('returns research-specific citation guidance', () => {
    const steps = pickStepTexts('research', 'none')
    expect(steps.join(' ')).toMatch(/citation/i)
    expect(steps.join(' ')).toMatch(/findings/i)
  })

  it('returns blocker-specific primary action', () => {
    expect(getTaskPlaybook('extraction', 'auth').primaryAction).toBe('open_settings')
    expect(getTaskPlaybook('extraction', 'failed').primaryAction).toBe('retry')
    expect(getTaskPlaybook('extraction', 'none').primaryAction).toBe('open_tour')
  })
})
