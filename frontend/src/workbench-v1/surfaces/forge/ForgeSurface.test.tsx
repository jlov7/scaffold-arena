import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ForgeSurface } from './ForgeSurface'

const digest = (character: string) => `sha256:${character.repeat(64)}`

function client() {
  return {
    forge: {
      proposals: {
        create: vi.fn().mockResolvedValue({
          proposal_id: 'forge-fixture-proposal', proposal_digest: digest('a'), proposal_artifact_digest: digest('a'), state: 'PENDING_APPROVAL',
          proposal: { mechanism_change: { mechanism_id: 'context_compaction' }, requested_claim_scope: 'fixture_contract' },
          claim_ceiling: 'Product controls only.', execution_started: false, automatic_merge: false, idempotent_replay: false,
        }),
      },
    },
    experimentPlanner: {
      create: vi.fn().mockResolvedValue({
        schema_version: 'scaffold-arena.next-best-experiment-report/1', report_id: 'plan-one', report_digest: digest('b'), report_artifact_digest: digest('b'), request_digest: digest('c'), mode: 'exploratory', verdict: 'READY',
        recommendations: [{ rank: 1, proposed_design: { design_id: 'context-design' }, expected_information_gain: 0.42, attempts: 2, cost_interval: { lower_usd: 2, upper_usd: 5 }, risk: 0.2, assumptions: ['Fixed evaluator.'], claim_ceiling: 'Bounded planner only.', alternatives: [] }],
        excluded_designs: [{ design_id: 'retry-design', reason: 'Budget exhausted.' }], claim_ceiling: 'Bounded planner only.', execution_started: false, network_requested: false, idempotent_replay: false,
      }),
    },
    processSafety: {
      create: vi.fn().mockResolvedValue({
        schema_version: 'scaffold-arena.process-safety-report/1', report_id: 'safety-one', report_digest: digest('d'), report_artifact_digest: digest('d'), request_digest: digest('e'), verdict: 'PASS',
        checks: [{ check_id: 'network_egress', verdict: 'PASS', detail: 'No external destination is declared.' }], retained_manifest_digests: [digest('f')], claim_ceiling: 'Product controls only.', raw_sensitive_content_retained: false, execution_started: false, network_requested: false, idempotent_replay: false,
      }),
    },
  } as unknown as Parameters<typeof ForgeSurface>[0]['client']
}

describe('ForgeSurface', () => {
  it('stages an untrusted proposal without exposing execution or merge authority', async () => {
    const arena = client()
    render(<ForgeSurface client={arena} projectId="project-one" mode="lab" />)

    expect(screen.getByText(/cannot inspect sealed holdouts/i)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Stage untrusted fixture proposal' }))

    await waitFor(() => expect(arena.forge.proposals.create).toHaveBeenCalledWith(expect.objectContaining({ untrusted: true, automatic_merge_requested: false, execution_requested: false }), { projectId: 'project-one' }))
    expect(await screen.findByText('Untrusted proposal record')).toBeInTheDocument()
    expect(screen.getByText('PENDING APPROVAL')).toBeInTheDocument()
    expect(screen.getByText('None')).toBeInTheDocument()
  })

  it('renders ranked budget/risk designs and digest-only process-safety checks accessibly', async () => {
    const arena = client()
    render(<ForgeSurface client={arena} projectId="project-one" mode="guided" />)

    fireEvent.click(screen.getByRole('button', { name: 'Simulate next best experiment' }))
    await waitFor(() => expect(arena.experimentPlanner.create).toHaveBeenCalledWith(expect.objectContaining({ mode: 'exploratory', execution_requested: false }), { projectId: 'project-one' }))
    expect(await screen.findByRole('table', { name: 'Ranked constrained experiment designs' })).toBeInTheDocument()
    expect(screen.getByText(/retry-design/i)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Check process-safety controls' }))
    await waitFor(() => expect(arena.processSafety.create).toHaveBeenCalledWith(expect.objectContaining({ execution_started: false, network_requested: false }), { projectId: 'project-one' }))
    expect(await screen.findByRole('table', { name: 'Process-safety checks' })).toBeInTheDocument()
    expect(screen.getByText(/raw sensitive content is not retained/i)).toBeInTheDocument()
  })
})
