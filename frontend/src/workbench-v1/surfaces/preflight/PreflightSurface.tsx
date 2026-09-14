import { useCallback, useEffect, useState } from 'react'
import type { ExperimentDetail, PreflightReport } from '../../../api/v1/client'
import { DisclosureRow, SevereFailureBanner, StatusIndicator, WorkbenchButton, WorkbenchPanel, WorkbenchState, WorkbenchTable } from '../../design-system'
import { FIXTURE_LABEL, problemMessage, stringValue, type ArenaV1Client } from '../../journeys/study-design-preflight/types'
import '../../journeys/study-design-preflight/journey.css'

export interface PreflightSurfaceProps {
  client: ArenaV1Client
  mode?: 'guided' | 'lab'
  experimentId: string | null
  projectId?: string
  isFixture?: boolean
  onNavigateToDesign?: () => void
  onProceedToExecute?: () => void
  onPreflightReport?: (report: PreflightReport) => void
  onExperimentIdentity?: (identity: ExperimentDetail['immutable_identity']) => void
}

type State = 'idle' | 'loading' | 'offline' | 'permission' | 'error'

interface DisplayIssue {
  code?: unknown
  endpoint_id?: unknown
  harness_id?: unknown
  message?: unknown
}

function JsonRows({ values, mode }: { values: readonly DisplayIssue[]; mode: 'guided' | 'lab' }) {
  return <ul className="sa-journey-list">{values.length ? values.map((value, index) => <li key={index}><strong>{mode === 'lab' ? stringValue(value.code, stringValue(value.endpoint_id, stringValue(value.harness_id, `Item ${index + 1}`))) : `Declared item ${index + 1}`}</strong>{typeof value.message === 'string' && <> — {value.message}</>}</li>) : <li>None declared.</li>}</ul>
}

export function PreflightSurface({ client, mode = 'lab', experimentId, projectId, isFixture = false, onNavigateToDesign, onProceedToExecute, onPreflightReport, onExperimentIdentity }: PreflightSurfaceProps) {
  const [state, setState] = useState<State>('idle')
  const [message, setMessage] = useState('')
  const [experiment, setExperiment] = useState<ExperimentDetail | null>(null)
  const [report, setReport] = useState<PreflightReport | null>(null)
  const [busy, setBusy] = useState(false)

  const reload = useCallback(async () => {
    if (!experimentId) return
    setState('loading')
    setMessage('')
    try {
      const recovered = await client.experiments.get(experimentId, { projectId })
      setExperiment(recovered)
      onExperimentIdentity?.(recovered.immutable_identity)
      setState('idle')
    } catch (error) {
      const problem = problemMessage(error)
      setState(problem.kind === 'offline' ? 'offline' : problem.kind === 'permission' ? 'permission' : 'error')
      setMessage(problem.message)
    }
  }, [client, experimentId, onExperimentIdentity, projectId])

  useEffect(() => { setReport(null); void reload() }, [reload])

  const freeze = async () => {
    if (!experiment) return
    setBusy(true)
    try {
      const response = await client.experiments.freeze(experiment.experiment_id, { projectId })
      setMessage(response.frozen ? 'The canonical experiment is frozen. Preflight is now available.' : 'Freeze did not return a frozen identity.')
      await reload()
    } catch (error) { setMessage(problemMessage(error).message) } finally { setBusy(false) }
  }

  const preflight = async () => {
    if (!experiment?.immutable_identity.frozen) return
    setBusy(true)
    try {
      const response = await client.experiments.preflight(experiment.experiment_id, { projectId })
      setReport(response)
      onPreflightReport?.(response)
      setMessage(response.verdict === 'PASS' ? 'Preflight passed the local protocol admissibility checks.' : 'Preflight returned HOLD. Resolve every blocker before execution can be requested.')
    } catch (error) {
      const problem = problemMessage(error)
      setMessage(problem.kind === 'hold' ? `Preflight HOLD: ${problem.message}` : problem.message)
    } finally { setBusy(false) }
  }

  if (!experimentId) return <WorkbenchState kind="empty" title="No experiment selected" action={onNavigateToDesign && <WorkbenchButton onClick={onNavigateToDesign}>Go to Design</WorkbenchButton>}>Create an unfrozen experiment in Design, then select it here.</WorkbenchState>
  if (state === 'loading') return <WorkbenchState kind="loading" title="Loading persisted experiment">Recovering experiment identity and freeze state.</WorkbenchState>
  if (state === 'offline') return <WorkbenchState kind="offline" title="Experiment registry unavailable" action={<WorkbenchButton onClick={() => void reload()}>Retry recovery</WorkbenchButton>}>{message}</WorkbenchState>
  if (state === 'permission') return <SevereFailureBanner title="Project context required" action={<WorkbenchButton onClick={() => void reload()}>Retry with project context</WorkbenchButton>}>{message}</SevereFailureBanner>
  if (state === 'error' || !experiment) return <WorkbenchState kind="error" title="Experiment recovery failed" action={<WorkbenchButton onClick={() => void reload()}>Retry recovery</WorkbenchButton>}>{message}</WorkbenchState>

  const frozen = experiment.immutable_identity.frozen
  const approved = experiment.owner_approval === 'approved'
  const hold = report?.verdict === 'HOLD'
  return <section className="sa-journey" aria-labelledby="preflight-heading">
    {isFixture && <p className="sa-journey-fixture">{FIXTURE_LABEL}</p>}
    <WorkbenchPanel title={<span id="preflight-heading">{mode === 'lab' ? `Preflight: ${experiment.experiment_id}` : 'Preflight check'}</span>} action={<StatusIndicator tone={frozen ? 'ready' : 'warning'}>{frozen ? 'Frozen' : 'Unfrozen'}</StatusIndicator>}>
      <div className="sa-journey-form">
        <p className="sa-journey-copy">Owner approval: <strong>{experiment.owner_approval}</strong>. Freeze binds the canonical definition and StudyPack hash; it does not start a provider or execution.</p>
        <div className="sa-journey-actions">
          <WorkbenchButton onClick={() => void freeze()} disabled={busy || frozen || !approved}>{frozen ? 'Experiment frozen' : 'Freeze experiment'}</WorkbenchButton>
          <WorkbenchButton tone="primary" onClick={() => void preflight()} disabled={busy || !frozen}>Preflight experiment</WorkbenchButton>
        </div>
        {!approved && <div className="sa-journey-callout"><p>{mode === 'lab' ? <>Freeze is unavailable until the persisted experiment has <code>owner_approval: "approved"</code>.</> : 'Freeze is unavailable until the persisted owner approval is approved.'}</p></div>}
        {message && <p className="sa-journey-status" data-tone={hold ? 'hold' : undefined} role="status">{message}</p>}
      </div>
    </WorkbenchPanel>

    {report && <>
      {hold && <SevereFailureBanner title="Execution remains unavailable" action={<WorkbenchButton disabled>Execution unavailable on HOLD</WorkbenchButton>}>No provider request has been emitted. Resolve the listed preflight blockers and run preflight again.</SevereFailureBanner>}
      {report.verdict === 'PASS' && <div className="sa-journey-callout"><p>PASS is local protocol admissibility only. It does not establish live benchmark evidence, provider execution, deployment approval, or an empirical claim.</p>{onProceedToExecute && <div className="sa-journey-actions"><WorkbenchButton onClick={onProceedToExecute}>Continue to Run Cockpit</WorkbenchButton></div>}</div>}
      <WorkbenchPanel title="Readiness verdict" action={<StatusIndicator tone={report.verdict === 'PASS' ? 'ready' : 'warning'}>{report.verdict}</StatusIndicator>}>
        <div className="sa-journey-grid"><div><p className="sa-journey-copy">Expected attempts: <strong>{report.expected_attempts}</strong></p><p className="sa-journey-copy">Design expansion: <strong>{report.design_expansion_count}</strong></p><p className="sa-journey-copy">Provider execution started: <strong>{String(report.provider_execution_started)}</strong></p></div><div><p className="sa-journey-copy">Claim ceiling: {report.claim_ceiling}</p><p className="sa-journey-copy">Authority ceiling: {report.authority_ceiling}</p></div></div>
      </WorkbenchPanel>
      <WorkbenchPanel title={`Blockers (${report.blockers.length})`} tone={hold ? 'critical' : 'default'}><JsonRows values={report.blockers} mode={mode} /></WorkbenchPanel>
      <WorkbenchPanel title="Deterministic readiness checks"><div className="sa-table-wrap"><WorkbenchTable><thead><tr><th scope="col">Task family</th><th scope="col">Deterministic weight</th></tr></thead><tbody>{Object.entries(report.study_pack_readiness.task_family_deterministic_weights).map(([family, weight], index) => <tr key={family}><td>{mode === 'lab' ? family : `Task family ${index + 1}`}</td><td>{weight}</td></tr>)}</tbody></WorkbenchTable></div><DisclosureRow title={`Registry readiness issues (${report.study_pack_readiness.issues.length})`}><JsonRows values={report.study_pack_readiness.issues} mode={mode} /></DisclosureRow></WorkbenchPanel>
      <WorkbenchPanel title="Factor manipulation fidelity"><div className="sa-journey-grid"><div><p className="sa-journey-copy">Varied factors: {mode === 'lab' ? report.manipulation_checks.varied_factor_ids.join(', ') || 'None' : `${report.manipulation_checks.varied_factor_ids.length} declared`}</p><p className="sa-journey-copy">Declared checks: {mode === 'lab' ? report.manipulation_checks.declared_check_factor_ids.join(', ') || 'None' : `${report.manipulation_checks.declared_check_factor_ids.length} declared`}</p><p className="sa-journey-copy">Valid: {String(report.manipulation_checks.valid)}</p></div><div><p className="sa-journey-copy">Missing factors: {mode === 'lab' ? report.manipulation_checks.missing_factor_ids.join(', ') || 'None' : report.manipulation_checks.missing_factor_ids.length ? `${report.manipulation_checks.missing_factor_ids.length} missing` : 'None'}</p><JsonRows values={report.manipulation_checks.missing_required_checks} mode={mode} /></div></div></WorkbenchPanel>
      <WorkbenchPanel title="Budget, harnesses, and endpoint pins"><div className="sa-journey-grid"><div><h3 className="sa-panel-title">Budget</h3>{mode === 'lab' ? <pre className="sa-journey-compact">{JSON.stringify(report.budget, null, 2)}</pre> : <p className="sa-journey-copy">A preflight-bound budget is available for execution review. Lab exposes the canonical budget object.</p>}</div><div><h3 className="sa-panel-title">Endpoint pins</h3><JsonRows values={report.endpoint_pins} mode={mode} /></div></div><DisclosureRow title="Harnesses"><JsonRows values={report.harnesses} mode={mode} /></DisclosureRow><DisclosureRow title="Required scenario checks"><JsonRows values={report.manipulation_checks.required_scenario_checks} mode={mode} /></DisclosureRow></WorkbenchPanel>
    </>}
  </section>
}
