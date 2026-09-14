import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { DesignSurface } from '../../surfaces/design'
import { PreflightSurface } from '../../surfaces/preflight'
import { StudiesSurface } from '../../surfaces/studies'
import type { ArenaV1Client } from './types'

const template = {
  experiment_id: 'offline-p0-pvrm', study_pack_id: 'offline-demo-v1', scenario_ids: ['a', 'b', 'c', 'd', 'e'], harness_ids: ['recorded'], deterministic_weight: 1,
  factors: ['planning', 'verification', 'recovery', 'memory'].map((factor_id) => ({ factor_id, levels: [false, true], manipulation_checks: [{ oracle: `${factor_id}-check` }] })),
  repetitions: 1, model_endpoints: [], owner_approval: 'approved', frozen: false,
}

const pack = {
  protocol_version: '1.0', study_pack_id: 'offline-demo-v1', version: '1.0.0', title: 'Offline fixture', license_spdx: 'MIT', authors: [], compatibility: {}, allowed_claims: [], limitations: [], preregistration: {}, scenarios: [], harnesses: [], experiments: [template],
}

function client(overrides: Record<string, unknown> = {}): ArenaV1Client {
  return {
    studyPacks: { list: vi.fn().mockResolvedValue({ study_packs: [], authority_ceiling: 'local' }), validate: vi.fn().mockResolvedValue({ valid: true }), import: vi.fn().mockResolvedValue({ study_pack_id: 'offline-demo-v1', version: '1.0.0' }), get: vi.fn().mockResolvedValue({ canonical_study_pack: pack, study_pack: {}, custody: {} }) },
    experiments: { create: vi.fn().mockResolvedValue({ experiment_id: 'created-spec' }), get: vi.fn().mockResolvedValue({ experiment_id: 'created-spec', owner_approval: 'approved', immutable_identity: { frozen: false }, definition: template }), freeze: vi.fn().mockResolvedValue({ frozen: true }), preflight: vi.fn().mockResolvedValue({ verdict: 'PASS', blockers: [], study_pack_readiness: { task_family_deterministic_weights: {}, issues: [] }, design_expansion_count: 16, expected_attempts: 80, budget: {}, harnesses: [], manipulation_checks: { varied_factor_ids: [], declared_check_factor_ids: [], required_scenario_checks: [], missing_required_checks: [], missing_factor_ids: [], valid: true }, endpoint_pins: [], provider_execution_started: false, claim_ceiling: 'fixture only', authority_ceiling: 'local' }) },
    exports: { studyPack: vi.fn() },
    ...overrides,
  } as unknown as ArenaV1Client
}

describe('Study → Design → Preflight journey', () => {
  it('uses registry validate/import transport for JSON and ZIP files', async () => {
    const arena = client()
    render(<StudiesSurface client={arena} selection={null} onSelect={vi.fn()} />)
    await screen.findByText('No durable StudyPacks')
    const input = screen.getByLabelText('StudyPack file')
    fireEvent.change(input, { target: { files: [new File(['{}'], 'pack.json', { type: 'application/json' })] } })
    await waitFor(() => expect(arena.studyPacks.import).toHaveBeenCalledWith(expect.any(File), 'application/json', expect.any(Object)))
    fireEvent.change(input, { target: { files: [new File(['zip'], 'pack.zip', { type: 'application/zip' })] } })
    await waitFor(() => expect(arena.studyPacks.import).toHaveBeenLastCalledWith(expect.any(File), 'application/zip', expect.any(Object)))
  })

  it('keeps empty and offline registry states distinct', async () => {
    const empty = client()
    const { rerender } = render(<StudiesSurface client={empty} selection={null} onSelect={vi.fn()} />)
    expect(await screen.findByText('No durable StudyPacks')).toBeInTheDocument()
    const offline = client({ studyPacks: { ...empty.studyPacks, list: vi.fn().mockRejectedValue(new TypeError('network unavailable')) } })
    rerender(<StudiesSurface client={offline} selection={null} onSelect={vi.fn()} />)
    expect(await screen.findByText('Study registry unavailable')).toBeInTheDocument()
  })

  it('selects a durable StudyPack by its stable id and version', async () => {
    const select = vi.fn()
    const arena = client({ studyPacks: { ...client().studyPacks, list: vi.fn().mockResolvedValue({ study_packs: [{ id: 'registry-1', study_pack_id: 'offline-demo-v1', version: '1.0.0', title: 'Offline fixture', authority_ceiling: 'fixture only' }], authority_ceiling: 'fixture only' }) } })
    render(<StudiesSurface client={arena} selection={null} onSelect={select} />)
    fireEvent.click(await screen.findByText('Select'))
    expect(select).toHaveBeenCalledWith({ studyPackId: 'offline-demo-v1', version: '1.0.0' })
  })

  it('derives the template matrix and expected attempts without fixture results', async () => {
    const arena = client()
    render(<DesignSurface client={arena} packSelection={{ studyPackId: 'offline-demo-v1', version: '1.0.0' }} experimentId={null} mode="guided" onExperimentSelected={vi.fn()} />)
    expect(await screen.findByText(/16 treatment arms · 80 expected attempts/)).toBeInTheDocument()
    expect(screen.getByText('Treatment matrix (16 declared arms)')).toBeInTheDocument()
    expect(screen.getAllByText(/^Arm \d+$/)).toHaveLength(16)
    expect(screen.getAllByRole('region', { name: 'Scrollable data table' })).not.toHaveLength(0)
    expect(screen.getByText('Synthetic fixture — not benchmark evidence.')).toBeInTheDocument()
  })

  it('creates a clean successor for a frozen experiment and rejects malformed Lab JSON', async () => {
    const create = vi.fn().mockResolvedValue({ experiment_id: 'created-spec' })
    const frozenDefinition = { ...template, frozen: true, frozen_at: '2026-08-14T00:00:00Z', study_pack_hash: 'a'.repeat(64), freeze_hash: 'b'.repeat(64) }
    const arena = client({ experiments: { ...client().experiments, create, get: vi.fn().mockResolvedValue({ experiment_id: 'frozen-spec', owner_approval: 'approved', immutable_identity: { frozen: true, freeze_hash: 'b'.repeat(64), study_pack_hash: 'a'.repeat(64), frozen_at: '2026-08-14T00:00:00Z' }, definition: frozenDefinition }) } })
    const { rerender } = render(<DesignSurface client={arena} packSelection={{ studyPackId: 'offline-demo-v1', version: '1.0.0' }} experimentId="frozen-spec" mode="guided" onExperimentSelected={vi.fn()} />)
    fireEvent.click(await screen.findByText('Create version draft'))
    fireEvent.click(screen.getByLabelText(/explicit owner approval/i))
    fireEvent.click(screen.getByText('Create unfrozen experiment'))
    await waitFor(() => expect(create).toHaveBeenCalled())
    expect(create).toHaveBeenCalledWith(expect.objectContaining({ predecessor_experiment_id: 'frozen-spec', frozen: false, frozen_at: null, freeze_hash: null, study_pack_hash: null }), expect.any(Object))
    rerender(<DesignSurface client={arena} packSelection={{ studyPackId: 'offline-demo-v1', version: '1.0.0' }} experimentId={null} mode="lab" onExperimentSelected={vi.fn()} />)
    fireEvent.change(await screen.findByLabelText('Canonical ExperimentSpec JSON'), { target: { value: '{broken' } })
    fireEvent.click(screen.getByText('Create unfrozen experiment'))
    expect(await screen.findByText(/Malformed JSON/)).toBeInTheDocument()
  })

  it('freezes an approved experiment and calls the real preflight endpoint', async () => {
    const freeze = vi.fn().mockResolvedValue({ frozen: true })
    const preflight = vi.fn().mockResolvedValue({ verdict: 'PASS', blockers: [], study_pack_readiness: { task_family_deterministic_weights: {}, issues: [] }, design_expansion_count: 16, expected_attempts: 80, budget: {}, harnesses: [], manipulation_checks: { varied_factor_ids: [], declared_check_factor_ids: [], required_scenario_checks: [], missing_required_checks: [], missing_factor_ids: [], valid: true }, endpoint_pins: [], provider_execution_started: false, claim_ceiling: 'fixture only', authority_ceiling: 'local' })
    const get = vi.fn()
      .mockResolvedValueOnce({ experiment_id: 'created-spec', owner_approval: 'approved', immutable_identity: { frozen: false }, definition: template })
      .mockResolvedValue({ experiment_id: 'created-spec', owner_approval: 'approved', immutable_identity: { frozen: true }, definition: template })
    const arena = client({ experiments: { ...client().experiments, get, freeze, preflight } })
    render(<PreflightSurface client={arena} experimentId="created-spec" isFixture />)
    fireEvent.click(await screen.findByText('Freeze experiment'))
    await waitFor(() => expect(freeze).toHaveBeenCalledWith('created-spec', expect.any(Object)))
    fireEvent.click(await screen.findByText('Preflight experiment'))
    await waitFor(() => expect(preflight).toHaveBeenCalledWith('created-spec', expect.any(Object)))
    expect(await screen.findByText('Synthetic fixture — not benchmark evidence.')).toBeInTheDocument()
  })

  it('does not offer execution after a HOLD preflight', async () => {
    const hold = { verdict: 'HOLD', blockers: [{ code: 'missing_control', scope: 'design', message: 'control required' }], study_pack_readiness: { task_family_deterministic_weights: {}, issues: [] }, design_expansion_count: 16, expected_attempts: 80, budget: {}, harnesses: [], manipulation_checks: { varied_factor_ids: [], declared_check_factor_ids: [], required_scenario_checks: [], missing_required_checks: [], missing_factor_ids: [], valid: false }, endpoint_pins: [], provider_execution_started: false, claim_ceiling: 'fixture only', authority_ceiling: 'local' }
    const arena = client({ experiments: { ...client().experiments, get: vi.fn().mockResolvedValue({ experiment_id: 'created-spec', owner_approval: 'approved', immutable_identity: { frozen: true }, definition: template }), preflight: vi.fn().mockResolvedValue(hold) } })
    render(<PreflightSurface client={arena} experimentId="created-spec" onProceedToExecute={vi.fn()} />)
    expect(await screen.findByText('Preflight experiment')).toBeInTheDocument()
    fireEvent.click(screen.getByText('Preflight experiment'))
    expect(await screen.findByText('Execution remains unavailable')).toBeInTheDocument()
    expect(screen.queryByText('Continue to Run Cockpit')).not.toBeInTheDocument()
  })
})
