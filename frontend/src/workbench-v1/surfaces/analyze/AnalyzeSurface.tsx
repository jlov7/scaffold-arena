import { useCallback, useEffect, useState } from 'react'

import { ApiProblem, createArenaV1, type AnalysisEffectReport, type AnalysisReportDetail, type ExperimentDetail, type JsonObject } from '../../../api/v1/client'
import { DisclosureRow, SevereFailureBanner, StatusIndicator, WorkbenchButton, WorkbenchPanel, WorkbenchState, WorkbenchTable } from '../../design-system'
import {
  AttemptConsistencyDistribution,
  BudgetForecastActualView,
  MainEffectHeatmap,
  PairwiseInteractionMap,
  ReliabilityCostLatencyPareto,
  SevereFailureMatrix,
  type EvidenceMetadata,
} from '../../visualizations'

import './analyze.css'

type ArenaV1Client = ReturnType<typeof createArenaV1>
type LoadState = 'loading' | 'ready' | 'empty' | 'offline' | 'permission' | 'hold' | 'error'

const ANALYSIS_EXTENSION = 'org.scaffold-arena.analysis-v1'

export interface AnalyzeSurfaceProps {
  client: ArenaV1Client
  mode?: 'guided' | 'lab'
  experimentId: string | null
  executionId: string | null
  projectId?: string
  initialReportDigest?: string | null
  onReportSelected?: (reportDigest: string) => void
  onNavigateToExecute?: () => void
  onNavigateToDesign?: () => void
}

function problem(error: unknown): { state: Extract<LoadState, 'offline' | 'permission' | 'hold' | 'error'>; message: string } {
  if (error instanceof ApiProblem) {
    if (error.isHold) return { state: 'hold', message: error.message }
    if (error.status === 401 || error.status === 403 || error.code === 'project_context_required' || error.code === 'unknown_project') return { state: 'permission', message: error.message }
    if (error.status >= 500) return { state: 'offline', message: error.message }
    return { state: 'error', message: error.message }
  }
  return { state: 'offline', message: error instanceof Error ? error.message : 'The analysis service could not be reached.' }
}

function record(value: unknown): JsonObject { return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as JsonObject : {} }
function configFromExperiment(experiment: ExperimentDetail | null): JsonObject | null {
  const extensions = record(experiment?.definition.extensions)
  const config = extensions[ANALYSIS_EXTENSION]
  return config !== null && typeof config === 'object' && !Array.isArray(config) ? config as JsonObject : null
}
function effectEvidence(detail: AnalysisReportDetail, mode: 'guided' | 'lab', effect?: AnalysisEffectReport): EvidenceMetadata {
  const series = effect?.series
  return {
    numerator: series ? String(series.numerator) : 'Unknown', denominator: series ? String(series.denominator) : 'Unknown',
    exclusions: (series?.exclusions ?? detail.report.exclusions).map(([id, reason]) => `${id}: ${reason}`),
    includedAttemptIds: series?.constituent_attempt_ids.length ? series.constituent_attempt_ids : series?.attempt_ids ?? detail.report.included_attempt_ids,
    sourceDigest: detail.source_digests.input_digest, analysisDigest: detail.report_digest,
    caveat: detail.report.trace_attribution_note, claimCeiling: detail.claim_ceiling,
    display: mode,
  }
}
function reportEvidence(detail: AnalysisReportDetail, mode: 'guided' | 'lab'): EvidenceMetadata { return effectEvidence(detail, mode) }
function download(blob: Blob, filename: string) {
  const href = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = href; anchor.download = filename; anchor.click()
  URL.revokeObjectURL(href)
}

export function AnalyzeSurface({ client, mode = 'lab', experimentId, executionId, projectId, initialReportDigest, onReportSelected, onNavigateToExecute, onNavigateToDesign }: AnalyzeSurfaceProps) {
  const [state, setState] = useState<LoadState>('loading')
  const [message, setMessage] = useState('')
  const [experiment, setExperiment] = useState<ExperimentDetail | null>(null)
  const [reports, setReports] = useState<Awaited<ReturnType<ArenaV1Client['analysisReports']['list']>>['analysis_reports']>([])
  const [selected, setSelected] = useState<AnalysisReportDetail | null>(null)
  const [busy, setBusy] = useState(false)

  const preregistered = configFromExperiment(experiment)
  const load = useCallback(async () => {
    if (!experimentId || !executionId) { setState('empty'); setReports([]); setSelected(null); return }
    setState('loading'); setMessage('')
    try {
      const [storedExperiment, list] = await Promise.all([
        client.experiments.get(experimentId, { projectId }),
        client.analysisReports.list({ experimentId, executionId }, { projectId }),
      ])
      setExperiment(storedExperiment); setReports(list.analysis_reports)
      if (list.analysis_reports.length === 0) { setSelected(null); setState('empty'); return }
      const selectedSummary = initialReportDigest ? list.analysis_reports.find((item) => item.report_digest === initialReportDigest) : list.analysis_reports[0]
      if (!selectedSummary) { setSelected(null); setState('error'); setMessage('The URL-selected report digest is not available for this persisted execution. No replacement report was selected.'); return }
      const detail = await client.analysisReports.get(selectedSummary.report_digest, { projectId })
      setSelected(detail); setState('ready')
    } catch (error) {
      const next = problem(error); setState(next.state); setMessage(next.message); setSelected(null)
    }
  }, [client, executionId, experimentId, initialReportDigest, projectId])

  useEffect(() => { void load() }, [load])

  const selectReport = async (digest: string) => {
    setBusy(true); setMessage('Verifying immutable report bytes and bindings…')
    try { setSelected(await client.analysisReports.get(digest, { projectId })); onReportSelected?.(digest); setState('ready'); setMessage('') }
    catch (error) { const next = problem(error); setState(next.state); setMessage(next.message) }
    finally { setBusy(false) }
  }
  const create = async () => {
    if (!experimentId || !executionId || !preregistered) return
    setBusy(true); setMessage('Submitting only the frozen preregistered analysis configuration…')
    try {
      const response = await client.analysis({ experiment_id: experimentId, execution_id: executionId, analysis_config: preregistered }, { projectId })
      const reportDigest = typeof response.report_digest === 'string' ? response.report_digest : undefined
      if (reportDigest) onReportSelected?.(reportDigest)
      setMessage(response.verdict === 'HOLD' ? 'Analysis returned HOLD. Review the durable evidence limitations below.' : 'Analysis report admitted; recovering its verified immutable detail.')
      await load()
    } catch (error) { const next = problem(error); setState(next.state); setMessage(next.message) }
    finally { setBusy(false) }
  }
  const exportReport = async (format: 'csv' | 'parquet') => {
    if (!selected) return
    setBusy(true)
    try { const result = await client.exports.analysis(selected.report_digest, format, { projectId }); download(result.blob, result.filename ?? `analysis-${selected.report_digest}.${format}`) }
    catch (error) { setMessage(problem(error).message) }
    finally { setBusy(false) }
  }

  if (!experimentId || !executionId) return <WorkbenchState kind="empty" title="Select persisted experiment and execution" action={onNavigateToExecute && <WorkbenchButton onClick={onNavigateToExecute}>Open Execute</WorkbenchButton>}>Analyze recovers immutable reports only for an explicit persisted experiment and execution.</WorkbenchState>
  if (state === 'loading') return <WorkbenchState kind="loading" title="Recovering verified analysis reports">Loading durable report summaries and verifying the selected immutable report.</WorkbenchState>
  if (state === 'offline') return <WorkbenchState kind="offline" title="Analysis recovery unavailable" action={<WorkbenchButton onClick={() => void load()}>Retry recovery</WorkbenchButton>}>{message || 'Reconnect to recover durable report artifacts.'}</WorkbenchState>
  if (state === 'permission') return <SevereFailureBanner title="Project context required" action={<WorkbenchButton onClick={() => void load()}>Retry with project context</WorkbenchButton>}>{message || 'Choose a project that owns this experiment and execution.'}</SevereFailureBanner>
  if (state === 'hold') return <SevereFailureBanner title="Analysis HOLD" action={<WorkbenchButton onClick={() => void load()}>Reload durable evidence</WorkbenchButton>}>{message || 'The report cannot be admitted or verified from the available durable evidence.'}</SevereFailureBanner>
  if (state === 'error') return <WorkbenchState kind="error" title="Analysis recovery failed" action={<WorkbenchButton onClick={() => void load()}>Retry recovery</WorkbenchButton>}>{message}</WorkbenchState>

  const report = selected?.report
  return <section className="sa-analyze" aria-labelledby="analyze-heading">
    <WorkbenchPanel title={<span id="analyze-heading">Analyze persisted execution</span>} action={<StatusIndicator tone={report ? 'ready' : 'warning'}>{report ? 'Verified report selected' : 'No report'}</StatusIndicator>}>
      <div className="sa-analyze-summary"><div><span>Experiment</span>{mode === 'lab' ? <code>{experimentId}</code> : <strong>Selected frozen comparison</strong>}</div><div><span>Execution</span>{mode === 'lab' ? <code>{executionId}</code> : <strong>Selected durable run</strong>}</div><div><span>Frozen preregistration</span><strong>{preregistered ? 'Available' : 'Missing'}</strong></div></div>
      <p className="sa-analyze-boundary">Create uses only the exact frozen analysis configuration. Browser defaults, scores, traces, costs, and usage are never submitted.</p>
      {!preregistered && <SevereFailureBanner title="Analysis is not preregistered" action={onNavigateToDesign ? <WorkbenchButton onClick={onNavigateToDesign}>Open Design</WorkbenchButton> : <a href="/workbench/design">Open Design</a>}>The selected frozen experiment has no readable Analysis v1 extension. Create a new correctly preregistered frozen experiment; this surface will not supply a configuration.</SevereFailureBanner>}
      <div className="sa-journey-actions"><WorkbenchButton tone="primary" disabled={busy || !preregistered} onClick={() => void create()}>Create immutable analysis</WorkbenchButton><WorkbenchButton disabled={busy} onClick={() => void load()}>Reload reports</WorkbenchButton></div>
      {message && <p className="sa-journey-status" role="status">{message}</p>}
      {preregistered && mode === 'lab' && <DisclosureRow title="Frozen preregistered analysis configuration"><pre className="sa-analyze-json">{JSON.stringify(preregistered, null, 2)}</pre></DisclosureRow>}
    </WorkbenchPanel>

    {state === 'empty' && <WorkbenchState kind="empty" title="No durable analysis report" action={preregistered ? <WorkbenchButton disabled={busy} onClick={() => void create()}>Create from frozen preregistration</WorkbenchButton> : undefined}>A completed execution and an exact frozen analysis configuration are required. No report is inferred from local state.</WorkbenchState>}
    {reports.length > 0 && <WorkbenchPanel title="Verified durable reports"><WorkbenchTable><thead><tr><th scope="col">{mode === 'lab' ? 'Report digest' : 'Report'}</th><th scope="col">Created</th><th scope="col">Adequacy ceiling</th><th scope="col">Integrity</th><th scope="col">Select</th></tr></thead><tbody>{reports.map((item, index) => <tr key={item.report_digest} aria-selected={selected?.report_digest === item.report_digest}><td>{mode === 'lab' ? <code>{item.report_digest}</code> : `Report ${index + 1}`}</td><td>{item.created_at}</td><td>{item.claim_ceiling}</td><td>{item.integrity_not_truth ? 'Integrity verified; not truth' : 'Unknown'}</td><td><WorkbenchButton disabled={busy || selected?.report_digest === item.report_digest} onClick={() => void selectReport(item.report_digest)}>Verify detail</WorkbenchButton></td></tr>)}</tbody></WorkbenchTable></WorkbenchPanel>}

    {selected && report && <ReportView detail={selected} mode={mode} onExport={exportReport} />}
  </section>
}

function ReportView({ detail, mode, onExport }: { detail: AnalysisReportDetail; mode: 'guided' | 'lab'; onExport: (format: 'csv' | 'parquet') => void }) {
  const report = detail.report
  const evidence = reportEvidence(detail, mode)
  const main = report.main_effects.map((effect) => ({ factor: effect.effect_id, level: effect.outcome, effect: effect.estimate, ciLow: effect.confidence_interval[0], ciHigh: effect.confidence_interval[1] }))
  const interactions = report.secondary_interactions.map((effect) => ({ leftFactor: effect.effect_id, rightFactor: effect.outcome, interaction: effect.estimate, ciLow: effect.confidence_interval[0], ciHigh: effect.confidence_interval[1] }))
  const pareto = report.profiles.map((profile) => ({ label: profile.profile_id, reliability: profile.pass_at_1.value, cost: profile.cost_usd.value, latencyMs: profile.latency_seconds.value === null ? null : profile.latency_seconds.value * 1000, pareto: report.pareto_profile_ids.includes(profile.profile_id) }))
  const consistency = report.profiles.flatMap((profile) => {
    const match = profile.pass_at_k.series_id.match(/pass_at_(\d+)/)
    return match ? [{ treatment: profile.profile_id, passAt1: profile.pass_at_1.value, passAtK: profile.pass_at_k.value, passPowerK: profile.pass_power_k.value, k: Number(match[1]) }] : []
  })
  const unknownKProfiles = report.profiles.filter((profile) => !/pass_at_(\d+)/.test(profile.pass_at_k.series_id))
  const severe = report.severe_failures_before_composites.map(([id, count]) => ({ id, category: id, description: `${count} severe failure${count === 1 ? '' : 's'} reported before composites.`, affectedAttempts: [] as string[], resolution: 'Inspect the immutable report exclusions and included-attempt list; affected attempt IDs are not enumerated by this aggregate.' }))
  const budget = report.profiles.map((profile) => ({ label: `${profile.profile_id} provider cost`, forecast: null, actual: profile.cost_status === 'reconciled' ? profile.cost_usd.value : null, unit: 'usd' as const }))
  const exportEvidence = { ...evidence, export: { label: 'Export CSV', onExport: () => onExport('csv') } }
  return <>
    <SevereFailureMatrix data={severe} evidence={evidence} />
    <WorkbenchPanel title="Verified report integrity and claim ceiling" action={<StatusIndicator tone="info">integrity_not_truth</StatusIndicator>}>
      <div className="sa-analyze-summary"><div><span>Report</span>{mode === 'lab' ? <code>{detail.report_digest}</code> : <strong>Selected durable report</strong>}</div><div><span>Artifact</span>{mode === 'lab' ? <code>{detail.artifact_digest}</code> : <strong>Integrity-bound artifact</strong>}</div><div><span>Claim ceiling</span><strong>{detail.claim_ceiling}</strong></div><div><span>Included attempts</span><strong>{report.included_attempt_ids.length}</strong></div></div>
      <p className="sa-analyze-boundary">Artifact integrity and canonical binding do not prove outcome correctness, causal attribution, live-provider validity, or independent reproduction.</p>
      <div className="sa-journey-actions"><WorkbenchButton onClick={() => onExport('csv')}>Export CSV</WorkbenchButton><WorkbenchButton onClick={() => onExport('parquet')}>Export Parquet</WorkbenchButton></div>
      <DisclosureRow title={`Report exclusions (${report.exclusions.length})`}><ul className="sa-journey-list">{report.exclusions.length ? report.exclusions.map(([id, reason], index) => <li key={`${id}:${reason}`}>{mode === 'lab' ? <><code>{id}</code> — {reason}</> : `Excluded record ${index + 1} — ${reason}`}</li>) : <li>None reported.</li>}</ul></DisclosureRow>
    </WorkbenchPanel>
    <MainEffectHeatmap data={main} evidence={exportEvidence} />
    <PairwiseInteractionMap data={interactions} evidence={evidence} />
    <PairedStressDifference effects={report.clean_vs_stressed_tax} evidence={evidence} />
    <ReliabilityCostLatencyPareto data={pareto} evidence={evidence} />
    {unknownKProfiles.length > 0 && <WorkbenchPanel title="Attempt consistency HOLD"><p>pass@k is Unknown for {mode === 'lab' ? unknownKProfiles.map((profile) => profile.profile_id).join(', ') : `${unknownKProfiles.length} profile(s)`} because its canonical series ID does not expose a parseable {mode === 'lab' && <code>pass_at_&lt;k&gt;</code>} suffix. No k value was assumed.</p></WorkbenchPanel>}
    <AttemptConsistencyDistribution data={consistency} evidence={evidence} />
    <BudgetForecastActualView data={budget} evidence={evidence} />
  </>
}

function PairedStressDifference({ effects, evidence }: { effects: readonly AnalysisEffectReport[]; evidence: EvidenceMetadata }) {
  const guided = evidence.display === 'guided'
  return <WorkbenchPanel title="Clean versus stressed ordinary-task tax" action={<StatusIndicator tone="info">Paired difference</StatusIndicator>}>
    <p className="sa-analyze-boundary">Each value is the reported stress-minus-clean paired difference, not a clean or stressed absolute. Unknown remains Unknown.</p>
    <WorkbenchTable aria-label="Clean versus stressed paired differences"><thead><tr><th scope="col">Effect</th><th scope="col">Outcome</th><th scope="col">Stress-minus-clean difference</th><th scope="col">Confidence interval</th><th scope="col">Status</th></tr></thead><tbody>{effects.length ? effects.map((effect) => <tr key={effect.effect_id}><td>{effect.effect_id}</td><td>{effect.outcome}</td><td>{effect.estimate === null ? 'Unknown' : effect.estimate.toFixed(2)}</td><td>{effect.confidence_interval[0] === null || effect.confidence_interval[1] === null ? 'Unknown' : `${effect.confidence_interval[0].toFixed(2)} to ${effect.confidence_interval[1].toFixed(2)}`}</td><td>{effect.status}{effect.reason ? ` — ${effect.reason}` : ''}</td></tr>) : <tr><td colSpan={5}>No paired difference values are applicable to this report.</td></tr>}</tbody></WorkbenchTable>
    <DisclosureRow title="Evidence and limitations"><dl className="sa-analyze-evidence"><div><dt>Numerator</dt><dd>{evidence.numerator}</dd></div><div><dt>Denominator</dt><dd>{evidence.denominator}</dd></div><div><dt>Exclusions</dt><dd>{evidence.exclusions.length ? guided ? `${evidence.exclusions.length} excluded record(s); inspect identities in Lab.` : evidence.exclusions.join('; ') : 'None reported'}</dd></div><div><dt>Included attempts</dt><dd>{evidence.includedAttemptIds.length ? guided ? `${evidence.includedAttemptIds.length} persisted attempt(s)` : evidence.includedAttemptIds.join(', ') : 'None'}</dd></div><div><dt>Source digest</dt><dd>{guided ? 'Withheld in Guided; verify through Evidence Room.' : evidence.sourceDigest}</dd></div><div><dt>Analysis digest</dt><dd>{guided ? 'Withheld in Guided; verify through Evidence Room.' : evidence.analysisDigest}</dd></div><div><dt>Claim ceiling</dt><dd>{evidence.claimCeiling}</dd></div></dl></DisclosureRow>
  </WorkbenchPanel>
}
