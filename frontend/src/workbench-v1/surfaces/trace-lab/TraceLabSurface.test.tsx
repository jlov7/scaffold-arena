import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { type ArenaV1Client } from '../../journeys/study-design-preflight/types'
import { TraceLabSurface } from './TraceLabSurface'

const SOURCE_DIGEST = 'd'.repeat(64)
const LEFT_DIGEST = 'a'.repeat(64)
const RIGHT_DIGEST = 'b'.repeat(64)

function client(): ArenaV1Client {
  return {
    traceLab: {
      analyze: vi.fn().mockResolvedValue({
        analysis_digest: 'trace-digest',
        analysis_version: 'trace-lab-v1.1',
        mode: 'COMPLETE_TRACE_DIAGNOSTIC',
        causal_label: 'DIAGNOSTIC_ONLY',
        claim_ceiling: 'diagnostic only',
        attempt_links: {
          left: { attempt_id: 'left', trace_url: '/api/v1/attempts/left/trace' },
          right: { attempt_id: 'right', trace_url: '/api/v1/attempts/right/trace' },
        },
        source_event_ids: {
          left: ['event-left-request', 'event-left-tool'],
          right: ['event-right-request', 'event-right-tool'],
        },
        alignment: {
          source_digest: SOURCE_DIGEST,
          source_digests: { left: LEFT_DIGEST, right: RIGHT_DIGEST },
          matched_anchors: 2,
          exact_observation_matches: 1,
          content_differences: 1,
          left_only: 0,
          right_only: 0,
          clock_skew_tolerant: true,
          rows: [
            {
              position: 0,
              status: 'MATCH',
              anchor: 'request',
              left: { event_id: 'event-left-request', ordinal: 0, observation_digest: LEFT_DIGEST, relative_ms: 0, evidence_ref: null },
              right: { event_id: 'event-right-request', ordinal: 0, observation_digest: LEFT_DIGEST, relative_ms: 0, evidence_ref: null },
            },
            {
              position: 1,
              status: 'CONTENT_DIFFERENCE',
              anchor: 'tool_call',
              left: { event_id: 'event-left-tool', ordinal: 1, observation_digest: LEFT_DIGEST, relative_ms: 10, evidence_ref: 'state:left' },
              right: { event_id: 'event-right-tool', ordinal: 1, observation_digest: RIGHT_DIGEST, relative_ms: 12, evidence_ref: 'state:right' },
            },
          ],
        },
        first_meaningful_divergence: {
          found: true,
          label: 'DIAGNOSTIC_ONLY',
          reason: 'tool_call observation digests differ at the same semantic anchor',
          confidence: 0.95,
          alignment_position: 1,
          left_event_id: 'event-left-tool',
          right_event_id: 'event-right-tool',
          evidence_refs: ['state:left', 'state:right'],
          state_before: { left: null, right: null },
          state_after: { left: null, right: null },
          state_ref_diff: {
            left: { state_id: { before: 'a', after: 'b' } },
            right: {},
          },
        },
        coverage: { numerator: 2, denominator: 2, exclusions: [] },
      }),
    },
  } as unknown as ArenaV1Client
}

describe('TraceLabSurface', () => {
  it('rejects same-attempt comparison in the browser without a request', () => {
    const arena = client()
    render(<TraceLabSurface client={arena} />)
    fireEvent.change(screen.getByLabelText('Left persisted attempt ID'), { target: { value: 'same' } })
    fireEvent.change(screen.getByLabelText('Right persisted attempt ID'), { target: { value: 'same' } })
    fireEvent.click(screen.getByRole('button', { name: 'Compare persisted traces' }))
    expect(arena.traceLab.analyze).not.toHaveBeenCalled()
    expect(screen.getByText('Trace diagnostic HOLD')).toBeInTheDocument()
  })

  it('renders diagnostic ceiling, source digest, aligned rows, and observed state diffs', async () => {
    const arena = client()
    render(<TraceLabSurface client={arena} />)
    fireEvent.change(screen.getByLabelText('Left persisted attempt ID'), { target: { value: 'left' } })
    fireEvent.change(screen.getByLabelText('Right persisted attempt ID'), { target: { value: 'right' } })
    fireEvent.click(screen.getByRole('button', { name: 'Compare persisted traces' }))
    await waitFor(() => expect(arena.traceLab.analyze).toHaveBeenCalledWith({ left_attempt_id: 'left', right_attempt_id: 'right' }, { projectId: undefined }))
    expect((await screen.findAllByText('DIAGNOSTIC_ONLY')).length).toBeGreaterThan(0)
    expect(screen.getByRole('table', { name: 'State before and after values' })).toHaveTextContent('left.state_id')
    expect(screen.getByRole('table', { name: 'Aligned trace events' })).toHaveTextContent('event-left-request')
    expect(screen.getByRole('table', { name: 'Aligned trace events' })).toHaveTextContent('event-right-tool')
    expect(screen.getByRole('table', { name: 'Aligned trace events' })).toHaveTextContent('diverged')
    expect(screen.getAllByText(SOURCE_DIGEST).length).toBeGreaterThan(0)
    expect(screen.getByText('Content differences')).toBeInTheDocument()
    expect(screen.queryByText(/does not supply a source digest/)).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /regression/i })).not.toBeInTheDocument()
  })

  it('reports an exact persisted attempt pair for URL ownership', async () => {
    const onAttemptPairSelected = vi.fn()
    render(<TraceLabSurface client={client()} initialLeftAttemptId="left" initialRightAttemptId="right" onAttemptPairSelected={onAttemptPairSelected} />)
    fireEvent.click(screen.getByRole('button', { name: 'Compare persisted traces' }))
    await waitFor(() => expect(onAttemptPairSelected).toHaveBeenCalledWith('left', 'right'))
  })

  it('keeps Guided on automatic persisted-attempt discovery rather than raw IDs', async () => {
    const arena = {
      ...client(),
      executions: {
        get: vi.fn().mockResolvedValue({
          attempts: [{ attempt_id: 'internal-attempt-1', status: 'completed' }],
        }),
      },
    } as unknown as ArenaV1Client
    render(<TraceLabSurface client={arena} mode="guided" executionId="internal-execution" />)

    expect(await screen.findByText('Persisted attempt 1')).toBeInTheDocument()
    expect(screen.queryByLabelText('Left persisted attempt ID')).not.toBeInTheDocument()
    expect(screen.queryByText('internal-attempt-1')).not.toBeInTheDocument()
  })

  it('withholds raw trace access from Guided diagnostics', async () => {
    const arena = client()
    render(<TraceLabSurface client={arena} mode="guided" initialLeftAttemptId="left" initialRightAttemptId="right" />)

    fireEvent.click(screen.getByRole('button', { name: 'Compare persisted traces' }))
    await waitFor(() => expect(arena.traceLab.analyze).toHaveBeenCalled())
    expect(screen.queryByText('Raw persisted traces:')).not.toBeInTheDocument()
    expect(screen.getByText(/Raw trace access and durable identities are available in Lab/)).toBeInTheDocument()
  })
})
