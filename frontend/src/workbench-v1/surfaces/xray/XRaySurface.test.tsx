import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { XRaySurface } from './XRaySurface'

const digest = 'a'.repeat(64)

function client() {
  return {
    xray: {
      create: vi.fn().mockResolvedValue({
        report_id: 'xray-report', report_digest: `sha256:${'b'.repeat(64)}`, analysis_digest: `sha256:${'b'.repeat(64)}`, report_artifact_digest: `sha256:${'b'.repeat(64)}`,
        claim_ceiling: 'captured input only', evidence_ceiling: 'captured input only',
        candidate_genome: { source_kind: 'repository', component_count: 1 },
        mechanism_graph: { nodes: [{ node_id: 'memory-read-write', status: 'inferred' }] },
        detected_mechanisms: [{ mechanism_id: 'memory-read-write', status: 'inferred', evidence_refs: ['artifact:sha256:source'] }],
        mechanisms: [{ mechanism_id: 'memory-read-write', status: 'inferred', evidence_refs: ['artifact:sha256:source'] }],
        unobservable_controls: ['provider calls'], confounds: ['capture incomplete'], security_paths: ['unknown static boundary'],
        first_study: { design: 'preregister a paired study' }, expected_attempts: null,
        expected_cost_interval: { minimum_usd: null, maximum_usd: null, reason: 'no price evidence' }, limitations: ['no execution'],
        provider_execution_started: false, execution_started: false, network_requested: false, idempotent_replay: false,
      }),
    },
  } as unknown as Parameters<typeof XRaySurface>[0]['client']
}

describe('XRaySurface', () => {
  it('uses only a named captured artifact and keeps inferred evidence distinct from verification', async () => {
    const arena = client()
    render(<XRaySurface client={arena} projectId="project-one" mode="lab" sourceDigest={null} />)

    fireEvent.change(screen.getByLabelText('Captured artifact digest'), { target: { value: digest } })
    fireEvent.change(screen.getByLabelText('Captured source type'), { target: { value: 'sdk' } })
    fireEvent.click(screen.getByRole('button', { name: 'Inspect captured source' }))

    await waitFor(() => expect(arena.xray.create).toHaveBeenCalledWith({ source_artifact_digest: digest, source_kind: 'sdk' }, { projectId: 'project-one' }))
    expect(await screen.findByText('Candidate, not verified')).toBeInTheDocument()
    expect(screen.getByText('memory-read-write')).toBeInTheDocument()
    expect(screen.getByText('inferred')).toBeInTheDocument()
    expect(screen.getByText(/Unknown — no price evidence/)).toBeInTheDocument()
    expect(screen.getByText(/never executes source, starts a provider, or contacts a network endpoint/i)).toBeInTheDocument()
  })

  it('keeps raw identities and source-kind overrides out of guided route context', async () => {
    const arena = client()
    render(<XRaySurface client={arena} mode="guided" sourceDigest={digest} />)

    expect(screen.queryByLabelText('Captured artifact digest')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Captured source type')).not.toBeInTheDocument()
    expect(screen.getByText('Auto-detect from the durable capture')).toBeInTheDocument()
    expect(screen.getByText('A captured source is selected from the durable route context.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Inspect captured source' }))
    await waitFor(() => expect(arena.xray.create).toHaveBeenCalledWith(
      { source_artifact_digest: digest, source_kind: 'auto' },
      { projectId: undefined },
    ))
    expect(screen.queryByText(digest)).not.toBeInTheDocument()
  })

  it('discovers and selects durable captured sources in guided mode', async () => {
    const arena = client()
    const snapshotLoader = vi.fn().mockResolvedValue({
      snapshots: [{
        snapshot_id: 'capture-one',
        source_name: 'Captured repository',
        source_uri: 'capture://repository',
        source_revision: 'abc123',
        captured_at: '2026-08-20T12:00:00Z',
        source_digest: `sha256:${digest}`,
        claim_ceiling: 'captured input only',
        idempotent_replay: false,
        execution_started: false,
        network_requested: false,
      }],
      claim_ceiling: 'captured input only',
    })

    render(
      <XRaySurface
        client={arena}
        projectId="project-one"
        mode="guided"
        sourceDigest={null}
        snapshotLoader={snapshotLoader}
      />,
    )

    const source = await screen.findByLabelText('Captured source')
    expect(source).toHaveValue('capture-one')
    expect(screen.queryByLabelText('Captured source type')).not.toBeInTheDocument()
    expect(snapshotLoader).toHaveBeenCalledWith(expect.objectContaining({ projectId: 'project-one' }))
    expect(screen.queryByText(`sha256:${digest}`)).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Inspect captured source' }))
    await waitFor(() => expect(arena.xray.create).toHaveBeenCalledWith(
      { source_artifact_digest: `sha256:${digest}`, source_kind: 'auto' },
      { projectId: 'project-one' },
    ))
  })
})
