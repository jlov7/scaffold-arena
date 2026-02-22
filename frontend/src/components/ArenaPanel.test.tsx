import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import ArenaPanel from './ArenaPanel'
import type { PanelState } from '../types'

function basePanel(): PanelState {
  return {
    scaffoldId: 'bare',
    scaffoldName: 'Bare Prompt',
    status: 'idle',
    phase: '',
    streamedText: '',
    output: '',
    metrics: null,
    evaluation: null,
    error: null,
  }
}

describe('ArenaPanel', () => {
  it('renders winner badge and score for winner panels', () => {
    const panel: PanelState = {
      ...basePanel(),
      status: 'winner',
      metrics: {
        input_tokens: 10,
        output_tokens: 10,
        cost_usd: 0.01,
        wall_time_ms: 1200,
        num_api_calls: 1,
      },
      evaluation: {
        total_score: 88,
        breakdown: {},
        weights: {},
        notes: [],
        judge: null,
      },
    }

    render(<ArenaPanel panel={panel} />)
    expect(screen.getByText('WINNER')).toBeInTheDocument()
    expect(screen.getByText('/ 100')).toBeInTheDocument()
  })

  it('renders failed state with error message', () => {
    const panel: PanelState = {
      ...basePanel(),
      status: 'failed',
      error: 'Timed out',
    }

    render(<ArenaPanel panel={panel} />)
    expect(screen.getByText('FAILED')).toBeInTheDocument()
    expect(screen.getByText('Timed out')).toBeInTheDocument()
  })

  it('renders guidance when completed panel has no output', () => {
    const panel: PanelState = {
      ...basePanel(),
      status: 'completed',
    }

    render(<ArenaPanel panel={panel} />)
    expect(
      screen.getByText(/No output was captured for this run/i),
    ).toBeInTheDocument()
  })

  it('renders failure guidance when failed panel has no output and no error', () => {
    const panel: PanelState = {
      ...basePanel(),
      status: 'failed',
      error: null,
    }

    render(<ArenaPanel panel={panel} />)
    expect(
      screen.getByText(/Run failed before output was generated/i),
    ).toBeInTheDocument()
  })
})
