import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { CounterfactualSurface } from './CounterfactualSurface'

function client() {
  return {
    counterfactual: {
      create: vi.fn().mockResolvedValue({
        schema_version: 'scaffold-arena.counterfactual-replay-report/1', report_id: 'replay-one', report_digest: `sha256:${'a'.repeat(64)}`, report_artifact_digest: `sha256:${'a'.repeat(64)}`, request_digest: `sha256:${'b'.repeat(64)}`, binding_digest: `sha256:${'c'.repeat(64)}`,
        mode: 'fixture', verdict: 'HOLD', evidence_maturity: 'paired_replay', maturity_ladder: [
          { maturity: 'temporal_correlation', state: 'observed', reason: 'ordered outcome only' },
          { maturity: 'diagnostic_divergence', state: 'observed', reason: 'diagnostic only' },
          { maturity: 'paired_replay', state: 'observed', reason: 'same binding' },
          { maturity: 'replicated_intervention', state: 'unknown', reason: 'more repeats needed' },
          { maturity: 'confirmatory_eligibility', state: 'ineligible', reason: 'no holdout result' },
        ],
        pair_count: 2, planned_repetitions: 2, effects: [
          { metric: 'quality', state: 'observed', point_estimate: 0.1, ci95_low: 0.01, ci95_high: 0.2, base_mean: 0.5, candidate_mean: 0.6, paired_samples: 2, reason: 'recorded only' },
          { metric: 'cost_usd', state: 'unknown', point_estimate: null, ci95_low: null, ci95_high: null, base_mean: null, candidate_mean: null, paired_samples: 0, reason: 'unknown' },
        ], conditional_measures: [
          { measure: 'intention_to_treat', state: 'ineligible', value: null, reason: 'not randomized' }, { measure: 'opportunity', state: 'ineligible', value: null, reason: 'no denominator' }, { measure: 'activation', state: 'ineligible', value: null, reason: 'not observed' }, { measure: 'fidelity_failure', state: 'ineligible', value: null, reason: 'not estimated' }, { measure: 'treatment_on_the_treated', state: 'ineligible', value: null, reason: 'no uptake binding' },
        ],
        new_severe_failures: [], usage_state: 'unknown', fidelity_level: 'applied', process_safety: 'pass', claim_ceiling: 'Fixture only; not causal proof.', limitations: ['unknown remains unknown'], provider_execution_started: false, execution_started: false, network_requested: false, idempotent_replay: false,
      }),
    },
    harnessCi: {
      create: vi.fn().mockResolvedValue({
        schema_version: 'scaffold-arena.harness-ci-report/1', report_id: 'hci-one', report_digest: `sha256:${'d'.repeat(64)}`, report_artifact_digest: `sha256:${'d'.repeat(64)}`, replay_report_digest: `sha256:${'a'.repeat(64)}`, verdict: 'HOLD',
        checks: [{ check_id: 'usage', verdict: 'HOLD', detail: 'Usage is unknown, not zero.' }], effects: [], severe_failures: [], usage_state: 'unknown', fidelity_level: 'applied', evidence_maturity: 'paired_replay', semantic_diff: { affected_mechanisms: ['context_compaction'], recommended_packs: ['context-survival-v1'], classification_state: 'observed' }, reproduction_command: 'arena harness-ci', step_summary: '## Harness CI — HOLD', pr_comment_body: '## Harness CI — HOLD', claim_ceiling: 'Policy result only; not causal proof.', provider_execution_started: false, execution_started: false, network_requested: false, idempotent_replay: false,
      }),
    },
  } as unknown as Parameters<typeof CounterfactualSurface>[0]['client']
}

describe('CounterfactualSurface', () => {
  it('runs a provider-free fixture then retains a Harness CI HOLD without treating usage as zero', async () => {
    const arena = client()
    render(<CounterfactualSurface client={arena} projectId="project-one" mode="guided" />)

    expect(screen.getByText('$0.00 consumed')).toBeInTheDocument()
    expect(screen.getByText(/requires explicit credentials attestation/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Run Harness CI check' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Run provider-free fixture replay' }))

    await waitFor(() => expect(arena.counterfactual.create).toHaveBeenCalled())
    expect(arena.counterfactual.create).toHaveBeenCalledWith(expect.objectContaining({ mode: 'fixture' }), { projectId: 'project-one' })
    expect((arena.counterfactual.create as ReturnType<typeof vi.fn>).mock.calls[0]?.[0]).not.toHaveProperty('live_authorization')
    expect(await screen.findByText('Effect and uncertainty')).toBeInTheDocument()
    expect(screen.getByText('Unknown usage/cost remains unknown. The interval describes recorded paired differences only; it does not identify a cause.')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Run Harness CI check' }))
    await waitFor(() => expect(arena.harnessCi.create).toHaveBeenCalledWith(expect.objectContaining({ replay_report_digest: `sha256:${'a'.repeat(64)}` }), { projectId: 'project-one' }))
    expect(await screen.findByText('Policy checks')).toBeInTheDocument()
    expect(screen.getByRole('table', { name: 'Harness CI policy checks' })).toBeInTheDocument()
  })
})
