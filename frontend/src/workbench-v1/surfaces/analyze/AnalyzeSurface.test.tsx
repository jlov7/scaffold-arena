import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ApiProblem, type AnalysisReportDetail } from '../../../api/v1/client'
import { type ArenaV1Client } from '../../journeys/study-design-preflight/types'
import { AnalyzeSurface } from './AnalyzeSurface'

const config = { registered_factors: [], primary_main_effects: [], secondary_interactions: [], gates: {}, options: {} }
const detail = {
  report_digest: 'report-digest', artifact_digest: 'artifact-digest', artifact_ref: 'sha256:artifact-digest', source_digests: { input_digest: 'input-digest', spec_hash: 'spec', study_pack_hash: 'pack', configuration_digest: 'config' },
  binding: {}, adequacy: {}, claim_ceiling: 'DESCRIPTIVE_ONLY', integrity_not_truth: true,
  report: {
    included_attempt_ids: ['attempt-1'], exclusions: [], severe_failures_before_composites: [['integrity', 1]], profiles: [{ profile_id: 'p1', attempt_ids: ['attempt-1'], pass_at_1: { value: null }, pass_at_k: { series_id: 'pass_at_unparseable', value: null }, pass_power_k: { value: null }, cost_status: 'unknown', cost_usd: { value: null }, latency_seconds: { value: null } }],
    main_effects: [{ effect_id: 'plan', outcome: 'pass', estimate: null, confidence_interval: [null, null] }], secondary_interactions: [], clean_vs_stressed_tax: [{ effect_id: 'tax', outcome: 'pass', estimate: 0.25, confidence_interval: [0.1, 0.4], status: 'ESTIMATED', reason: null }], pareto_profile_ids: [], trace_attribution_note: 'diagnostic only',
  },
} as unknown as AnalysisReportDetail

function client(overrides: Record<string, unknown> = {}): ArenaV1Client {
  return {
    experiments: { get: vi.fn().mockResolvedValue({ definition: { extensions: { 'org.scaffold-arena.analysis-v1': config } } }) },
    analysisReports: { list: vi.fn().mockResolvedValue({ analysis_reports: [{ report_digest: 'report-digest', created_at: 'now', claim_ceiling: 'DESCRIPTIVE_ONLY', integrity_not_truth: true }] }), get: vi.fn().mockResolvedValue(detail) },
    analysis: vi.fn().mockResolvedValue({ verdict: 'HOLD' }), exports: { analysis: vi.fn() }, ...overrides,
  } as unknown as ArenaV1Client
}

describe('AnalyzeSurface', () => {
  it('distinguishes no durable report from an unavailable report service', async () => {
    const arena = client({ analysisReports: { list: vi.fn().mockResolvedValue({ analysis_reports: [] }), get: vi.fn() } })
    render(<AnalyzeSurface client={arena} experimentId="experiment-1" executionId="execution-1" />)
    expect(await screen.findByText('No durable analysis report')).toBeInTheDocument()
    expect(screen.getByText(/No report is inferred from local state/)).toBeInTheDocument()
  })

  it('recovers verified detail, keeps severe failures visible, and preserves unknown values', async () => {
    render(<AnalyzeSurface client={client()} experimentId="experiment-1" executionId="execution-1" projectId="project-1" />)
    expect(await screen.findByText('Verified report integrity and claim ceiling')).toBeInTheDocument()
    expect(screen.getByLabelText('Severe failure matrix')).toHaveAttribute('data-severe-visible', 'true')
    expect(screen.getByRole('table', { name: 'Main effect values' })).toHaveTextContent('Unknown')
    expect(screen.getByRole('table', { name: 'Clean versus stressed paired differences' })).toHaveTextContent('Stress-minus-clean difference')
    expect(screen.getByText(/pass@k is Unknown/)).toBeInTheDocument()
  })

  it('keeps Guided analysis evidence actionable without rendering raw durable identities or canonical config', async () => {
    render(<AnalyzeSurface client={client()} mode="guided" experimentId="experiment-1" executionId="execution-1" projectId="project-1" />)
    expect(await screen.findByText('Verified report integrity and claim ceiling')).toBeInTheDocument()
    expect(screen.getByText('Selected frozen comparison')).toBeInTheDocument()
    expect(screen.queryByText('experiment-1')).not.toBeInTheDocument()
    expect(screen.queryByText('execution-1')).not.toBeInTheDocument()
    expect(screen.queryByText('report-digest')).not.toBeInTheDocument()
    expect(screen.queryByText('input-digest')).not.toBeInTheDocument()
    expect(screen.queryByText('Frozen preregistered analysis configuration')).not.toBeInTheDocument()
    expect(screen.getAllByText('Withheld in Guided; verify through Evidence Room.').length).toBeGreaterThan(0)
  })

  it('uses an exact URL-selected report digest and never substitutes a different report', async () => {
    const get = vi.fn().mockResolvedValue(detail)
    const arena = client({ analysisReports: { list: vi.fn().mockResolvedValue({ analysis_reports: [{ report_digest: 'other-report' }, { report_digest: 'report-digest' }] }), get } })
    render(<AnalyzeSurface client={arena} experimentId="experiment-1" executionId="execution-1" initialReportDigest="report-digest" />)
    await screen.findByText('Verified report integrity and claim ceiling')
    expect(get).toHaveBeenCalledWith('report-digest', { projectId: undefined })

    const missing = client({ analysisReports: { list: vi.fn().mockResolvedValue({ analysis_reports: [{ report_digest: 'other-report' }] }), get: vi.fn() } })
    render(<AnalyzeSurface client={missing} experimentId="experiment-1" executionId="execution-1" initialReportDigest="gone" />)
    expect(await screen.findByText('Analysis recovery failed')).toHaveTextContent('Analysis recovery failed')
    expect(missing.analysisReports.get).not.toHaveBeenCalled()
  })

  it('submits only the frozen extension configuration and renders HOLD from tamper/config rejection', async () => {
    const arena = client()
    render(<AnalyzeSurface client={arena} experimentId="experiment-1" executionId="execution-1" projectId="project-1" />)
    await screen.findByText('Verified report integrity and claim ceiling')
    fireEvent.click(screen.getByRole('button', { name: 'Create immutable analysis' }))
    await waitFor(() => expect(arena.analysis).toHaveBeenCalledWith({ experiment_id: 'experiment-1', execution_id: 'execution-1', analysis_config: config }, { projectId: 'project-1' }))

    const held = client({ analysisReports: { list: vi.fn().mockResolvedValue({ analysis_reports: [{ report_digest: 'report-digest', created_at: 'now', claim_ceiling: 'DESCRIPTIVE_ONLY', integrity_not_truth: true }] }), get: vi.fn().mockRejectedValue(new ApiProblem(409, { verdict: 'HOLD', error: { message: 'artifact mismatch' } }, 'HOLD')) } })
    render(<AnalyzeSurface client={held} experimentId="experiment-1" executionId="execution-1" />)
    expect(await screen.findByText('Analysis HOLD')).toHaveTextContent('Analysis HOLD')
  })
})
