import { useMemo, useState, type ReactNode } from 'react'

import { ApiProblem, type createArenaV1, type DiagnosticMetric, type ObservatoryReport, type ObservatoryRequest } from '../../../api/v1/client'
import { DisclosureRow, SevereFailureBanner, StatusIndicator, WorkbenchButton, WorkbenchPanel, WorkbenchState, WorkbenchTable } from '../../design-system'

import './observatory.css'

type Client = ReturnType<typeof createArenaV1>
type State = 'idle' | 'loading' | 'empty' | 'offline' | 'permission' | 'hold' | 'error'
type Metric = DiagnosticMetric & { status?: string; reason?: string }
type FidelityStage = 'declared' | 'assigned' | 'available' | 'triggered' | 'applied' | 'activated' | 'observed' | 'downstream pathway detected'
type FidelityRecord = { stage: string; status: string; reason: string; evidence_refs?: string[] }
type ObservatoryView = ObservatoryReport & {
  intervention_fidelity: FidelityRecord[]
  treatment_estimates?: Record<string, unknown>
  treatment_measures?: Record<string, unknown>
  evidence_ceiling?: string
}

const FIDELITY_STAGES: FidelityStage[] = ['declared', 'assigned', 'available', 'triggered', 'applied', 'activated', 'observed', 'downstream pathway detected']
const CONTEXT_METRICS = ['useful context density', 'irrelevant-token ratio', 'stale-context rate', 'instruction survival', 'source coverage', 'compression loss', 'contradiction exposure', 'retrieval precision', 'retrieval recall', 'context-window utilization', 'context cost per success']
const MEMORY_METRICS = ['write precision', 'retrieval precision', 'retrieval recall', 'stale-memory rate', 'contradiction resolution', 'write amplification', 'negative transfer', 'cross-task interference', 'privacy leakage', 'forgetting correctness', 'marginal contribution', 'cost per useful retrieval']
const LOOP_CHECKS = ['repeated-state loops', 'oscillation', 'redundant tools', 'verification without correction', 'retries with unchanged inputs', 'context growth without progress', 'premature stopping', 'missing stopping conditions', 'deadlock/livelock', 'unbounded delegation', 'recovery that worsens state']
const GRAPH_CHECKS = ['critical path', 'fan-in/fan-out', 'coordination overhead', 'duplicated messages', 'state bottlenecks', 'failure propagation', 'authority concentration', 'unused nodes', 'cycles', 'unreachable transitions', 'expensive low-value branches']

export interface ObservatorySurfaceProps {
  client: Client
  projectId?: string
  mode: 'guided' | 'lab'
  attemptIds: string[]
  xrayDigest: string | null
  sourceDigest: string | null
}

function issue(error: unknown): { state: Exclude<State, 'idle' | 'loading' | 'empty'>; message: string } {
  if (error instanceof ApiProblem) {
    if (error.isHold) return { state: 'hold', message: error.message }
    if (error.status === 401 || error.status === 403 || error.code === 'project_context_required' || error.code === 'unknown_project') return { state: 'permission', message: error.message }
    return { state: error.status >= 500 ? 'offline' : 'error', message: error.message }
  }
  return { state: 'offline', message: error instanceof Error ? error.message : 'The observatory could not be reached.' }
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function text(value: unknown, fallback = 'Unknown'): string {
  return typeof value === 'string' && value.trim() ? value : fallback
}

function metricKey(label: string): string {
  return label.replaceAll(/[^a-z0-9]+/g, '_').replaceAll(/^_|_$/g, '')
}

function normalizeMetrics(value: unknown): Metric[] {
  if (Array.isArray(value)) return value.filter((item): item is Metric => Boolean(item && typeof item === 'object' && typeof (item as Metric).metric_id === 'string'))
  const source = record(value)
  return Object.entries(source).map(([metric_id, raw]) => {
    const metric = record(raw)
    return {
      metric_id,
      value: typeof raw === 'string' || typeof raw === 'number' ? raw : metric.value as string | number | null ?? null,
      numerator: typeof metric.numerator === 'number' ? metric.numerator : null,
      denominator: typeof metric.denominator === 'number' ? metric.denominator : null,
      exclusions: Array.isArray(metric.exclusions) ? metric.exclusions.filter((item): item is string => typeof item === 'string') : [],
      status: typeof metric.status === 'string' ? metric.status : undefined,
      reason: typeof metric.reason === 'string' ? metric.reason : undefined,
    }
  })
}

function readLedgerMetric(ledger: Record<string, unknown>, label: string): Metric {
  const candidates = normalizeMetrics(ledger.metrics)
  const key = metricKey(label)
  const found = candidates.find((metric) => metric.metric_id === key || metric.metric_id === label)
  if (found) return found
  const raw = ledger[key]
  if (typeof raw === 'number' || typeof raw === 'string') return { metric_id: key, value: raw, numerator: null, denominator: null, exclusions: [], status: 'observed' }
  return { metric_id: key, value: null, numerator: null, denominator: null, exclusions: ['not observed in the named persisted evidence'], status: 'unknown', reason: 'No applicable bounded evidence was reported.' }
}

function metricValue(metric: Metric): string {
  if (metric.value === null || metric.value === undefined) return 'Unknown'
  return typeof metric.value === 'number' ? Number.isFinite(metric.value) ? String(metric.value) : 'Unknown' : metric.value
}

function statusFor(value: unknown): { status: string; reason: string } {
  if (typeof value === 'boolean') return { status: value ? 'observed' : 'not observed' , reason: value ? 'A bounded persisted signal was reported.' : 'No bounded persisted signal was reported.' }
  const details = record(value)
  if (typeof details.status === 'string') return { status: details.status, reason: text(details.reason, 'No additional explanation was reported.') }
  return { status: 'unknown', reason: 'No applicable bounded evidence was reported.' }
}

function metricTable(title: string, ledger: Record<string, unknown>, labels: string[]): ReactNode {
  return <WorkbenchPanel title={title}><WorkbenchTable aria-label={`${title} metrics`}><thead><tr><th scope="col">Metric</th><th scope="col">Value</th><th scope="col">Numerator / denominator</th><th scope="col">Status and exclusions</th></tr></thead><tbody>{labels.map((label) => {
    const metric = readLedgerMetric(ledger, label)
    const counts = metric.numerator === null || metric.denominator === null ? 'Unknown' : `${metric.numerator} / ${metric.denominator}`
    return <tr key={label}><td>{label}</td><td>{metricValue(metric)}</td><td>{counts}</td><td>{metric.status ?? 'unknown'}{metric.reason ? ` — ${metric.reason}` : ''}{metric.exclusions.length ? ` Exclusions: ${metric.exclusions.join('; ')}.` : ''}</td></tr>
  })}</tbody></WorkbenchTable><p className="sa-observatory-note">Unknown means the bounded persisted evidence did not support a value. It is never rendered as zero.</p></WorkbenchPanel>
}

export function ObservatorySurface(props: ObservatorySurfaceProps) {
  return <ObservatorySurfaceContent key={`${props.mode}:${props.attemptIds.join(',')}`} {...props} />
}

function ObservatorySurfaceContent({ client, projectId, mode, attemptIds, xrayDigest, sourceDigest }: ObservatorySurfaceProps) {
  const [ids, setIds] = useState(attemptIds.join(','))
  const [state, setState] = useState<State>(attemptIds.length ? 'idle' : 'empty')
  const [message, setMessage] = useState('')
  const [report, setReport] = useState<ObservatoryView | null>(null)

  const parsedAttemptIds = useMemo(() => Array.from(new Set(ids.split(',').map((value) => value.trim()).filter(Boolean))), [ids])
  const inspect = async () => {
    if (!parsedAttemptIds.length) {
      setState('empty')
      setMessage('Select at least one exact persisted attempt. The observatory does not discover, execute, replay, or reconstruct an attempt.')
      return
    }
    const payload: ObservatoryRequest = {
      attempt_ids: parsedAttemptIds,
      ...(xrayDigest ? { xray_analysis_digest: xrayDigest } : {}),
      ...(sourceDigest ? { source_artifact_digest: sourceDigest } : {}),
      diagnostic_partial_mode: false,
    }
    setState('loading')
    setMessage('Reading only named persisted evidence. The observatory is not a graph runtime and does not replay an attempt.')
    setReport(null)
    try {
      const next = await client.observatory.create(payload, { projectId })
      setReport(next as ObservatoryView)
      setState('idle')
      setMessage('Observatory report recovered. All values retain their reported evidence boundary.')
    } catch (error) {
      const next = issue(error)
      setState(next.state)
      setMessage(next.message)
    }
  }

  if (state === 'offline') return <WorkbenchState kind="offline" title="Observatory unavailable" action={<WorkbenchButton onClick={() => void inspect()}>Retry observation</WorkbenchButton>}>{message}</WorkbenchState>
  if (state === 'permission') return <SevereFailureBanner title="Project context required" action={<WorkbenchButton onClick={() => void inspect()}>Retry with project context</WorkbenchButton>}>{message}</SevereFailureBanner>

  return <section className="sa-observatory" aria-labelledby="observatory-heading">
    <WorkbenchPanel title={<span id="observatory-heading">Context, Memory, Loop, and Graph Observatory</span>} action={<StatusIndicator tone="info">Persisted evidence only</StatusIndicator>}>
      <p className="sa-observatory-boundary">Inspect named project-bound persisted events and custody artifacts. The observatory does not execute a graph, replay an attempt, or reconstruct missing evidence.</p>
      {mode === 'lab' ? <div className="sa-observatory-form"><div className="sa-observatory-field"><label htmlFor="observatory-attempt-ids">Persisted attempt IDs</label><input id="observatory-attempt-ids" value={ids} onChange={(event) => setIds(event.target.value)} autoComplete="off" spellCheck={false} aria-describedby="observatory-attempt-help" /><small id="observatory-attempt-help">Comma-separated durable IDs only. The service reads only the submitted project-bound records and rejects partial-mode reconstruction.</small></div></div> : <p className="sa-observatory-selection" data-selected={parsedAttemptIds.length > 0}>{parsedAttemptIds.length ? `${parsedAttemptIds.length} persisted attempt${parsedAttemptIds.length === 1 ? '' : 's'} selected from the durable route context.` : 'No persisted attempt is selected. Enter Lab mode only when you know the durable attempt identity.'}</p>}
      <div className="sa-journey-actions"><WorkbenchButton tone="primary" disabled={state === 'loading' || !parsedAttemptIds.length} onClick={() => void inspect()}>Inspect persisted evidence</WorkbenchButton></div>
      {state === 'loading' && <p className="sa-observatory-status" role="status">{message}</p>}
      {state === 'empty' && <WorkbenchState kind="empty" title="Persisted attempt required">{message || 'The observatory only accepts named, existing persisted attempt evidence. It cannot fill missing data from a runtime, source repository, or model.'}</WorkbenchState>}
      {state === 'hold' && <SevereFailureBanner title="Observatory HOLD">{message}</SevereFailureBanner>}
      {state === 'error' && <WorkbenchState kind="error" title="Observatory inspection failed" action={<WorkbenchButton onClick={() => void inspect()}>Retry observation</WorkbenchButton>}>{message}</WorkbenchState>}
      {state === 'idle' && message && <p className="sa-observatory-status" role="status">{message}</p>}
    </WorkbenchPanel>
    {report && <Details report={report} />}
  </section>
}

function Details({ report }: { report: ObservatoryView }) {
  const context = record(report.context_ledger)
  const memory = record(report.memory_ledger)
  const graph = record(report.graph_microscope)
  const loops = Array.isArray(report.loop_microscope) ? report.loop_microscope : []
  const fidelity = report.intervention_fidelity ?? []
  const estimates = record(report.treatment_estimates ?? report.treatment_measures)
  const evidenceCeiling = text(report.evidence_ceiling ?? report.claim_ceiling, 'Persisted-event observation only.')
  const fidelityByStage = new Map(fidelity.map((item) => [item.stage.replaceAll('_', ' '), item]))

  return <div className="sa-observatory-report">
    {metricTable('Context Ledger', context, CONTEXT_METRICS)}
    {metricTable('Memory Ledger', memory, MEMORY_METRICS)}
    <WorkbenchPanel title="Loop microscope"><WorkbenchTable aria-label="Loop microscope checks"><thead><tr><th scope="col">Check</th><th scope="col">Status</th><th scope="col">Reason</th></tr></thead><tbody>{LOOP_CHECKS.map((check) => {
      const item = loops.find((candidate) => candidate.check === check || candidate.check === metricKey(check) || candidate.detector === check || candidate.detector === metricKey(check)) ?? record(record(report.loop_microscope)[metricKey(check)])
      const value = statusFor(item)
      return <tr key={check}><td>{check}</td><td>{value.status}</td><td>{value.reason}</td></tr>
    })}</tbody></WorkbenchTable><p className="sa-observatory-note">A loop finding is an observation over recorded state and event references. It does not prove cause or reconstruct a missing iteration.</p></WorkbenchPanel>
    <WorkbenchPanel title="Graph microscope"><WorkbenchTable aria-label="Graph microscope checks"><thead><tr><th scope="col">Analysis</th><th scope="col">Status</th><th scope="col">Reason</th></tr></thead><tbody>{GRAPH_CHECKS.map((check) => {
      const value = statusFor(graph[metricKey(check)] ?? graph[check])
      return <tr key={check}><td>{check}</td><td>{value.status}</td><td>{value.reason}</td></tr>
    })}</tbody></WorkbenchTable><p className="sa-observatory-note">This is ingestion and evaluation of existing runtime evidence, not another graph runtime.</p></WorkbenchPanel>
    <WorkbenchPanel title="Intervention fidelity ladder" action={<StatusIndicator tone="warning">Evidence ordered</StatusIndicator>}>
      <ol className="sa-observatory-fidelity">{FIDELITY_STAGES.map((stage) => {
        const item = fidelityByStage.get(stage)
        return <li key={stage}><strong>{stage}</strong><span>{item?.status ?? 'unknown'}</span><p>{item?.reason ?? 'No applicable bounded evidence was reported.'}</p></li>
      })}</ol>
      <p className="sa-observatory-note">“Downstream pathway detected” requires an observed downstream edge. It is not inferred from a declaration, assignment, activation, or outcome alone.</p>
      <DisclosureRow title="Conditional treatment measures"><TreatmentMeasures estimates={estimates} /></DisclosureRow>
    </WorkbenchPanel>
    <WorkbenchPanel title="Observatory evidence boundary"><p>{evidenceCeiling}</p><p className="sa-observatory-note">Unknown-aware ledgers preserve absent, unavailable, or inapplicable values explicitly. Content-addressed reports support custody checks; they do not prove correctness, causality, performance, or security assurance.</p></WorkbenchPanel>
  </div>
}

function TreatmentMeasures({ estimates }: { estimates: Record<string, unknown> }) {
  const names = ['intention-to-treat', 'opportunity', 'activation', 'fidelity failure', 'treatment-on-the-treated']
  return <WorkbenchTable aria-label="Conditional treatment measures"><thead><tr><th scope="col">Measure</th><th scope="col">Result</th><th scope="col">Condition</th></tr></thead><tbody>{names.map((name) => {
    const details = record(estimates[metricKey(name)] ?? estimates[name])
    const applicable = details.assumptions_satisfied === true && (typeof details.value === 'number' || typeof details.value === 'string')
    return <tr key={name}><td>{name}</td><td>{applicable ? String(details.value) : 'Not estimated'}</td><td>{applicable ? text(details.assumption_note, 'Server reported required assumptions as satisfied.') : 'Not reported because the required assumptions or bounded evidence are unavailable.'}</td></tr>
  })}</tbody></WorkbenchTable>
}
