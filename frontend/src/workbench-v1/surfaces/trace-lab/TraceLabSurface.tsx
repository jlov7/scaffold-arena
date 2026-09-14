import { useCallback, useEffect, useMemo, useState } from 'react'

import { ApiProblem, createArenaV1, type ExecutionDetail, type JsonObject, type TraceAnalysisRequest } from '../../../api/v1/client'
import { DisclosureRow, SevereFailureBanner, StatusIndicator, WorkbenchButton, WorkbenchPanel, WorkbenchState, WorkbenchTable } from '../../design-system'
import { AlignedTraceTimeline, StateBeforeAfterComparison, type AlignedTraceEvent, type EvidenceMetadata } from '../../visualizations'

import './trace-lab.css'

type ArenaV1Client = ReturnType<typeof createArenaV1>
type State = 'idle' | 'loading' | 'empty' | 'offline' | 'permission' | 'hold' | 'error'
type AlignmentStatus = 'MATCH' | 'CONTENT_DIFFERENCE' | 'LEFT_ONLY' | 'RIGHT_ONLY'

interface TraceAlignmentEvent extends JsonObject {
  event_id: string
  ordinal: number
  observation_digest: string | null
  relative_ms: number | null
  evidence_ref: string | null
}

interface TraceAlignmentRow extends JsonObject {
  position: number
  status: AlignmentStatus
  anchor: string
  left: TraceAlignmentEvent | null
  right: TraceAlignmentEvent | null
}

interface TraceLabResponse extends JsonObject {
  analysis_digest: string
  analysis_version: string
  mode: string
  causal_label: 'DIAGNOSTIC_ONLY'
  claim_ceiling: string
  attempt_links: { left: { attempt_id: string; trace_url: string }; right: { attempt_id: string; trace_url: string } }
  source_event_ids: { left: string[]; right: string[] }
  alignment: {
    source_digest: string
    source_digests: { left: string; right: string }
    matched_anchors: number
    exact_observation_matches: number
    content_differences: number
    left_only: number
    right_only: number
    clock_skew_tolerant: boolean
    rows: TraceAlignmentRow[]
  }
  first_meaningful_divergence: {
    found: boolean
    label: 'DIAGNOSTIC_ONLY'
    reason: string
    confidence: number | null
    alignment_position: number | null
    left_event_id: string | null
    right_event_id: string | null
    evidence_refs: string[]
    state_before: { left: JsonObject | null; right: JsonObject | null }
    state_after: { left: JsonObject | null; right: JsonObject | null }
    state_ref_diff: { left: Record<string, { before: string | null; after: string | null }>; right: Record<string, { before: string | null; after: string | null }> }
  }
  coverage: { numerator: number; denominator: number; exclusions: string[] }
}

export interface TraceLabSurfaceProps {
  client: ArenaV1Client
  mode?: 'guided' | 'lab'
  projectId?: string
  executionId?: string | null
  initialLeftAttemptId?: string | null
  initialRightAttemptId?: string | null
  onAttemptPairSelected?: (leftAttemptId: string, rightAttemptId: string) => void
}

function isTraceResponse(value: JsonObject): value is TraceLabResponse {
  if (typeof value.analysis_digest !== 'string' || typeof value.analysis_version !== 'string' || value.causal_label !== 'DIAGNOSTIC_ONLY' || typeof value.claim_ceiling !== 'string') return false
  const alignment = value.alignment
  return Boolean(
    alignment
    && typeof alignment === 'object'
    && !Array.isArray(alignment)
    && typeof alignment.source_digest === 'string'
    && Array.isArray(alignment.rows),
  )
}

function message(error: unknown): { state: Extract<State, 'offline' | 'permission' | 'hold' | 'error'>; text: string } {
  if (error instanceof ApiProblem) {
    if (error.isHold) return { state: 'hold', text: error.message }
    if (error.status === 401 || error.status === 403 || error.code === 'project_context_required' || error.code === 'unknown_project') return { state: 'permission', text: error.message }
    if (error.status >= 500) return { state: 'offline', text: error.message }
    return { state: 'error', text: error.message }
  }
  return { state: 'offline', text: error instanceof Error ? error.message : 'Trace Lab could not be reached.' }
}

function stateChanges(response: TraceLabResponse) {
  const result: Array<{ field: string; before: string | null; after: string | null; status: 'changed' | 'unchanged' | 'unknown' }> = []
  for (const side of ['left', 'right'] as const) for (const [field, change] of Object.entries(response.first_meaningful_divergence.state_ref_diff[side] ?? {})) {
    result.push({ field: `${side}.${field}`, before: change.before, after: change.after, status: change.before === null || change.after === null ? 'unknown' : change.before === change.after ? 'unchanged' : 'changed' })
  }
  return result
}

function traceEvidence(response: TraceLabResponse, mode: 'guided' | 'lab'): EvidenceMetadata {
  return {
    numerator: String(response.coverage.numerator),
    denominator: String(response.coverage.denominator),
    exclusions: response.coverage.exclusions,
    includedAttemptIds: [response.attempt_links.left.attempt_id, response.attempt_links.right.attempt_id],
    sourceDigest: response.alignment.source_digest,
    analysisDigest: response.analysis_digest,
    caveat: 'Observed persisted-trace diagnostic only. Matching hashes show byte-identical recorded observations; they do not prove correctness or cause.',
    claimCeiling: response.claim_ceiling,
    display: mode,
  }
}

const alignmentKind: Record<AlignmentStatus, AlignedTraceEvent['alignment']> = {
  MATCH: 'aligned',
  CONTENT_DIFFERENCE: 'diverged',
  LEFT_ONLY: 'left_only',
  RIGHT_ONLY: 'right_only',
}

function eventLabel(anchor: string, event: TraceAlignmentEvent | null, mode: 'guided' | 'lab'): string | null {
  if (!event) return null
  if (mode === 'guided') return `${anchor} · persisted observation`
  const digest = event.observation_digest ? ` · sha256:${event.observation_digest.slice(0, 12)}` : ' · digest unknown'
  const timing = event.relative_ms === null ? '' : ` · +${event.relative_ms.toFixed(0)} ms`
  return `${anchor} · ${event.event_id}${digest}${timing}`
}

function timelineRows(response: TraceLabResponse, mode: 'guided' | 'lab'): AlignedTraceEvent[] {
  return response.alignment.rows.map((row) => ({
    position: row.position,
    left: eventLabel(row.anchor, row.left, mode),
    right: eventLabel(row.anchor, row.right, mode),
    alignment: alignmentKind[row.status],
  }))
}

export function TraceLabSurface({ client, mode = 'lab', projectId, executionId, initialLeftAttemptId, initialRightAttemptId, onAttemptPairSelected }: TraceLabSurfaceProps) {
  const [execution, setExecution] = useState<ExecutionDetail | null>(null)
  const [state, setState] = useState<State>(executionId ? 'loading' : 'idle')
  const [notice, setNotice] = useState('')
  const [left, setLeft] = useState(initialLeftAttemptId ?? '')
  const [right, setRight] = useState(initialRightAttemptId ?? '')
  const [partial, setPartial] = useState(false)
  const [result, setResult] = useState<TraceLabResponse | null>(null)

  useEffect(() => { setLeft(initialLeftAttemptId ?? ''); setRight(initialRightAttemptId ?? '') }, [initialLeftAttemptId, initialRightAttemptId])

  const loadExecution = useCallback(async () => {
    if (!executionId) return
    setState('loading')
    try { const durable = await client.executions.get(executionId, { projectId }); setExecution(durable); setState(durable.attempts.length ? 'idle' : 'empty'); setNotice('') }
    catch (error) { const next = message(error); setState(next.state); setNotice(next.text) }
  }, [client, executionId, projectId])
  useEffect(() => { void loadExecution() }, [loadExecution])

  const attemptIds = useMemo(() => execution?.attempts.map((attempt) => attempt.attempt_id) ?? [], [execution])
  const compare = async () => {
    if (!left || !right) { setState('empty'); setNotice('Select or enter two persisted attempt IDs.'); return }
    if (left === right) { setState('hold'); setNotice('Trace comparison requires two distinct persisted attempts.'); return }
    onAttemptPairSelected?.(left, right)
    const payload: TraceAnalysisRequest = { left_attempt_id: left, right_attempt_id: right, ...(partial ? { diagnostic_partial_mode: true } : {}) }
    setState('loading'); setNotice('Comparing persisted trace references; no trace events or outcomes are sent by this browser.'); setResult(null)
    try {
      const raw = await client.traceLab.analyze(payload, { projectId })
      if (!isTraceResponse(raw)) throw new TypeError('Malformed trace diagnostic response.')
      setResult(raw); setState('idle'); setNotice('')
    } catch (error) { const next = message(error); setState(next.state); setNotice(next.text) }
  }
  const chooseLeft = (attemptId: string) => { setLeft(attemptId); onAttemptPairSelected?.(attemptId, right) }
  const chooseRight = (attemptId: string) => { setRight(attemptId); onAttemptPairSelected?.(left, attemptId) }

  if (state === 'offline') return <WorkbenchState kind="offline" title="Trace Lab unavailable" action={<WorkbenchButton onClick={() => void (executionId ? loadExecution() : compare())}>Retry</WorkbenchButton>}>{notice || 'Reconnect to retrieve durable trace diagnostics.'}</WorkbenchState>
  if (state === 'permission') return <SevereFailureBanner title="Project context required" action={<WorkbenchButton onClick={() => void (executionId ? loadExecution() : compare())}>Retry with project context</WorkbenchButton>}>{notice}</SevereFailureBanner>

  const evidence = result ? traceEvidence(result, mode) : null
  const changes = result ? stateChanges(result) : []
  const alignedEvents = result ? timelineRows(result, mode) : []
  return <section className="sa-trace-lab" aria-labelledby="trace-lab-heading">
    <WorkbenchPanel title={<span id="trace-lab-heading">Trace Lab</span>} action={<StatusIndicator tone="info">DIAGNOSTIC_ONLY</StatusIndicator>}>
      <p className="sa-trace-lab-boundary">Compare two persisted attempts. Alignment is diagnostic only: it does not establish causality or reconstruct missing events.</p>
      {executionId && <p className="sa-trace-lab-context">{mode === 'lab' ? <>Execution <code>{executionId}</code></> : 'Selected durable run'} — persisted attempts are loaded from durable execution detail.</p>}
      {state === 'loading' && <p role="status">{notice || 'Loading persisted trace references…'}</p>}
      {state === 'hold' && <SevereFailureBanner title="Trace diagnostic HOLD">{notice}</SevereFailureBanner>}
      {state === 'error' && <WorkbenchState kind="error" title="Trace diagnostic failed" action={<WorkbenchButton onClick={() => void compare()}>Retry comparison</WorkbenchButton>}>{notice}</WorkbenchState>}
      {state === 'empty' && <WorkbenchState kind="empty" title="No attempt pair selected">{notice || 'This execution has no persisted attempt pair yet. Return after durable attempts are recorded.'}</WorkbenchState>}
      {attemptIds.length > 0 && <div className="sa-trace-lab-attempts"><strong>Persisted attempts</strong><WorkbenchTable><thead><tr><th scope="col">Attempt</th><th scope="col">Status</th><th scope="col">Left</th><th scope="col">Right</th></tr></thead><tbody>{execution!.attempts.map((attempt, index) => <tr key={attempt.attempt_id}><td>{mode === 'lab' ? <code>{attempt.attempt_id}</code> : `Persisted attempt ${index + 1}`}</td><td>{attempt.status}</td><td><WorkbenchButton onClick={() => chooseLeft(attempt.attempt_id)} disabled={left === attempt.attempt_id}>Use left</WorkbenchButton></td><td><WorkbenchButton onClick={() => chooseRight(attempt.attempt_id)} disabled={right === attempt.attempt_id}>Use right</WorkbenchButton></td></tr>)}</tbody></WorkbenchTable></div>}
      {mode === 'lab' && <div className="sa-trace-lab-form"><label>Left persisted attempt ID<input value={left} onChange={(event) => setLeft(event.target.value)} autoComplete="off" /></label><label>Right persisted attempt ID<input value={right} onChange={(event) => setRight(event.target.value)} autoComplete="off" /></label><label className="sa-trace-lab-check"><input type="checkbox" checked={partial} onChange={(event) => setPartial(event.target.checked)} /> Permit diagnostic partial mode when trace completeness is insufficient</label></div>}
      <div className="sa-journey-actions"><WorkbenchButton tone="primary" disabled={state === 'loading' || !left || !right} onClick={() => void compare()}>Compare persisted traces</WorkbenchButton>{executionId && <WorkbenchButton disabled={state === 'loading'} onClick={() => void loadExecution()}>Reload attempts</WorkbenchButton>}</div>
    </WorkbenchPanel>
    {result && evidence && <>
      {result.mode === 'DIAGNOSTIC_PARTIAL' && <SevereFailureBanner title="Partial trace diagnostic">Coverage exclusions are present. This is explicitly diagnostic partial mode and remains below any causal or reconstructed-event claim.</SevereFailureBanner>}
      <WorkbenchPanel title="Observed alignment" action={<StatusIndicator tone="warning">{result.causal_label}</StatusIndicator>}>
        <div className="sa-trace-lab-metrics"><div><span>Matched anchors</span><strong>{result.alignment.matched_anchors}</strong></div><div><span>Exact observations</span><strong>{result.alignment.exact_observation_matches}</strong></div><div><span>Content differences</span><strong>{result.alignment.content_differences}</strong></div><div><span>Left only</span><strong>{result.alignment.left_only}</strong></div><div><span>Right only</span><strong>{result.alignment.right_only}</strong></div><div><span>Clock-skew tolerant</span><strong>{String(result.alignment.clock_skew_tolerant)}</strong></div></div>
        <p>First meaningful divergence: <strong>{result.first_meaningful_divergence.found ? result.first_meaningful_divergence.reason : 'None observed'}</strong>. Rows align persisted semantic anchors and observation hashes; they do not expose payloads or infer cause.</p>
        {mode === 'lab'
          ? <p>Raw persisted traces: <a href={result.attempt_links.left.trace_url}>left {result.attempt_links.left.attempt_id}</a> · <a href={result.attempt_links.right.trace_url}>right {result.attempt_links.right.attempt_id}</a></p>
          : <p>Use Compare persisted traces to reproduce this bounded diagnostic from the automatically discovered attempts. Raw trace access and durable identities are available in Lab.</p>}
        {mode === 'lab' && <><DisclosureRow title="Trace source identities"><div className="sa-trace-lab-ids"><p><strong>Combined</strong> <code>{result.alignment.source_digest}</code></p><p><strong>Left</strong> <code>{result.alignment.source_digests.left}</code></p><p><strong>Right</strong> <code>{result.alignment.source_digests.right}</code></p></div></DisclosureRow><DisclosureRow title="Source event IDs"><div className="sa-trace-lab-ids"><p><strong>Left</strong> {result.source_event_ids.left.join(', ') || 'None'}</p><p><strong>Right</strong> {result.source_event_ids.right.join(', ') || 'None'}</p></div></DisclosureRow></>}
      </WorkbenchPanel>
      <AlignedTraceTimeline evidence={evidence} data={{ leftAttemptId: result.attempt_links.left.attempt_id, rightAttemptId: result.attempt_links.right.attempt_id, firstDivergence: result.first_meaningful_divergence.alignment_position, confidence: result.first_meaningful_divergence.confidence, events: alignedEvents }} />
      <StateBeforeAfterComparison evidence={evidence} data={changes} />
      {changes.length === 0 && <WorkbenchPanel title="State differences"><p>No observed state-reference difference was returned. This does not reconstruct absent state or trace values.</p></WorkbenchPanel>}
    </>}
  </section>
}
