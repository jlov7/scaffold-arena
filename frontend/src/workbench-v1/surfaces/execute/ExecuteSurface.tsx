import { type ReactNode, useMemo, useRef, useState } from 'react'
import type { PreflightReport } from '../../../api/v1/client'
import { DisclosureRow, SevereFailureBanner, StatusIndicator, WorkbenchButton, WorkbenchPanel, WorkbenchState, WorkbenchTable } from '../../design-system'
import { type ArenaV1Client } from '../../journeys/study-design-preflight/types'
import { EMPTY_PROVENANCE, formatCost, parseProvenance } from '../../journeys/execution-control/codec'
import { useExecutionControl } from '../../journeys/execution-control/useExecutionControl'
import type { ExecutionMode } from '../../journeys/execution-control/types'
import '../../journeys/execution-control/execution-control.css'

export interface ExecuteSurfaceProps {
  client: ArenaV1Client
  /** Only pass the persisted ID of the selected frozen experiment. */
  frozenExperimentId: string | null
  /** The latest real report is caller-owned; this surface never runs preflight itself. */
  preflightReport: PreflightReport | null
  mode: ExecutionMode
  requestedExecutionId?: string | null
  isBundledOfflineDemo?: boolean
  projectId?: string
  onExecutionSelected?: (executionId: string) => void
  onNavigateToAnalyze?: (executionId: string) => void
  onNavigateToPreflight?: () => void
  onSwitchToLab?: () => void
}

function tone(status: string): 'ready' | 'info' | 'warning' | 'failure' {
  if (/completed|ready/i.test(status)) return 'ready'
  if (/failed|cancelled|error/i.test(status)) return 'failure'
  if (/hold|incomplete|timed/i.test(status)) return 'warning'
  return 'info'
}

function readable(value: string | null | undefined): string { return value && value.length > 0 ? value : 'UNKNOWN' }

function logicalEventKey(event: { event: string; data: Record<string, unknown>; cursor: string }): string {
  return typeof event.data.event_id === 'string' ? event.data.event_id : `${event.event}:${event.cursor}`
}

function idempotencyKey(): string {
  return globalThis.crypto?.randomUUID?.() ?? `execution-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function recordStateSummary(items: readonly { status: string }[], label: string): string {
  const counts = new Map<string, number>()
  for (const item of items) {
    if (/failed|timed_out|incomplete|cancelled/i.test(item.status)) counts.set(item.status, (counts.get(item.status) ?? 0) + 1)
  }
  if (counts.size === 0) return `No failed, timed out, incomplete, or cancelled ${label} in the loaded records.`
  return [...counts].map(([status, count]) => `${count} ${status} ${label}${count === 1 ? '' : 's'}`).join('; ')
}

export function ExecuteSurface({ client, frozenExperimentId, preflightReport, mode, requestedExecutionId, isBundledOfflineDemo = false, projectId, onExecutionSelected, onNavigateToAnalyze, onNavigateToPreflight, onSwitchToLab }: ExecuteSurfaceProps) {
  const [labDraft, setLabDraft] = useState(() => JSON.stringify(EMPTY_PROVENANCE, null, 2))
  const [validationErrors, setValidationErrors] = useState<string[]>([])
  const [confirmingCancel, setConfirmingCancel] = useState(false)
  const validationSummary = useRef<HTMLDivElement>(null)
  const control = useExecutionControl({ client, projectId, frozenExperimentId, preflightReport, requestedExecutionId, onExecutionSelected })
  const canCreate = Boolean(frozenExperimentId && preflightReport?.verdict === 'PASS')
  const selectedStatus = control.selected?.status ?? ''
  const canCancel = Boolean(control.selected && !/completed|failed|cancelled/i.test(selectedStatus))
  const canResume = Boolean(!isBundledOfflineDemo && control.selected && /failed|timed_out|cancelled|incomplete/i.test(selectedStatus))
  const executionState = control.selected?.status ?? (control.executions.length > 0 ? 'UNKNOWN' : 'Not started')
  const loadedAttemptAttention = control.selected ? recordStateSummary(control.selected.attempts, 'attempt') : null
  const loadedJobAttention = control.selected ? recordStateSummary(control.selected.jobs, 'job') : null
  const hasLoadedRecordAttention = Boolean(control.selected && /\d (failed|timed_out|incomplete|cancelled)/.test(`${loadedAttemptAttention}; ${loadedJobAttention}`))
  const visibleEvents = useMemo(() => {
    const seen = new Set<string>()
    return control.events.filter(({ event }) => {
      const key = logicalEventKey(event)
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
  }, [control.events])

  const detailSection = (title: string, children: ReactNode, log = false) => mode === 'guided'
    ? <DisclosureRow title={`${title} — ${log ? 'show log' : 'show records'}`}>{children}</DisclosureRow>
    : <WorkbenchPanel title={title}>{children}</WorkbenchPanel>

  const submit = async () => {
    if (mode === 'guided') {
      setValidationErrors(['Guided mode cannot manufacture execution provenance. Configure a capture integration that persists the observed immutable record, then recover it here.'])
      requestAnimationFrame(() => validationSummary.current?.focus())
      return
    }
    const result = parseProvenance(labDraft)
    if (!canCreate) {
      const reason = !frozenExperimentId ? 'Select a persisted frozen experiment before requesting execution.' : 'Execution is HOLD until the latest real PreflightReport verdict is PASS.'
      setValidationErrors([reason]); requestAnimationFrame(() => validationSummary.current?.focus()); return
    }
    if (!result.provenance) { setValidationErrors(result.errors); requestAnimationFrame(() => validationSummary.current?.focus()); return }
    setValidationErrors([])
    await control.create(result.provenance, idempotencyKey())
  }

  if (!frozenExperimentId) return <WorkbenchState kind="empty" title="Select a frozen experiment">Choose a persisted frozen experiment in Design, then load its latest real preflight report. Execution cannot infer either from browser state.</WorkbenchState>

  return <section className="sa-execute" aria-labelledby="execute-heading">
    <WorkbenchPanel title={<span id="execute-heading">Run Cockpit</span>} action={<div className="sa-execute-summary-action"><StatusIndicator tone={canCreate ? 'ready' : 'warning'}>{canCreate ? 'Preflight PASS' : 'Execution HOLD'}</StatusIndicator>{/completed/i.test(executionState) && onNavigateToAnalyze && control.selected && <WorkbenchButton tone="primary" onClick={() => onNavigateToAnalyze(control.selected!.execution_id)}>Analyze selected execution</WorkbenchButton>}</div>}>
      <div className="sa-execute-overview">
        <div className="sa-execute-overview-source"><span className="sa-region-label">Source</span><strong>{isBundledOfflineDemo ? 'Synthetic fixture — not benchmark evidence.' : mode === 'lab' ? 'Observed source required' : 'Selected frozen comparison'}</strong></div>
        <div><span className="sa-region-label">Preflight verdict</span><strong>{preflightReport?.verdict ?? 'MISSING'}</strong></div>
        <div><span className="sa-region-label">Expected attempts</span><strong>{preflightReport?.expected_attempts ?? 'UNKNOWN'}</strong></div>
        <div><span className="sa-region-label">Budget ceiling</span><strong>{formatCost(preflightReport?.budget?.max_total_cost_usd ?? preflightReport?.budget?.max_cost_usd)}</strong></div>
        <div><span className="sa-region-label">Execution state</span><strong>{executionState}</strong></div>
      </div>
      <p className="sa-execute-boundary">A queued or completed fixture run is a durable protocol record, not provider or benchmark evidence. Missing usage and cost remain UNKNOWN.</p>
      {!canCreate && <SevereFailureBanner title="Execution is blocked" action={onNavigateToPreflight ? <WorkbenchButton onClick={onNavigateToPreflight}>Run or recover preflight</WorkbenchButton> : <a className="sa-execute-link" href="/workbench/preflight">Run or recover preflight</a>}>{preflightReport?.verdict === 'HOLD' ? 'Resolve the stored preflight blockers, rerun preflight in its surface, then return with a real PASS report.' : 'No current PreflightReport was recovered for this frozen experiment. Run or recover preflight before requesting execution; this surface will not infer a PASS or submit preflight automatically.'}</SevereFailureBanner>}
      {preflightReport?.blockers.length ? <DisclosureRow title={`Preflight blockers (${preflightReport.blockers.length})`}><ul className="sa-execute-list">{preflightReport.blockers.map((blocker, index) => <li key={`${blocker.code}-${index}`}><strong>{blocker.code}</strong> — {blocker.message}</li>)}</ul></DisclosureRow> : null}
    </WorkbenchPanel>

    <WorkbenchPanel title={mode === 'lab' ? 'Execution provenance' : 'Observed execution capture'} action={<StatusIndicator tone="warning">Required immutable evidence</StatusIndicator>}>
      {mode === 'guided' && isBundledOfflineDemo ? <>
        <p className="sa-journey-copy">Run the exact bundled synthetic fixture with server-captured local provenance. This produces durable fixture records only; it does not invoke a provider or establish benchmark evidence.</p>
        <div className="sa-journey-actions"><WorkbenchButton tone={/completed/i.test(executionState) ? 'secondary' : 'primary'} disabled={!canCreate || control.busy} onClick={() => void control.createOfflineDemo()}>Run bundled offline demo</WorkbenchButton></div>
        {!canCreate && <p className="sa-journey-note">Run preflight and resolve any HOLD before starting the bundled fixture.</p>}
      </> : mode === 'guided' ? <>
        <p className="sa-journey-copy">Guided mode automatically recovers persisted execution history. It never asks you to type or construct provenance, digests, runtime identities, usage, or cost records.</p>
        <SevereFailureBanner title="Execution remains HOLD until capture is configured" action={onSwitchToLab && <WorkbenchButton onClick={onSwitchToLab}>Switch to Lab</WorkbenchButton>}>No observed execution capture is available. No execution request will be emitted, even after a preflight PASS. Configure capture through the local operator workflow, then use Lab to submit its canonical record. This browser does not construct provenance.</SevereFailureBanner>
      </> : <>
        <p className="sa-journey-copy">Supply observed provenance from your configured environment. Blank fields stay blank; this interface does not generate revisions, images, digests, endpoints, usage, or costs.</p>
        <div className="sa-journey-form"><label className="sa-journey-field">Canonical ExecutionProvenance JSON<textarea value={labDraft} onChange={(event) => setLabDraft(event.target.value)} spellCheck={false} /></label><p className="sa-journey-note">Lab sends the same validated canonical object through the same durable execution request path. Extra fields, missing source references, invalid digests, and naive timestamps are rejected before any request.</p></div>
        <div className="sa-journey-actions"><WorkbenchButton tone="primary" disabled={!canCreate || control.busy} onClick={() => void submit()}>Enqueue durable execution</WorkbenchButton></div>
      </>}
      {validationErrors.length > 0 && <div ref={validationSummary} className="sa-journey-summary" role="alert" tabIndex={-1}><strong>Resolve provenance before enqueueing</strong><ul>{validationErrors.map((error, index) => <li key={index}>{error}</li>)}</ul></div>}
      {control.message && <p className="sa-journey-status" role="status">{control.message}</p>}
    </WorkbenchPanel>

    {control.state === 'loading' && control.executions.length === 0 ? <WorkbenchState kind="loading" title="Recovering durable executions">Loading list and detail records for {frozenExperimentId}.</WorkbenchState> : null}
    {control.state === 'offline' ? <WorkbenchState kind="offline" title="Execution recovery is offline" action={<WorkbenchButton onClick={() => void control.load()}>Retry durable recovery</WorkbenchButton>}>{control.message || 'Reconnect, then reload durable execution history by stable ID.'}</WorkbenchState> : null}
    {control.state === 'permission' ? <SevereFailureBanner title="Project context required" action={<WorkbenchButton onClick={() => void control.load()}>Retry with project context</WorkbenchButton>}>{control.message || 'Choose a project with access to this experiment.'}</SevereFailureBanner> : null}
    {control.state === 'error' ? <WorkbenchState kind="error" title="Execution recovery failed" action={<WorkbenchButton onClick={() => void control.load()}>Retry durable recovery</WorkbenchButton>}>{control.message || 'The latest request could not be completed.'}</WorkbenchState> : null}

    {control.state === 'empty' ? <WorkbenchState kind="empty" title="No durable executions yet">A PASS preflight and valid observed provenance are required before enqueueing the first durable execution.</WorkbenchState> : null}
    {control.executions.length > 0 && <WorkbenchPanel title="Durable execution history" action={<div className="sa-journey-actions"><WorkbenchButton onClick={() => void control.load()}>Reload</WorkbenchButton>{control.nextOffset !== null && <WorkbenchButton onClick={() => void control.loadMore()}>Load more</WorkbenchButton>}</div>}>
      <WorkbenchTable><thead><tr><th scope="col">{mode === 'lab' ? 'Execution ID' : 'Run'}</th><th scope="col">Status</th><th scope="col">Attempts</th><th scope="col">Jobs</th><th scope="col">Created</th><th scope="col">Select</th></tr></thead><tbody>{control.executions.map((execution, index) => { const selectedDetail = control.selected?.execution_id === execution.execution_id ? control.selected : null; return <tr key={execution.execution_id} aria-selected={Boolean(selectedDetail)}><td>{mode === 'lab' ? <code>{execution.execution_id}</code> : `Run ${index + 1}`}</td><td><StatusIndicator tone={tone(execution.status)}>{execution.status}</StatusIndicator></td><td>{selectedDetail?.counts.attempts ?? 'UNKNOWN'}</td><td>{selectedDetail?.counts.jobs ?? 'UNKNOWN'}</td><td>{readable(execution.created_at)}</td><td><WorkbenchButton onClick={() => void control.choose(execution.execution_id)} disabled={Boolean(selectedDetail)}>Select</WorkbenchButton></td></tr> })}</tbody></WorkbenchTable>
    </WorkbenchPanel>}

    {control.selected && <>
      <WorkbenchPanel title="Execution control" action={<StatusIndicator tone={tone(control.selected.status)}>{control.selected.status}</StatusIndicator>}>
        <div className="sa-execute-control-grid"><div><span className="sa-region-label">Worker state</span><strong>UNKNOWN (not supplied)</strong></div><div><span className="sa-region-label">Started</span><strong>{readable(control.selected.started_at)}</strong></div><div><span className="sa-region-label">Completed</span><strong>{readable(control.selected.completed_at)}</strong></div><div><span className="sa-region-label">Observed usage</span><strong>UNKNOWN</strong></div><div><span className="sa-region-label">Observed cost</span><strong>UNKNOWN</strong></div></div>
        <p className="sa-execute-boundary">Usage and cost are UNKNOWN because the execution detail endpoint does not provide observed provider usage or a price quote.</p>
        {!/completed|failed|cancelled/i.test(control.selected.status) && <p className="sa-execute-boundary">This execution is nonterminal and therefore partial durable evidence. Continue observing the persisted event stream or reload recovery state.</p>}
        {confirmingCancel && canCancel ? <div className="sa-execute-confirm" role="alert"><strong>Confirm cancellation</strong><span>This requests cancellation for nonterminal durable jobs. It does not establish provider state.</span><WorkbenchButton tone="danger" disabled={control.busy} onClick={() => { setConfirmingCancel(false); void control.cancel() }}>Confirm cancel</WorkbenchButton><WorkbenchButton disabled={control.busy} onClick={() => setConfirmingCancel(false)}>Keep execution</WorkbenchButton></div> : <div className="sa-journey-actions">{canCancel && <WorkbenchButton tone="danger" disabled={control.busy} onClick={() => setConfirmingCancel(true)}>Cancel execution</WorkbenchButton>}{canResume && <WorkbenchButton disabled={control.busy} onClick={() => void control.resume()}>Resume execution</WorkbenchButton>}{isBundledOfflineDemo && !/completed/i.test(control.selected.status) && <WorkbenchButton disabled={control.busy} onClick={() => void control.createOfflineDemo()}>{/failed|cancelled/i.test(control.selected.status) ? 'Start a new bundled offline demo' : 'Resume bundled offline demo'}</WorkbenchButton>}{!canCancel && !canResume && !isBundledOfflineDemo && (!/completed/i.test(control.selected.status) || !onNavigateToAnalyze) && <p className="sa-journey-note">No control action is available for this terminal execution state.</p>}</div>}
      </WorkbenchPanel>

      <WorkbenchPanel title="Loaded execution records" action={<StatusIndicator tone={hasLoadedRecordAttention ? 'failure' : 'info'}>{hasLoadedRecordAttention ? 'Needs attention' : 'Scope only'}</StatusIndicator>}>
        <p className="sa-execute-boundary"><strong>{loadedAttemptAttention}</strong> <strong>{loadedJobAttention}</strong></p>
        <p className="sa-execute-boundary">This covers {control.selected.attempts.length} loaded attempt record(s) and {control.selected.jobs.length} loaded job record(s). The execution detail does not include evaluator grades or a severe-failure aggregate, so this summary cannot establish evaluator success or the absence of severe failures.</p>
      </WorkbenchPanel>

      {detailSection(`Attempts (${control.selected.counts.attempts})`, <>
        {control.selected.attempts.length === 0 ? <WorkbenchState kind="empty" title="No attempt records">The durable execution has no persisted attempts yet. Reload after a worker records one.</WorkbenchState> : <WorkbenchTable><thead><tr><th scope="col">Attempt</th><th scope="col">Scenario</th><th scope="col">Ordinal</th><th scope="col">State</th><th scope="col">Inspect</th></tr></thead><tbody>{control.selected.attempts.map((item, index) => <tr key={item.attempt_id}><td>{mode === 'lab' ? <code>{item.attempt_id}</code> : `Attempt ${index + 1}`}</td><td>{mode === 'lab' ? item.scenario_id : `Scenario ${index + 1}`}</td><td>{item.ordinal}</td><td><StatusIndicator tone={tone(item.status)}>{item.status}</StatusIndicator></td><td><WorkbenchButton onClick={() => void control.inspectAttempt(item.attempt_id)}>Details</WorkbenchButton></td></tr>)}</tbody></WorkbenchTable>}
      </>)}

      {detailSection(`Durable jobs (${control.selected.counts.jobs})`, <>
        {control.selected.jobs.length === 0 ? <WorkbenchState kind="empty" title="No durable jobs">The selected execution has no persisted job records yet. Reload recovery state.</WorkbenchState> : <WorkbenchTable><thead><tr><th scope="col">Job</th><th scope="col">Attempt</th><th scope="col">Kind</th><th scope="col">State</th><th scope="col">Attempts</th><th scope="col">Cancel requested</th></tr></thead><tbody>{control.selected.jobs.map((job, index) => <tr key={job.job_id}><td>{mode === 'lab' ? <code>{job.job_id}</code> : `Job ${index + 1}`}</td><td>{mode === 'lab' ? job.attempt_id ?? 'UNKNOWN' : job.attempt_id ? 'Linked persisted attempt' : 'UNKNOWN'}</td><td>{job.kind}</td><td><StatusIndicator tone={tone(job.status)}>{job.status}</StatusIndicator></td><td>{job.attempt_count}</td><td>{readable(job.cancel_requested_at)}</td></tr>)}</tbody></WorkbenchTable>}
      </>)}

      {control.attempt && detailSection(mode === 'lab' ? `Attempt ${control.attempt.attempt_id}` : 'Selected persisted attempt', <>{mode === 'lab' ? <><div className="sa-execute-json" tabIndex={0} aria-label="Attempt request and result"><pre>{JSON.stringify({ status: control.attempt.status, request: control.attempt.request, result: control.attempt.result }, null, 2)}</pre></div><div className="sa-journey-actions"><WorkbenchButton onClick={() => void control.inspectTrace(control.attempt!.attempt_id)}>Load trace</WorkbenchButton></div></> : <><p className="sa-journey-copy">Status: <strong>{control.attempt.status}</strong>. Inspect the persisted trace to diagnose the outcome; raw request and result objects remain in Lab mode.</p><WorkbenchButton onClick={() => void control.inspectTrace(control.attempt!.attempt_id)}>Load trace</WorkbenchButton></>}</>)}
      {control.trace && detailSection(`Trace (${control.trace.events.length} persisted events)`, <div className="sa-execute-trace" tabIndex={0} aria-label="Persisted attempt trace"><WorkbenchTable><thead><tr><th scope="col">Sequence</th><th scope="col">Type</th><th scope="col">Created</th>{mode === 'lab' && <th scope="col">Payload</th>}</tr></thead><tbody>{control.trace.events.map((event) => <tr key={event.event_id}><td>{event.sequence}</td><td>{event.event_type}</td><td>{event.created_at}</td>{mode === 'lab' && <td><code>{JSON.stringify(event.payload)}</code></td>}</tr>)}</tbody></WorkbenchTable></div>)}

      {detailSection(`Live durable events (${visibleEvents.length})`, <>
        <p className="sa-execute-live" role="status" aria-live="polite">{visibleEvents.length === 0 ? 'Waiting for persisted execution events.' : `${visibleEvents.length} unique persisted event${visibleEvents.length === 1 ? '' : 's'} received.`}</p>
        <div className="sa-execute-events" tabIndex={0} aria-label="Live execution event log">{visibleEvents.length === 0 ? <p className="sa-journey-note">No events are currently available. A nonterminal execution remains partial evidence.</p> : <ol>{visibleEvents.map(({ event }, index) => <li key={logicalEventKey(event)}>{mode === 'lab' && <code>{event.cursor}</code>} <strong>{event.event}</strong> {mode === 'lab' ? <span>{JSON.stringify(event.data)}</span> : <span>{`Persisted event ${index + 1}`}</span>}</li>)}</ol>}</div>
      </>, true)}
    </>}
  </section>
}
