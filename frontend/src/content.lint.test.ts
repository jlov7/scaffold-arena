import { describe, expect, test } from 'vitest'

import { COPY } from './content/copy'

const CTA_VERB_PATTERN =
  /^(Run|Export|Share|Take|Retry|Cancel|Open|Review|Enable|Disable)\b/i
const BANNED_JARGON = [
  /\bsynergy\b/i,
  /\bleverage\b/i,
  /\bjust\b/i,
  /\bobviously\b/i,
  /\bsimply\b/i,
]

describe('content lint', () => {
  test('primary action labels start with action verbs', () => {
    const labels = Object.values(COPY.actions)
    for (const label of labels) {
      expect(label).toMatch(CTA_VERB_PATTERN)
    }
  })

  test('error messages include clear remediation language', () => {
    expect(COPY.errors.offlineRunBlocked.toLowerCase()).toMatch(
      /(reconnect|retry)/,
    )
    expect(COPY.errors.connectionFailed.toLowerCase()).toMatch(
      /(retry|help|open)/,
    )
    expect(COPY.errors.offlineRunBlocked.toLowerCase()).toMatch(
      /(fallback|safe fallback)/,
    )
    expect(COPY.errors.connectionFailed.toLowerCase()).toMatch(
      /(fallback|safe fallback)/,
    )
  })

  test('helper text follows why + input + expected outcome structure', () => {
    const helpers = Object.values(COPY.helpers)
    for (const helper of helpers) {
      expect(helper).toMatch(/\bso\b/i)
      expect(helper.endsWith('.')).toBe(true)
    }
  })

  test('results empty state includes next action and learn link language', () => {
    const empty = COPY.emptyStates.results.toLowerCase()
    expect(empty).toMatch(/run|load/)
    expect(empty).toMatch(/help center|learn/)
  })

  test('copy avoids banned filler and jargon terms', () => {
    const corpus = [
      ...Object.values(COPY.actions),
      ...Object.values(COPY.labels),
      ...Object.values(COPY.errors),
      COPY.app.subtitle,
    ].join(' ')

    for (const banned of BANNED_JARGON) {
      expect(corpus).not.toMatch(banned)
    }
  })
})
