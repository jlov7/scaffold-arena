import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ExecutionDetail, ExecutionEvent, PreflightReport } from '../../../api/v1/client'
import { type ArenaV1Client } from '../../journeys/study-design-preflight/types'
import { ExecuteSurface } from './ExecuteSurface'

const digest = 'a'.repeat(64)
const pass: PreflightReport = {
  verdict: 'PASS', blockers: [], study_pack_readiness: { verdict: 'PASS', task_family_deterministic_weights: {}, issues: [] },
  design_expansion_count: 1, expected_attempts: 1, budget: {}, harnesses: [],
  manipulation_checks: { varied_factor_ids: [], declared_check_factor_ids: [], required_scenario_checks: [], missing_required_checks: [], missing_factor_ids: [], valid: true },
  endpoint_pins: [], provider_execution_started: false, claim_ceiling: 'local', authority_ceiling: 'local',
}

const execution: ExecutionDetail = {
  execution_id: 'exec-1', experiment_id: 'frozen-1', status: 'queued', started_at: null, completed_at: null, created_at: '2026-08-14T12:00:00Z',
  attempts: [{ attempt_id: 'attempt-1', episode_id: 'episode-1', episode_ordinal: 1, scenario_id: 'scenario-1', ordinal: 1, status: 'queued', created_at: '2026-08-14T12:00:00Z' }],
  jobs: [{ job_id: 'job-1', attempt_id: 'attempt-1', kind: 'attempt', status: 'queued', attempt_count: 0, available_at: null, cancel_requested_at: null, created_at: '2026-08-14T12:00:00Z' }],
  counts: { attempts: 1, jobs: 1 }, claim_ceiling: 'durable status only',
}

function asyncEvents(items: ExecutionEvent[] = []) {
  return async function* () { for (const item of items) yield item }
}

function client(overrides: Record<string, unknown> = {}): ArenaV1Client {
  return {
    executions: {
      list: vi.fn().mockResolvedValue({ executions: [execution], pagination: { limit: 50, offset: 0, next_offset: null }, claim_ceiling: 'status only' }),
      get: vi.fn().mockResolvedValue(execution),
      events: vi.fn(asyncEvents()),
      create: vi.fn().mockResolvedValue({ execution_id: 'exec-1', expected_attempts: 1, job_ids: ['job-1'], idempotent_replay: false, provider_execution_started_by_request: false, claim_ceiling: 'durable dispatch' }),
      cancel: vi.fn().mockResolvedValue({ execution_id: 'exec-1', status: 'cancelled' }),
      resume: vi.fn().mockRejectedValue(Object.assign(new Error('No durable resume service is configured.'), { status: 409, verdict: 'HOLD' })),
      ...overrides,
    },
    attempts: { get: vi.fn().mockResolvedValue({ attempt_id: 'attempt-1', execution_id: 'exec-1', status: 'queued', execution_status: 'queued', ordinal: 1, request: {}, result: {} }), trace: vi.fn().mockResolvedValue({ attempt_id: 'attempt-1', events: [] }) },
  } as unknown as ArenaV1Client
}

function renderSurface(arena = client(), report: PreflightReport | null = pass, mode: 'guided' | 'lab' = 'guided') {
  return { arena, ...render(<ExecuteSurface client={arena} frozenExperimentId="frozen-1" preflightReport={report} mode={mode} projectId="project-1" />) }
}

function fillLabProvenance() {
  fireEvent.change(screen.getByLabelText('Canonical ExecutionProvenance JSON'), { target: { value: JSON.stringify({
    code_revision: 'abc123', code_hash: digest, runtime_image: 'registry/worker:1', runtime_image_hash: digest,
    environment_hash: digest, prompt_hash: digest, context_hash: digest, tool_hash: digest,
    source_refs: [{ source_uri: 'artifact://source', content_hash: digest }], captured_at: '2026-08-14T12:00:00Z', protocol_version: '1.0',
  }) } })
}

describe('ExecuteSurface', () => {
  it('blocks creation from a HOLD preflight without calling create', async () => {
    const arena = client()
    renderSurface(arena, { ...pass, verdict: 'HOLD', blockers: [{ code: 'budget', scope: 'experiment', message: 'Budget must be configured.' }] })
    await screen.findByText('Durable execution history')
    expect(screen.getByText('Execution is blocked')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Enqueue durable execution' })).not.toBeInTheDocument()
    expect(arena.executions.create).not.toHaveBeenCalled()
  })

  it('directs a recovered frozen experiment with no report to preflight without submitting it', async () => {
    const onNavigateToPreflight = vi.fn()
    const arena = client()
    render(<ExecuteSurface client={arena} frozenExperimentId="frozen-1" preflightReport={null} mode="guided" onNavigateToPreflight={onNavigateToPreflight} />)

    expect(await screen.findByText(/No current PreflightReport was recovered for this frozen experiment/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Run or recover preflight' })).toBeInTheDocument()
    expect(arena.executions.create).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Run or recover preflight' }))
    expect(onNavigateToPreflight).toHaveBeenCalledOnce()
    expect(arena.executions.create).not.toHaveBeenCalled()
  })

  it('rejects invalid provenance locally and sends no request', async () => {
    const { arena } = renderSurface(client(), pass, 'lab')
    await screen.findByText('Durable execution history')
    fireEvent.click(screen.getByRole('button', { name: 'Enqueue durable execution' }))
    expect(await screen.findByText('Resolve provenance before enqueueing')).toBeInTheDocument()
    expect(arena.executions.create).not.toHaveBeenCalled()
  })

  it('creates with an idempotency key and states the provider boundary', async () => {
    const { arena } = renderSurface(client(), pass, 'lab')
    await screen.findByText('Durable execution history')
    fillLabProvenance()
    fireEvent.click(screen.getByRole('button', { name: 'Enqueue durable execution' }))
    await waitFor(() => expect(arena.executions.create).toHaveBeenCalledTimes(1))
    expect(arena.executions.create).toHaveBeenCalledWith('frozen-1', expect.objectContaining({ code_hash: digest }), expect.objectContaining({ idempotencyKey: expect.any(String) }))
    expect(await screen.findByText(/This API request did not start provider execution/)).toBeInTheDocument()
  })

  it('keeps Guided mode on persisted discovery rather than manual provenance construction', async () => {
    const onSwitchToLab = vi.fn()
    const arena = client()
    render(<ExecuteSurface client={arena} frozenExperimentId="frozen-1" preflightReport={pass} mode="guided" projectId="project-1" onSwitchToLab={onSwitchToLab} />)
    await screen.findByText('Durable execution history')
    expect(screen.getByText('Execution remains HOLD until capture is configured')).toBeInTheDocument()
    expect(screen.getByText(/Configure capture through the local operator workflow/i)).toBeInTheDocument()
    expect(screen.queryByText('uv run arena provenance capture')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Switch to Lab' }))
    expect(onSwitchToLab).toHaveBeenCalledOnce()
    expect(screen.getByText(/Guided mode automatically recovers persisted execution history/)).toBeInTheDocument()
    expect(screen.queryByLabelText('Canonical ExecutionProvenance JSON')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Enqueue durable execution' })).not.toBeInTheDocument()
    expect(screen.queryByText('frozen-1')).not.toBeInTheDocument()
    expect(arena.executions.create).not.toHaveBeenCalled()
  })

  it('hydrates stable execution detail, deduplicates events, and renders terminal observation', async () => {
    const events: ExecutionEvent[] = [
      { cursor: '1', event: 'job_queued', data: { event_id: 'event-1' } },
      { cursor: '2', event: 'job_queued', data: { event_id: 'event-1' } },
      { cursor: '3', event: 'terminal', data: { execution_id: 'exec-1', status: 'completed' } },
    ]
    const get = vi.fn()
      .mockResolvedValueOnce({ ...execution, status: 'running' })
      .mockResolvedValueOnce({ ...execution, status: 'completed' })
    const arena = client({ events: vi.fn(asyncEvents(events)), get })
    renderSurface(arena)
    await screen.findByText('Durable execution history')
    expect(screen.getByText('Run 1')).toBeInTheDocument()
    expect(screen.queryByText('exec-1')).not.toBeInTheDocument()
    await waitFor(() => expect(screen.getByText(/2 unique persisted events received/)).toBeInTheDocument())
    await waitFor(() => expect(get).toHaveBeenCalledTimes(2))
    expect(get).toHaveBeenLastCalledWith('exec-1', expect.any(Object))
  })

  it('keeps Guided run records behind native disclosures while retaining the status and boundary', async () => {
    renderSurface()
    await screen.findByText('Durable execution history')
    expect(screen.getByText('Execution state')).toBeInTheDocument()
    expect(screen.getAllByText('queued', { exact: true }).length).toBeGreaterThan(0)
    expect(screen.getByText(/durable protocol record, not provider or benchmark evidence/)).toBeInTheDocument()
    const attempts = screen.getByText('Attempts (1) — show records').closest('details')
    const jobs = screen.getByText('Durable jobs (1) — show records').closest('details')
    const events = screen.getByText('Live durable events (0) — show log').closest('details')
    expect(attempts).not.toHaveAttribute('open')
    expect(jobs).not.toHaveAttribute('open')
    expect(events).not.toHaveAttribute('open')
  })

  it('keeps the full record panels open in Lab mode', async () => {
    renderSurface(client(), pass, 'lab')
    await screen.findByText('Durable execution history')
    expect(screen.getByRole('heading', { name: 'Attempts (1)' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Durable jobs (1)' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Live durable events (0)' })).toBeInTheDocument()
  })

  it('keeps loaded failed child records visible while Guided disclosures remain closed', async () => {
    const arena = client({ get: vi.fn().mockResolvedValue({
      ...execution,
      status: 'completed',
      attempts: [{ ...execution.attempts[0], status: 'failed' }],
      jobs: [{ ...execution.jobs[0], status: 'incomplete' }],
    }) })
    renderSurface(arena)
    await screen.findByText('Loaded execution records')
    expect(screen.getByText('1 failed attempt')).toBeInTheDocument()
    expect(screen.getByText('1 incomplete job')).toBeInTheDocument()
    expect(screen.getByText(/does not include evaluator grades or a severe-failure aggregate/)).toBeInTheDocument()
    expect(screen.getByText('Attempts (1) — show records').closest('details')).not.toHaveAttribute('open')
    expect(screen.getByText('Durable jobs (1) — show records').closest('details')).not.toHaveAttribute('open')
  })

  it('hydrates only the selected stable execution from a paginated list', async () => {
    const second = { execution_id: 'exec-2', experiment_id: 'frozen-1', status: 'queued', started_at: null, completed_at: null, created_at: '2026-08-14T12:01:00Z' }
    const get = vi.fn().mockResolvedValue(execution)
    const arena = client({
      list: vi.fn().mockResolvedValue({ executions: [{ execution_id: execution.execution_id, experiment_id: execution.experiment_id, status: execution.status, started_at: execution.started_at, completed_at: execution.completed_at, created_at: execution.created_at }, second], pagination: { limit: 50, offset: 0, next_offset: 50 }, claim_ceiling: 'status only' }),
      get,
    })
    renderSurface(arena)
    await screen.findByText('Run 2')
    expect(get).toHaveBeenCalledTimes(1)
    expect(get).toHaveBeenCalledWith('exec-1', expect.any(Object))
    expect(screen.getByRole('button', { name: 'Load more' })).toBeInTheDocument()
  })

  it('honors a URL-selected execution outside the first list page', async () => {
    const requested = { ...execution, execution_id: 'exec-99' }
    const get = vi.fn().mockResolvedValue(requested)
    const arena = client({
      list: vi.fn().mockResolvedValue({ executions: [execution], pagination: { limit: 50, offset: 0, next_offset: 50 }, claim_ceiling: 'status only' }),
      get,
    })
    render(<ExecuteSurface client={arena} frozenExperimentId="frozen-1" preflightReport={pass} mode="guided" requestedExecutionId="exec-99" projectId="project-1" />)
    await screen.findByText('Durable execution history')
    expect(get).toHaveBeenCalledWith('exec-99', expect.any(Object))
    expect(screen.getByText('Run 1')).toBeInTheDocument()
    expect(screen.getByText('Run 2')).toBeInTheDocument()
  })

  it('does not substitute a list execution when the URL ID is missing or belongs to another experiment', async () => {
    const mismatch = client({ get: vi.fn().mockResolvedValue({ ...execution, execution_id: 'other-run', experiment_id: 'other-frozen' }) })
    const { rerender } = render(<ExecuteSurface client={mismatch} frozenExperimentId="frozen-1" preflightReport={pass} mode="guided" requestedExecutionId="other-run" projectId="project-1" />)
    expect(await screen.findByText('Execution recovery failed')).toBeInTheDocument()
    expect(screen.getAllByText(/belongs to a different experiment/)).toHaveLength(2)
    expect(screen.queryByText('Execution control')).not.toBeInTheDocument()

    const missing = client({ get: vi.fn().mockRejectedValue(Object.assign(new Error('Not found'), { status: 404 })) })
    rerender(<ExecuteSurface client={missing} frozenExperimentId="frozen-1" preflightReport={pass} mode="guided" requestedExecutionId="missing-run" projectId="project-1" />)
    expect(await screen.findByText('Execution recovery failed')).toBeInTheDocument()
    expect(screen.queryByText('Execution control')).not.toBeInTheDocument()
  })

  it('ignores a delayed prior route detail and never attaches its event stream', async () => {
    let resolvePrior: ((value: ExecutionDetail) => void) | undefined
    const prior = new Promise<ExecutionDetail>((resolve) => { resolvePrior = resolve })
    const later = { ...execution, execution_id: 'exec-b', experiment_id: 'frozen-b', status: 'completed' }
    const get = vi.fn((executionId: string) => executionId === 'exec-a' ? prior : Promise.resolve(later))
    const events = vi.fn(asyncEvents())
    const arena = client({
      list: vi.fn(({ experimentId }: { experimentId: string }) => Promise.resolve({
        executions: [], pagination: { limit: 50, offset: 0, next_offset: null }, claim_ceiling: experimentId,
      })),
      get,
      events,
    })
    const { rerender } = render(<ExecuteSurface client={arena} frozenExperimentId="frozen-a" preflightReport={pass} mode="guided" requestedExecutionId="exec-a" projectId="project-1" />)
    await waitFor(() => expect(get).toHaveBeenCalledWith('exec-a', expect.any(Object)))
    rerender(<ExecuteSurface client={arena} frozenExperimentId="frozen-b" preflightReport={pass} mode="guided" requestedExecutionId="exec-b" projectId="project-1" />)
    await waitFor(() => expect(get).toHaveBeenCalledWith('exec-b', expect.any(Object)))
    resolvePrior?.({ ...execution, execution_id: 'exec-a', experiment_id: 'frozen-a' })
    await waitFor(() => expect(events).toHaveBeenCalledWith('exec-b', expect.any(Object)))
    expect(events).not.toHaveBeenCalledWith('exec-a', expect.any(Object))
  })

  it('runs the bundled fixture only through the bounded server action after PASS', async () => {
    const arena = client()
    const execute = vi.fn().mockResolvedValue({ execution_id: 'fixture-run', expected_attempts: 80, job_ids: [], idempotent_replay: false, fixture_execution_scheduled: true, provider_execution_started_by_request: false, claim_ceiling: 'fixture only' })
    ;(arena as unknown as { offlineDemo: { execute: typeof execute } }).offlineDemo = { execute }
    render(<ExecuteSurface client={arena} frozenExperimentId="frozen-1" preflightReport={pass} mode="guided" isBundledOfflineDemo projectId="project-1" />)
    await screen.findByText('Run bundled offline demo')
    expect(screen.queryByLabelText('Canonical ExecutionProvenance JSON')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Run bundled offline demo' }))
    await waitFor(() => expect(execute).toHaveBeenCalledWith('frozen-1', expect.objectContaining({ idempotencyKey: expect.any(String) })))
    expect(await screen.findByText(/No provider was invoked/)).toBeInTheDocument()
  })

  it('keeps a completed execution in Cockpit until Analyze is explicitly chosen', async () => {
    const onNavigateToAnalyze = vi.fn()
    const arena = client({ get: vi.fn().mockResolvedValue({ ...execution, status: 'completed' }) })
    render(<ExecuteSurface client={arena} frozenExperimentId="frozen-1" preflightReport={pass} mode="guided" projectId="project-1" isBundledOfflineDemo onNavigateToAnalyze={onNavigateToAnalyze} />)
    await screen.findByText('Analyze selected execution')
    expect(screen.getByRole('button', { name: 'Run bundled offline demo' })).toHaveAttribute('data-tone', 'secondary')
    expect(onNavigateToAnalyze).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Analyze selected execution' }))
    expect(onNavigateToAnalyze).toHaveBeenCalledWith('exec-1')
  })

  it('requires cancel confirmation, preserves resume HOLD, and drills into attempt/trace', async () => {
    const arena = client({ get: vi.fn().mockResolvedValue({ ...execution, status: 'incomplete' }) })
    renderSurface(arena)
    await screen.findByText('Durable execution history')
    fireEvent.click(screen.getByRole('button', { name: 'Cancel execution' }))
    expect(screen.getByText('Confirm cancellation')).toBeInTheDocument()
    expect(arena.executions.cancel).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('button', { name: 'Confirm cancel' }))
    await waitFor(() => expect(arena.executions.cancel).toHaveBeenCalledWith('exec-1', expect.any(Object)))
    fireEvent.click(screen.getByRole('button', { name: 'Resume execution' }))
    expect(await screen.findByText(/Resume HOLD/)).toBeInTheDocument()
    fireEvent.click(screen.getByText('Attempts (1) — show records'))
    fireEvent.click(screen.getByRole('button', { name: 'Details' }))
    await screen.findByText('Selected persisted attempt — show records')
    fireEvent.click(screen.getByText('Selected persisted attempt — show records'))
    expect(screen.getByText('Scenario 1')).toBeInTheDocument()
    expect(screen.queryByText('scenario-1')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Load trace' }))
    await waitFor(() => expect(arena.attempts.trace).toHaveBeenCalledWith('attempt-1', expect.any(Object)))
  })

  it('does not offer cancel or resume for a completed execution', async () => {
    const arena = client({ get: vi.fn().mockResolvedValue({ ...execution, status: 'completed' }) })
    renderSurface(arena)
    await screen.findByText('Durable execution history')
    expect(screen.queryByRole('button', { name: 'Cancel execution' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Resume execution' })).not.toBeInTheDocument()
    expect(screen.getByText('No control action is available for this terminal execution state.')).toBeInTheDocument()
  })

  it('offers a recovery action when durable reload is offline', async () => {
    const arena = client({ list: vi.fn().mockRejectedValue(Object.assign(new TypeError('Network unavailable'), { status: 503 })) })
    renderSurface(arena)
    expect(await screen.findByText('Execution recovery is offline')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Retry durable recovery' }))
    await waitFor(() => expect(arena.executions.list).toHaveBeenCalledTimes(2))
  })
})
