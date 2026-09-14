import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { session, listStudyPacks, getExperiment, freezeExperiment, fetchRuntimeMetadata } = vi.hoisted(() => ({
  session: vi.fn(),
  listStudyPacks: vi.fn(),
  getExperiment: vi.fn(),
  freezeExperiment: vi.fn(),
  fetchRuntimeMetadata: vi.fn(),
}))

vi.mock('../api/v1/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/v1/client')>()
  return { ...actual, arenaV1: { auth: { session }, studyPacks: { list: listStudyPacks }, experiments: { get: getExperiment, freeze: freezeExperiment } } }
})

vi.mock('../api/v1/runtimeMetadata', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api/v1/runtimeMetadata')>()
  return { ...actual, fetchRuntimeMetadata }
})

import { WorkbenchV1App } from './WorkbenchV1App'

describe('WorkbenchV1App team project selection', () => {
  beforeEach(() => {
    window.history.replaceState({}, '', '/workbench/studies')
    session.mockResolvedValue({
      authenticated: true,
      mode: 'team',
      memberships: [
        { project_id: 'alpha', role: 'viewer' },
        { project_id: 'beta', role: 'operator' },
      ],
    })
    fetchRuntimeMetadata.mockResolvedValue({
      schema_version: 'build-meta.v1',
      app_version: '0.9.1',
      protocol_version: '1.0',
      git_sha: __GIT_SHA__,
      build_environment: 'test',
      build_time: 'unknown',
    })
    listStudyPacks.mockResolvedValue({ study_packs: [] })
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('blocks project-scoped surfaces until a membership is selected and restores chooser state on back navigation', async () => {
    render(<WorkbenchV1App />)

    expect(await screen.findByRole('heading', { name: 'Choose a project' })).toBeInTheDocument()
    expect(screen.getByText(/Authorized project 1/)).toBeInTheDocument()
    expect(screen.queryByText('alpha')).not.toBeInTheDocument()
    expect(screen.queryByText('Loading durable StudyPacks')).not.toBeInTheDocument()
    expect(listStudyPacks).not.toHaveBeenCalled()

    fireEvent.click(screen.getAllByRole('button', { name: 'Use project' })[0]!)
    await waitFor(() => expect(window.location.search).toBe('?project_id=alpha'))

    const restored = new Promise<void>((resolve) => {
      window.addEventListener('popstate', () => resolve(), { once: true })
    })
    await act(async () => {
      window.history.back()
      await restored
    })

    expect(await screen.findByRole('heading', { name: 'Choose a project' })).toBeInTheDocument()
    expect(window.location.search).toBe('')
  }, 10_000)

  it('surfaces a mixed frontend/backend revision before a user interprets one deployment', async () => {
    session.mockResolvedValue({ authenticated: true, mode: 'personal' })
    fetchRuntimeMetadata.mockResolvedValue({
      schema_version: 'build-meta.v1',
      app_version: '0.9.1',
      protocol_version: '1.0',
      git_sha: __GIT_SHA__ === 'dev' ? 'b'.repeat(40) : (__GIT_SHA__[0] === 'a' ? 'b' : 'a').repeat(40),
      build_environment: 'production',
      build_time: '2026-08-20T12:00:00.000Z',
    })

    render(<WorkbenchV1App />)

    expect((await screen.findAllByText('Revision mismatch')).length).toBeGreaterThan(0)
    expect(screen.getByText(/mixed deployment/i)).toBeInTheDocument()
  })

  it('labels a selected experiment as unfrozen until its persisted frozen_at is recovered', async () => {
    window.history.replaceState({}, '', '/workbench/preflight?study_pack_id=research-pack-v1&study_pack_version=1.0.0&experiment_id=offline-p0-pvrm-v2')
    session.mockResolvedValue({ authenticated: true, mode: 'personal' })
    getExperiment.mockResolvedValue({
      experiment_id: 'offline-p0-pvrm-v2',
      owner_approval: 'approved',
      immutable_identity: { frozen: false, frozen_at: null },
      definition: {},
    })

    render(<WorkbenchV1App />)

    expect(await screen.findByText('Comparison selected')).toBeInTheDocument()
    expect(screen.queryByText('offline-p0-pvrm-v2')).not.toBeInTheDocument()
    expect(screen.getByText('Experiment', { selector: '.sa-command-label' })).toBeInTheDocument()
    expect(screen.queryByText('Frozen spec', { selector: '.sa-command-label' })).not.toBeInTheDocument()
    expect(screen.queryByText('Synthetic fixture — not benchmark evidence.')).not.toBeInTheDocument()
  })

  it('retains the synthetic fixture boundary on Preflight when the selected pack is carried from Design', async () => {
    window.history.replaceState({}, '', '/workbench/preflight?study_pack_id=offline-demo-v1&study_pack_version=1.0.0&experiment_id=offline-p0-pvrm-v2')
    session.mockResolvedValue({ authenticated: true, mode: 'personal' })
    getExperiment.mockResolvedValue({
      experiment_id: 'offline-p0-pvrm-v2', owner_approval: 'approved',
      immutable_identity: { frozen: false, frozen_at: null }, definition: {},
    })

    render(<WorkbenchV1App />)

    expect(await screen.findByText('Synthetic fixture — not benchmark evidence.')).toBeInTheDocument()
  })

  it('promotes the shell label only after freeze reload returns frozen_at', async () => {
    window.history.replaceState({}, '', '/workbench/preflight?experiment_id=offline-p0-pvrm-v2')
    session.mockResolvedValue({ authenticated: true, mode: 'personal' })
    getExperiment
      .mockResolvedValueOnce({ experiment_id: 'offline-p0-pvrm-v2', owner_approval: 'approved', immutable_identity: { frozen: false, frozen_at: null }, definition: {} })
      .mockResolvedValueOnce({ experiment_id: 'offline-p0-pvrm-v2', owner_approval: 'approved', immutable_identity: { frozen: false, frozen_at: null }, definition: {} })
      .mockResolvedValue({ experiment_id: 'offline-p0-pvrm-v2', owner_approval: 'approved', immutable_identity: { frozen: true, frozen_at: '2026-08-14T00:00:00Z' }, definition: {} })
    freezeExperiment.mockResolvedValue({ frozen: true })

    render(<WorkbenchV1App />)
    const freezeButton = await screen.findByRole(
      'button',
      { name: 'Freeze experiment' },
      { timeout: 5_000 },
    )
    fireEvent.click(freezeButton)

    expect(
      await screen.findByText(
        'Frozen comparison selected',
        {},
        { timeout: 5_000 },
      ),
    ).toBeInTheDocument()
    expect(screen.queryByText('offline-p0-pvrm-v2')).not.toBeInTheDocument()
    expect(
      await screen.findByText(
        'Frozen spec',
        { selector: '.sa-command-label' },
        { timeout: 5_000 },
      ),
    ).toBeInTheDocument()
  })

  it('returns a deep-linked Execute recovery state to Preflight without posting automatically', async () => {
    window.history.replaceState({}, '', '/workbench/execute?experiment_id=offline-p0-pvrm-v2')
    session.mockResolvedValue({ authenticated: true, mode: 'personal' })
    getExperiment.mockResolvedValue({
      experiment_id: 'offline-p0-pvrm-v2', owner_approval: 'approved',
      immutable_identity: { frozen: true, frozen_at: '2026-08-14T00:00:00Z' }, definition: {},
    })

    render(<WorkbenchV1App />)

    fireEvent.click(await screen.findByRole('button', { name: 'Run or recover preflight' }))
    await waitFor(() => expect(window.location.pathname).toBe('/workbench/preflight'))
  })

  it('switches Guided Execute to Lab from the provenance-capture handoff without constructing browser provenance', async () => {
    window.history.replaceState({}, '', '/workbench/execute?experiment_id=offline-p0-pvrm-v2')
    session.mockResolvedValue({ authenticated: true, mode: 'personal' })
    getExperiment.mockResolvedValue({
      experiment_id: 'offline-p0-pvrm-v2', owner_approval: 'approved',
      immutable_identity: { frozen: true, frozen_at: '2026-08-14T00:00:00Z' }, definition: {},
    })

    render(<WorkbenchV1App />)

    expect(
      await screen.findByText('Execution remains HOLD until capture is configured'),
    ).toBeInTheDocument()
    expect(screen.queryByText('uv run arena provenance capture')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Canonical ExecutionProvenance JSON')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Switch to Lab' }))
    expect(await screen.findByLabelText('Canonical ExecutionProvenance JSON')).toBeInTheDocument()
  })

  it('lazy-loads the provider-free Counterfactual Replay workbench surface from its stable route', async () => {
    window.history.replaceState({}, '', '/workbench/counterfactual')
    session.mockResolvedValue({ authenticated: true, mode: 'personal' })

    render(<WorkbenchV1App />)

    expect(await screen.findByText('$0.00 consumed')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Run Harness CI check' })).toBeDisabled()
  })

  it('lazy-loads Arena Forge from its stable route without presenting execution authority', async () => {
    window.history.replaceState({}, '', '/workbench/forge')
    session.mockResolvedValue({ authenticated: true, mode: 'personal' })

    render(<WorkbenchV1App />)

    expect(await screen.findByRole('button', { name: 'Stage untrusted fixture proposal' })).toBeInTheDocument()
    expect(screen.getAllByRole('heading', { name: 'Arena Forge' }).length).toBeGreaterThan(0)
    expect(screen.getByText(/cannot inspect sealed holdouts/i)).toBeInTheDocument()
  })
})
