import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ObservatorySurface } from './ObservatorySurface'

function client() {
  return {
    observatory: {
      create: vi.fn().mockResolvedValue({
        report_id: 'observatory-report', report_digest: `sha256:${'c'.repeat(64)}`, analysis_digest: `sha256:${'c'.repeat(64)}`, report_artifact_digest: `sha256:${'c'.repeat(64)}`,
        claim_ceiling: 'persisted evidence only', context_ledger: { metrics: [] }, memory_ledger: { metrics: [] },
        loop_microscope: [{ check: 'repeated_state_loops', status: 'unknown', reason: 'no state evidence' }],
        graph_microscope: { critical_path: { status: 'unknown', reason: 'no graph evidence' } },
        intervention_fidelity: [
          { stage: 'declared', status: 'observed', reason: 'declared event' },
          { stage: 'downstream_pathway_detected', status: 'unknown', reason: 'no downstream edge' },
        ],
        fidelity_ladder: ['declared', 'assigned', 'available', 'triggered', 'applied', 'activated', 'observed', 'downstream_pathway_detected'], fidelity_level: 'declared',
        metrics: [], attempt_ids: ['attempt-one'], xray_analysis_digest: null, limitations: ['no reconstruction'],
        provider_execution_started: false, execution_started: false, network_requested: false, idempotent_replay: false,
      }),
    },
  } as unknown as Parameters<typeof ObservatorySurface>[0]['client']
}

describe('ObservatorySurface', () => {
  it('uses exact persisted attempts, exposes unknown-aware ledgers, and does not estimate treatment effects', async () => {
    const arena = client()
    render(<ObservatorySurface client={arena} projectId="project-one" mode="lab" attemptIds={[]} xrayDigest={null} sourceDigest={null} />)

    fireEvent.change(screen.getByLabelText('Persisted attempt IDs'), { target: { value: 'attempt-one,attempt-one' } })
    fireEvent.click(screen.getByRole('button', { name: 'Inspect persisted evidence' }))

    await waitFor(() => expect(arena.observatory.create).toHaveBeenCalledWith({ attempt_ids: ['attempt-one'], diagnostic_partial_mode: false }, { projectId: 'project-one' }))
    expect(await screen.findByText('Context Ledger')).toBeInTheDocument()
    expect(screen.getAllByText('No applicable bounded evidence was reported.').length).toBeGreaterThan(0)
    expect(screen.getByText('downstream pathway detected')).toBeInTheDocument()
    expect(screen.getAllByText('Not estimated').length).toBe(5)
    expect(screen.getByText(/does not execute a graph, replay an attempt, or reconstruct missing evidence/i)).toBeInTheDocument()
  })

  it('does not show raw attempt IDs in guided mode', () => {
    const arena = client()
    render(<ObservatorySurface client={arena} mode="guided" attemptIds={['attempt-secret']} xrayDigest={null} sourceDigest={null} />)

    expect(screen.queryByLabelText('Persisted attempt IDs')).not.toBeInTheDocument()
    expect(screen.queryByText('attempt-secret')).not.toBeInTheDocument()
    expect(screen.getByText('1 persisted attempt selected from the durable route context.')).toBeInTheDocument()
  })
})
