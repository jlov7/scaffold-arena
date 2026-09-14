import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import {
  AlignedTraceTimeline,
  AttemptConsistencyDistribution,
  BudgetForecastActualView,
  MainEffectHeatmap,
  ReliabilityCostLatencyPareto,
  SevereFailureMatrix,
  type EvidenceMetadata,
} from './index'

const evidence: EvidenceMetadata = {
  numerator: '18 passing attempts',
  denominator: '24 included attempts',
  exclusions: ['attempt-25 missing trace'],
  includedAttemptIds: ['attempt-01', 'attempt-02'],
  sourceDigest: 'source-sha256',
  analysisDigest: 'analysis-sha256',
  caveat: 'Synthetic fixture — not benchmark evidence.',
  claimCeiling: 'Descriptive local analysis only.',
}

describe('workbench visualizations', () => {
  it('renders semantic values and full evidence metadata through a keyboard disclosure', () => {
    render(<MainEffectHeatmap evidence={evidence} data={[{ factor: 'Planner', level: 'on', effect: 0.24, ciLow: 0.12, ciHigh: 0.36 }]} />)

    expect(screen.getByRole('table', { name: 'Main effect values' })).toHaveTextContent('0.24')
    const disclosure = screen.getByText('Evidence and limitations')
    fireEvent.keyDown(disclosure, { key: 'Enter' })
    fireEvent.click(disclosure)
    expect(screen.getByText('source-sha256')).toBeInTheDocument()
    expect(screen.getByText('Descriptive local analysis only.')).toBeInTheDocument()
  })

  it('keeps unknown actual cost distinct from zero actual cost', () => {
    render(<BudgetForecastActualView evidence={evidence} data={[
      { label: 'Provider usage', forecast: 12, actual: null, unit: 'usd' },
      { label: 'Storage', forecast: 1, actual: 0, unit: 'usd' },
      { label: 'Trace tokens', forecast: 600, actual: 0, unit: 'tokens' },
    ]} />)

    expect(screen.getByRole('table', { name: 'Budget forecast and actual values' })).toHaveTextContent('Unknown')
    expect(screen.getAllByText('$0.00').find((element) => element.getAttribute('data-value-state') === 'zero')).toBeTruthy()
    expect(screen.getAllByText('Unknown').find((element) => element.getAttribute('data-value-state') === 'unknown')).toBeTruthy()
    expect(screen.getAllByText('0 tokens').find((element) => element.getAttribute('data-value-state') === 'zero')).toBeTruthy()
  })

  it('partitions unpriced or incomplete Pareto rows without assigning plot coordinates or status', () => {
    render(<ReliabilityCostLatencyPareto evidence={evidence} data={[
      { label: 'Measured', reliability: 0.8, cost: 0.02, latencyMs: 120, pareto: true },
      { label: 'Unpriced', reliability: 0.7, cost: null, latencyMs: 140, pareto: true },
      { label: 'No latency', reliability: null, cost: 0.03, latencyMs: null, pareto: false },
    ]} />)

    const incomplete = screen.getByRole('region', { name: 'Unpriced or incomplete' })
    expect(incomplete).toHaveTextContent('Unpriced')
    expect(incomplete).toHaveTextContent('No latency')
    expect(incomplete).toHaveTextContent('no geometric position or Pareto status')
    expect(incomplete.querySelectorAll('circle')).toHaveLength(0)
    expect(incomplete.querySelectorAll('[data-pareto]')).toHaveLength(0)
    const table = screen.getByRole('table', { name: 'Reliability cost latency values' })
    expect(table).toHaveTextContent('Not assessed (incomplete inputs)')
    expect(table.querySelectorAll('circle')).toHaveLength(0)
  })

  it('renders every supplied severe failure and exposes a keyboard-accessible resolution action', () => {
    const resolve = vi.fn()
    render(<SevereFailureMatrix evidence={evidence} onResolve={resolve} data={[
      { id: 'f-1', category: 'Permission', description: 'Project context denied', affectedAttempts: ['attempt-01'], resolution: 'Restore project context' },
      { id: 'f-2', category: 'Integrity', description: 'Trace digest mismatch', affectedAttempts: ['attempt-02'], resolution: 'Reacquire trace' },
    ]} />)

    expect(screen.getByLabelText('Severe failure matrix')).toHaveAttribute('data-severe-visible', 'true')
    expect(screen.getByRole('table', { name: 'All severe failures' })).toHaveTextContent('Project context denied')
    expect(screen.getByRole('table', { name: 'All severe failures' })).toHaveTextContent('Trace digest mismatch')
    fireEvent.keyDown(screen.getByRole('button', { name: 'Resolve severe failures' }), { key: 'Enter' })
    fireEvent.click(screen.getByRole('button', { name: 'Resolve severe failures' }))
    expect(resolve).toHaveBeenCalledOnce()
  })

  it('keeps a zero-failure matrix visible without announcing a failure alert', () => {
    render(<SevereFailureMatrix evidence={evidence} data={[]} />)

    expect(screen.getByRole('status')).toHaveTextContent('Severe failures (0)')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByRole('table', { name: 'All severe failures' })).toHaveTextContent('No values available.')
  })

  it('does not conflate pass@1, pass@k, and pass^k', () => {
    render(<AttemptConsistencyDistribution evidence={evidence} data={[{ treatment: 'Rerank', passAt1: 0.25, passAtK: 0.75, passPowerK: 0.02, k: 3 }]} />)

    const table = screen.getByRole('table', { name: 'Attempt consistency values' })
    expect(table).toHaveTextContent('25.0%')
    expect(table).toHaveTextContent('75.0%')
    expect(table).toHaveTextContent('2.0%')
    expect(screen.getByText('pass^3')).toBeInTheDocument()
  })

  it('preserves the trace diagnostic ceiling and can render an actionable empty state', () => {
    const inspect = vi.fn()
    render(<AlignedTraceTimeline evidence={evidence} state={{ kind: 'empty', title: 'No aligned traces', description: 'Select two persisted attempt traces.', action: { label: 'Inspect attempts', onAction: inspect } }} data={{ leftAttemptId: 'attempt-01', rightAttemptId: 'attempt-02', firstDivergence: null, confidence: null, events: [] }} />)

    expect(screen.getByText('DIAGNOSTIC_ONLY')).toBeInTheDocument()
    expect(screen.getByText(/does not establish cause/i)).toBeInTheDocument()
    expect(screen.getByText(/First divergence: Unknown/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Inspect attempts' }))
    expect(inspect).toHaveBeenCalledOnce()
  })
})
