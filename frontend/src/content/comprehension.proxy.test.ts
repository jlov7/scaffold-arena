import { describe, expect, it } from 'vitest'

import { COPY } from './copy'

interface ComprehensionCheck {
  id: string
  text: string
  mustContain: string[]
}

function normalize(text: string): string {
  return text.toLowerCase()
}

function passesCheck(check: ComprehensionCheck): boolean {
  const normalized = normalize(check.text)
  return check.mustContain.every((needle) => normalized.includes(needle))
}

const checks: ComprehensionCheck[] = [
  { id: 'subtitle-value', text: COPY.app.subtitle, mustContain: ['same model', 'different scaffolding'] },
  { id: 'action-run', text: COPY.actions.runArena, mustContain: ['run'] },
  { id: 'action-cancel', text: COPY.actions.cancelRun, mustContain: ['cancel'] },
  { id: 'action-export-report', text: COPY.actions.exportReport, mustContain: ['export'] },
  { id: 'action-share', text: COPY.actions.share, mustContain: ['share'] },
  { id: 'error-offline-reason', text: COPY.errors.offlineRunBlocked, mustContain: ['offline', 'cannot start run'] },
  { id: 'error-offline-recovery', text: COPY.errors.offlineRunBlocked, mustContain: ['reconnect', 'retry'] },
  { id: 'error-offline-fallback', text: COPY.errors.offlineRunBlocked, mustContain: ['safe fallback mode'] },
  { id: 'error-connection-reason', text: COPY.errors.connectionFailed, mustContain: ['connection failed'] },
  { id: 'error-connection-recovery', text: COPY.errors.connectionFailed, mustContain: ['retry stream', 'help center'] },
  { id: 'helper-task-why', text: COPY.helpers.chooseTask, mustContain: ['choose a task', 'benchmark'] },
  { id: 'helper-task-outcome', text: COPY.helpers.chooseTask, mustContain: ['quality'] },
  { id: 'helper-model-why', text: COPY.helpers.chooseModel, mustContain: ['choose one model', 'fairly'] },
  { id: 'helper-model-outcome', text: COPY.helpers.chooseModel, mustContain: ['consistently'] },
  { id: 'helper-run-flow', text: COPY.helpers.runFlow, mustContain: ['run the arena', 'same input'] },
  { id: 'empty-results-step1', text: COPY.emptyStates.results, mustContain: ['run the arena first'] },
  { id: 'empty-results-step2', text: COPY.emptyStates.results, mustContain: ['load a historical run'] },
  { id: 'empty-results-step3', text: COPY.emptyStates.results, mustContain: ['review winner quality', 'compare outputs'] },
  { id: 'empty-results-step4', text: COPY.emptyStates.results, mustContain: ['export evidence'] },
  { id: 'empty-results-help', text: COPY.emptyStates.results, mustContain: ['help center'] },
]

describe('onboarding copy comprehension proxy', () => {
  for (const check of checks) {
    it(`comprehension check passes: ${check.id}`, () => {
      expect(passesCheck(check)).toBe(true)
    })
  }

  it('proxy matrix reaches minimum sample size of 20 checks', () => {
    expect(checks.length).toBeGreaterThanOrEqual(20)
  })
})
