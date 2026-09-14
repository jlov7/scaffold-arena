import { useEffect, useMemo, useState, type ReactNode } from 'react'

import { ApiProblem, type createArenaV1, type DetectedMechanism, type XRayReport, type XRayRequest, type XRaySourceKind } from '../../../api/v1/client'
import { listXRaySnapshots, type ListXRaySnapshotsOptions, type XRaySnapshotList, type XRaySnapshotSummary } from '../../../api/v1/xraySnapshots'
import { DisclosureRow, SevereFailureBanner, StatusIndicator, WorkbenchButton, WorkbenchPanel, WorkbenchState, WorkbenchTable } from '../../design-system'

import './xray.css'

type Client = ReturnType<typeof createArenaV1>
type State = 'idle' | 'loading' | 'empty' | 'offline' | 'permission' | 'hold' | 'error'
type SnapshotLoader = (options?: ListXRaySnapshotsOptions) => Promise<XRaySnapshotList>
const SNAPSHOT_LOADING_MESSAGE = 'Loading the durable captured-source registry. No source is crawled or executed.'

const SOURCE_KINDS: Array<{ value: XRaySourceKind; label: string; help: string }> = [
  { value: 'auto', label: 'Auto-detect from capture', help: 'Uses only the durable captured record to determine its static source profile.' },
  { value: 'repository', label: 'Repository capture', help: 'A bounded repository, configuration, or manifest capture.' },
  { value: 'acp', label: 'ACP metadata', help: 'An already captured Agent Client Protocol identity or metadata record.' },
  { value: 'cli', label: 'CLI metadata', help: 'An already captured CLI profile, configuration, or receipt.' },
  { value: 'otel_bundle', label: 'OpenTelemetry bundle', help: 'A bounded captured telemetry export; no collector is contacted.' },
  { value: 'sdk', label: 'SDK integration', help: 'An already captured integration declaration or configuration.' },
  { value: 'recorded_run', label: 'Recorded run', help: 'A bounded prior-run capture; it is not replayed.' },
]

type Mechanism = DetectedMechanism & { summary?: string }
type ReportView = XRayReport & {
  likely_confounds?: string[]
  security_critical_paths?: string[]
  recommended_first_study?: string | Record<string, unknown>
  mechanisms: Mechanism[]
}

export interface XRaySurfaceProps {
  client: Client
  projectId?: string
  mode: 'guided' | 'lab'
  sourceDigest: string | null
  snapshotLoader?: SnapshotLoader
}

function issue(error: unknown): { state: Exclude<State, 'idle' | 'loading' | 'empty'>; message: string } {
  if (error instanceof ApiProblem) {
    if (error.isHold) return { state: 'hold', message: error.message }
    if (error.status === 401 || error.status === 403 || error.code === 'project_context_required' || error.code === 'unknown_project') return { state: 'permission', message: error.message }
    return { state: error.status >= 500 ? 'offline' : 'error', message: error.message }
  }
  return { state: 'offline', message: error instanceof Error ? error.message : 'Harness X-Ray could not be reached.' }
}

function text(value: unknown, fallback = 'Unknown'): string {
  return typeof value === 'string' && value.trim().length > 0 ? value : fallback
}

function strings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0) : []
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function mechanisms(report: ReportView): Mechanism[] {
  const source = report.mechanisms ?? report.detected_mechanisms ?? []
  return source.filter((item): item is Mechanism => Boolean(item && typeof item.mechanism_id === 'string' && typeof item.status === 'string'))
}

function costInterval(value: unknown): string {
  if (typeof value === 'string' && value.trim()) return value
  const interval = record(value)
  const lower = interval.lower ?? interval.minimum ?? interval.min ?? interval.minimum_usd
  const upper = interval.upper ?? interval.maximum ?? interval.max ?? interval.maximum_usd
  const currency = text(interval.currency, 'USD')
  if (typeof lower === 'number' && typeof upper === 'number') return `${currency} ${lower.toFixed(2)}–${upper.toFixed(2)}`
  const reason = text(interval.reason, '')
  return reason ? `Unknown — ${reason}` : 'Unknown — no cost is implied by a missing interval.'
}

function study(value: unknown): string {
  if (typeof value === 'string' && value.trim()) return value
  const details = record(value)
  const title = text(details.title, '')
  const summary = text(details.summary ?? details.description ?? details.design, '')
  return [title, summary].filter(Boolean).join(' — ') || 'Unknown — no study recommendation was derived from this capture.'
}

function listOrUnknown(values: string[], unknown: string): ReactNode {
  return values.length ? <ul className="sa-xray-list">{values.map((value) => <li key={value}>{value}</li>)}</ul> : <p className="sa-xray-unknown">{unknown}</p>
}

function snapshotLabel(snapshot: XRaySnapshotSummary): string {
  return snapshot.source_revision ? `${snapshot.source_name} · ${snapshot.source_revision}` : snapshot.source_name
}

export function XRaySurface(props: XRaySurfaceProps) {
  return <XRaySurfaceContent key={`${props.mode}:${props.projectId ?? ''}:${props.sourceDigest ?? ''}`} {...props} />
}

function XRaySurfaceContent({ client, projectId, mode, sourceDigest, snapshotLoader = listXRaySnapshots }: XRaySurfaceProps) {
  const [digest, setDigest] = useState(sourceDigest ?? '')
  const [kind, setKind] = useState<XRaySourceKind>(mode === 'guided' ? 'auto' : 'repository')
  const [state, setState] = useState<State>(sourceDigest ? 'idle' : mode === 'guided' ? 'loading' : 'empty')
  const [message, setMessage] = useState(sourceDigest || mode !== 'guided' ? '' : SNAPSHOT_LOADING_MESSAGE)
  const [report, setReport] = useState<ReportView | null>(null)
  const [snapshots, setSnapshots] = useState<XRaySnapshotSummary[]>([])
  const [selectedSnapshotId, setSelectedSnapshotId] = useState('')
  const [sourceRefresh, setSourceRefresh] = useState(0)

  const kindDetail = useMemo(() => SOURCE_KINDS.find((item) => item.value === kind)!, [kind])

  useEffect(() => {
    if (mode !== 'guided' || sourceDigest) return
    const controller = new AbortController()
    let active = true
    void snapshotLoader({ projectId, signal: controller.signal }).then((result) => {
      if (!active) return
      setSnapshots(result.snapshots)
      const first = result.snapshots[0]
      if (!first) {
        setSelectedSnapshotId('')
        setDigest('')
        setState('empty')
        setMessage('No durable captured source is available for this project. Capture one before running X-Ray.')
        return
      }
      setSelectedSnapshotId(first.snapshot_id)
      setDigest(first.source_digest)
      setKind('auto')
      setState('idle')
      setMessage('A durable captured source is ready for provider-free inspection.')
    }).catch((error) => {
      if (!active || controller.signal.aborted) return
      const next = issue(error)
      setState(next.state)
      setMessage(next.message)
    })
    return () => {
      active = false
      controller.abort()
    }
  }, [mode, projectId, snapshotLoader, sourceDigest, sourceRefresh])

  const reloadSnapshots = () => {
    setState('loading')
    setMessage(SNAPSHOT_LOADING_MESSAGE)
    setSourceRefresh((value) => value + 1)
  }

  const inspect = async () => {
    if (!digest) {
      setState('empty')
      setMessage('Choose a previously captured source before inspection. X-Ray never crawls, executes, installs, or fetches a source for you.')
      return
    }
    const payload: XRayRequest = { source_artifact_digest: digest, source_kind: kind }
    setState('loading')
    setMessage('Inspecting only the named captured artifact. No provider, process, or network operation is started.')
    setReport(null)
    try {
      const next = await client.xray.create(payload, { projectId })
      setReport(next)
      setState('idle')
      setMessage('Static report recovered. Candidate findings remain evidence-bounded.')
    } catch (error) {
      const next = issue(error)
      setState(next.state)
      setMessage(next.message)
    }
  }

  const sourceLoadFailed = mode === 'guided' && !digest
  if (state === 'offline') return <WorkbenchState kind="offline" title={sourceLoadFailed ? 'Captured sources unavailable' : 'Harness X-Ray unavailable'} action={<WorkbenchButton onClick={() => sourceLoadFailed ? reloadSnapshots() : void inspect()}>{sourceLoadFailed ? 'Reload captured sources' : 'Retry inspection'}</WorkbenchButton>}>{message}</WorkbenchState>
  if (state === 'permission') return <SevereFailureBanner title="Project context required" action={<WorkbenchButton onClick={() => sourceLoadFailed ? reloadSnapshots() : void inspect()}>Retry with project context</WorkbenchButton>}>{message}</SevereFailureBanner>

  return <section className="sa-xray" aria-labelledby="xray-heading">
    <WorkbenchPanel title={<span id="xray-heading">Harness X-Ray</span>} action={<StatusIndicator tone="info">Provider-free inspection</StatusIndicator>}>
      <p className="sa-xray-boundary">Inspect a bounded captured artifact to propose a candidate Harness Genome and mechanism graph. This surface never executes source, starts a provider, or contacts a network endpoint.</p>
      <div className="sa-xray-form">
        {mode === 'lab' ? <>
          <div className="sa-xray-field"><label htmlFor="xray-source-kind">Captured source type</label><select id="xray-source-kind" value={kind} onChange={(event) => setKind(event.target.value as XRaySourceKind)}>{SOURCE_KINDS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select><small>{kindDetail.help}</small></div>
          <div className="sa-xray-field"><label htmlFor="xray-artifact-digest">Captured artifact digest</label><input id="xray-artifact-digest" value={digest} onChange={(event) => setDigest(event.target.value.trim())} autoComplete="off" spellCheck={false} aria-describedby="xray-digest-help" /><small id="xray-digest-help">Lab mode accepts the exact immutable artifact identity. It does not accept a local path or URL for execution.</small></div>
        </> : <>
          <div className="sa-xray-field"><span className="sa-xray-field-label">Source profiling</span><strong>Auto-detect from the durable capture</strong><small>{SOURCE_KINDS[0].help} Guided mode cannot override the captured source profile.</small></div>
          {snapshots.length ? <div className="sa-xray-field"><label htmlFor="xray-captured-source">Captured source</label><select id="xray-captured-source" value={selectedSnapshotId} onChange={(event) => {
            const selected = snapshots.find((snapshot) => snapshot.snapshot_id === event.target.value)
            setSelectedSnapshotId(event.target.value)
            if (!selected) return
            setDigest(selected.source_digest)
            setKind('auto')
            setReport(null)
            setState('idle')
            setMessage('A durable captured source is ready for provider-free inspection.')
          }}>{snapshots.map((snapshot) => <option key={snapshot.snapshot_id} value={snapshot.snapshot_id}>{snapshotLabel(snapshot)}</option>)}</select><small>Guided mode loads only durable captures already registered to this project. Raw artifact digests remain hidden.</small></div> : <p className="sa-xray-selection" data-selected={Boolean(digest)}>{digest ? 'A captured source is selected from the durable route context.' : 'No captured source is available. Capture one first, or use Lab mode only with an existing immutable artifact identity.'}</p>}
        </>}
      </div>
      <div className="sa-journey-actions"><WorkbenchButton tone="primary" disabled={state === 'loading' || !digest} onClick={() => void inspect()}>Inspect captured source</WorkbenchButton></div>
      {state === 'loading' && <p role="status" className="sa-xray-status">{message}</p>}
      {state === 'empty' && <WorkbenchState kind="empty" title="Captured source required">{message || 'X-Ray requires a bounded, previously captured source. It will not discover or access a repository, CLI, SDK, agent, telemetry system, or recorded run on its own.'}</WorkbenchState>}
      {state === 'hold' && <SevereFailureBanner title="X-Ray HOLD">{message}</SevereFailureBanner>}
      {state === 'error' && <WorkbenchState kind="error" title="Harness X-Ray failed" action={<WorkbenchButton onClick={() => void inspect()}>Retry inspection</WorkbenchButton>}>{message}</WorkbenchState>}
      {state === 'idle' && message && <p role="status" className="sa-xray-status">{message}</p>}
    </WorkbenchPanel>
    {report && <Report report={report} mode={mode} />}
  </section>
}

export function Report({ report, mode }: { report: ReportView; mode: 'guided' | 'lab' }) {
  const candidate = record(report.candidate_genome)
  const graph = record(report.mechanism_graph)
  const rows = mechanisms(report)
  const unobservable = strings(report.unobservable_controls)
  const confounds = strings(report.likely_confounds ?? report.confounds)
  const security = strings(report.security_critical_paths ?? report.security_paths)
  const evidenceCeiling = text(report.evidence_ceiling ?? report.claim_ceiling, 'Static captured-source observation only.')
  const firstStudy = study(report.first_study ?? report.recommended_first_study)
  const expectedAttempts = typeof report.expected_attempts === 'number' ? String(report.expected_attempts) : 'Unknown — no attempt count is inferred.'

  return <div className="sa-xray-report">
    <WorkbenchPanel title="Candidate Harness Genome" action={<StatusIndicator tone="warning">Candidate, not verified</StatusIndicator>}>
      <dl className="sa-xray-facts"><div><dt>Subject</dt><dd>{text(candidate.name ?? candidate.subject ?? candidate.genome_id ?? candidate.source_kind, 'Unnamed candidate')}</dd></div><div><dt>Mechanism graph</dt><dd>{typeof graph.node_count === 'number' ? `${graph.node_count} observed/candidate node(s)` : Array.isArray(graph.nodes) ? `${graph.nodes.length} observed/candidate node(s)` : typeof candidate.component_count === 'number' ? `${candidate.component_count} candidate component(s)` : 'Unknown graph coverage'}</dd></div><div><dt>Evidence ceiling</dt><dd>{evidenceCeiling}</dd></div>{mode === 'lab' && <div><dt>Report digest</dt><dd><code>{report.report_digest}</code></dd></div>}</dl>
      <p className="sa-xray-boundary">A candidate Genome records what this bounded capture supports. Declared, observed, inferred, verified, unsupported, and unknown are distinct states.</p>
    </WorkbenchPanel>
    <WorkbenchPanel title="Detected mechanisms and evidence">
      <WorkbenchTable aria-label="Detected mechanism evidence"><thead><tr><th scope="col">Mechanism</th><th scope="col">Evidence status</th><th scope="col">Evidence links</th></tr></thead><tbody>{rows.length ? rows.map((item) => <tr key={item.mechanism_id}><td>{item.mechanism_id}{item.summary ? <small className="sa-xray-cell-note">{item.summary}</small> : null}</td><td>{item.status}</td><td>{mode === 'lab' ? item.evidence_refs.join(', ') || 'None' : item.evidence_refs.length ? `${item.evidence_refs.length} linked record(s)` : 'No linked record'}</td></tr>) : <tr><td colSpan={3}>Unknown — no mechanisms were reported for this bounded capture.</td></tr>}</tbody></WorkbenchTable>
      <p className="sa-xray-unknown">Inference remains inference; a missing signal is not proof of unsupported behavior.</p>
    </WorkbenchPanel>
    <div className="sa-xray-grid">
      <WorkbenchPanel title="Unobservable controls">{listOrUnknown(unobservable, 'Unknown — this capture cannot expose any additional control boundaries.')}</WorkbenchPanel>
      <WorkbenchPanel title="Likely confounds">{listOrUnknown(confounds, 'Unknown — no confound assessment was reported.')}</WorkbenchPanel>
      <WorkbenchPanel title="Security-critical paths">{listOrUnknown(security, 'Unknown — static inspection is not a security assessment.')}</WorkbenchPanel>
      <WorkbenchPanel title="Recommended first study"><p>{firstStudy}</p></WorkbenchPanel>
    </div>
    <WorkbenchPanel title="Planning bounds">
      <dl className="sa-xray-facts"><div><dt>Expected attempts</dt><dd>{expectedAttempts}</dd></div><div><dt>Expected cost interval</dt><dd>{costInterval(report.expected_cost_interval)}</dd></div><div><dt>Evidence ceiling</dt><dd>{evidenceCeiling}</dd></div></dl>
      <DisclosureRow title="What this report cannot establish"><p>It does not establish runtime behavior, provider use, performance, causality, security assurance, or independent verification. A content digest proves custody of bytes only within its stated boundary.</p></DisclosureRow>
    </WorkbenchPanel>
  </div>
}
