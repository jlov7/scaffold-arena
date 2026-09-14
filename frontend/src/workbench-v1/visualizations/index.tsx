import { useId, type ReactNode } from 'react'

import { DisclosureRow, SevereFailureBanner, StatusIndicator, WorkbenchButton, WorkbenchState, WorkbenchTable } from '../design-system'

import './visualizations.css'

export type KnownValue = number | null

export interface EvidenceExport {
  label: string
  href?: string
  onExport?: () => void
}

export interface EvidenceMetadata {
  numerator: string
  denominator: string
  exclusions: readonly string[]
  includedAttemptIds: readonly string[]
  sourceDigest: string
  analysisDigest: string
  caveat: string
  claimCeiling: string
  /** Guided surfaces retain the evidence ceiling while withholding raw durable identities. */
  display?: 'guided' | 'lab'
  export?: EvidenceExport
}

export interface VisualizationAction {
  label: string
  onAction: () => void
}

interface VisualizationStateBase {
  kind: 'loading' | 'empty' | 'error' | 'offline' | 'partial'
  title: string
  description: ReactNode
}

/** Empty, partial, offline, and error states require a caller-owned next action. */
export type VisualizationState =
  | (VisualizationStateBase & { kind: 'loading'; action?: VisualizationAction })
  | (VisualizationStateBase & { kind: 'empty' | 'error' | 'offline' | 'partial'; action: VisualizationAction })

interface VisualizationProps<T> {
  data: T
  evidence: EvidenceMetadata
  state?: VisualizationState
}

const unknown = (value: KnownValue, digits = 2) => value === null ? 'Unknown' : value.toFixed(digits)
const percent = (value: KnownValue) => value === null ? 'Unknown' : `${(value * 100).toFixed(1)}%`
const currency = (value: KnownValue) => value === null ? 'Unknown' : new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(value)
const interval = (low: KnownValue, high: KnownValue) => low === null || high === null ? 'Unknown' : `${low.toFixed(2)} to ${high.toFixed(2)}`
const stateAction = (action?: VisualizationAction) => action && <WorkbenchButton onClick={action.onAction}>{action.label}</WorkbenchButton>

function VisualizationStateView({ state }: { state?: VisualizationState }) {
  if (!state) return null
  if (state.kind === 'partial') return <section className="wbv-partial-state" aria-live="polite"><StatusIndicator tone="warning">partial</StatusIndicator><h3>{state.title}</h3><p>{state.description}</p>{stateAction(state.action)}</section>
  return <WorkbenchState kind={state.kind} title={state.title} action={stateAction(state.action)}>{state.description}</WorkbenchState>
}

export function EvidenceMetadataDisclosure({ evidence }: { evidence: EvidenceMetadata }) {
  const guided = evidence.display === 'guided'
  return <DisclosureRow title="Evidence and limitations">
    <dl className="wbv-evidence-list">
      <div><dt>Numerator</dt><dd>{evidence.numerator}</dd></div>
      <div><dt>Denominator</dt><dd>{evidence.denominator}</dd></div>
      <div><dt>Exclusions</dt><dd>{evidence.exclusions.length ? guided ? `${evidence.exclusions.length} excluded record(s); inspect identities in Lab.` : evidence.exclusions.join('; ') : 'None reported'}</dd></div>
      <div><dt>Included attempts</dt><dd className={guided ? undefined : 'wbv-mono'}>{evidence.includedAttemptIds.length ? guided ? `${evidence.includedAttemptIds.length} persisted attempt(s)` : evidence.includedAttemptIds.join(', ') : 'None'}</dd></div>
      <div><dt>Source digest</dt><dd className={guided ? undefined : 'wbv-mono'}>{guided ? 'Withheld in Guided; verify through Evidence Room.' : evidence.sourceDigest}</dd></div>
      <div><dt>Analysis digest</dt><dd className={guided ? undefined : 'wbv-mono'}>{guided ? 'Withheld in Guided; verify through Evidence Room.' : evidence.analysisDigest}</dd></div>
      <div><dt>Caveat</dt><dd>{evidence.caveat}</dd></div>
      <div><dt>Claim ceiling</dt><dd>{evidence.claimCeiling}</dd></div>
    </dl>
    {evidence.export && (evidence.export.href
      ? <a className="wbv-export" href={evidence.export.href}>{evidence.export.label}</a>
      : <WorkbenchButton onClick={evidence.export.onExport}>{evidence.export.label}</WorkbenchButton>)}
  </DisclosureRow>
}

function VisualizationFrame({ title, description, evidence, state, children }: { title: string; description: string; evidence: EvidenceMetadata; state?: VisualizationState; children: ReactNode }) {
  return <section className="wbv-frame" aria-label={title}>
    <header><div><h2>{title}</h2><p>{description}</p></div></header>
    <VisualizationStateView state={state} />
    {children}
    <EvidenceMetadataDisclosure evidence={evidence} />
  </section>
}

export interface MainEffect {
  factor: string
  level: string
  effect: KnownValue
  ciLow: KnownValue
  ciHigh: KnownValue
}

export function MainEffectHeatmap({ data, evidence, state }: VisualizationProps<readonly MainEffect[]>) {
  return <VisualizationFrame title="Main effects" description="Estimated effect and confidence interval by factor level." evidence={evidence} state={state}>
    {data.length > 0 && <div className="wbv-heatmap" aria-label="Main effect heatmap">
      {data.map((item) => <div key={`${item.factor}-${item.level}`} className="wbv-heat-cell" data-direction={item.effect === null ? 'unknown' : item.effect > 0 ? 'positive' : item.effect < 0 ? 'negative' : 'neutral'}>
        <strong>{item.factor}: {item.level}</strong><span>{unknown(item.effect)}</span><small>CI {interval(item.ciLow, item.ciHigh)}</small>
      </div>)}
    </div>}
    <SemanticTable label="Main effect values" headers={['Factor', 'Level', 'Effect', 'Confidence interval']} rows={data.map((item) => [item.factor, item.level, unknown(item.effect), interval(item.ciLow, item.ciHigh)])} />
  </VisualizationFrame>
}

export interface PairwiseInteraction {
  leftFactor: string
  rightFactor: string
  interaction: KnownValue
  ciLow: KnownValue
  ciHigh: KnownValue
}

export function PairwiseInteractionMap({ data, evidence, state }: VisualizationProps<readonly PairwiseInteraction[]>) {
  return <VisualizationFrame title="Pairwise interactions" description="Interaction effects; unknown indicates unavailable analysis rather than no interaction." evidence={evidence} state={state}>
    {data.length > 0 && <ul className="wbv-interaction-map" aria-label="Pairwise interaction map">{data.map((item) => <li key={`${item.leftFactor}-${item.rightFactor}`} data-direction={item.interaction === null ? 'unknown' : item.interaction > 0 ? 'positive' : item.interaction < 0 ? 'negative' : 'neutral'}><span>{item.leftFactor} × {item.rightFactor}</span><strong>{unknown(item.interaction)}</strong><small>CI {interval(item.ciLow, item.ciHigh)}</small></li>)}</ul>}
    <SemanticTable label="Pairwise interaction values" headers={['Factors', 'Interaction', 'Confidence interval']} rows={data.map((item) => [`${item.leftFactor} × ${item.rightFactor}`, unknown(item.interaction), interval(item.ciLow, item.ciHigh)])} />
  </VisualizationFrame>
}

export interface OrdinaryTaskTax {
  task: string
  clean: KnownValue
  stressed: KnownValue
  unit: string
}

export function OrdinaryTaskTaxComparison({ data, evidence, state }: VisualizationProps<readonly OrdinaryTaskTax[]>) {
  return <VisualizationFrame title="Clean versus stressed task tax" description="Ordinary-task performance is shown separately under clean and stressed conditions." evidence={evidence} state={state}>
    {data.map((item) => <div className="wbv-tax-row" key={item.task}><strong>{item.task}</strong><div><span>Clean</span><b data-value-state={item.clean === null ? 'unknown' : 'known'}>{unknown(item.clean)} {item.unit}</b></div><div><span>Stressed</span><b data-value-state={item.stressed === null ? 'unknown' : 'known'}>{unknown(item.stressed)} {item.unit}</b></div></div>)}
    <SemanticTable label="Clean versus stressed task values" headers={['Task', 'Clean', 'Stressed', 'Unit']} rows={data.map((item) => [item.task, unknown(item.clean), unknown(item.stressed), item.unit])} />
  </VisualizationFrame>
}

export interface ParetoPoint {
  label: string
  reliability: KnownValue
  cost: KnownValue
  latencyMs: KnownValue
  pareto: boolean
}

export function ReliabilityCostLatencyPareto({ data, evidence, state }: VisualizationProps<readonly ParetoPoint[]>) {
  const chartId = useId()
  const visible = data.filter((item) => item.cost !== null && item.latencyMs !== null)
  const incomplete = data.filter((item) => item.cost === null || item.latencyMs === null)
  const maxCost = Math.max(1, ...visible.map((item) => item.cost ?? 0))
  const maxLatency = Math.max(1, ...visible.map((item) => item.latencyMs ?? 0))
  return <VisualizationFrame title="Reliability, cost, and latency" description="Direct labels show the reported Pareto status; the plot is an orientation aid, not a hidden-value view." evidence={evidence} state={state}>
    {visible.length > 0 && <svg className="wbv-pareto" viewBox="0 0 640 260" role="img" aria-labelledby={`${chartId}-title ${chartId}-desc`}><title id={`${chartId}-title`}>Reliability cost latency Pareto view</title><desc id={`${chartId}-desc`}>Horizontal position is cost and vertical position is latency. Each point is directly labelled with reliability and Pareto status.</desc><line x1="52" x2="612" y1="218" y2="218" /><line x1="52" x2="52" y1="24" y2="218" />{visible.map((item) => { const x = 52 + ((item.cost ?? 0) / maxCost) * 548; const y = 218 - ((item.latencyMs ?? 0) / maxLatency) * 176; return <g key={item.label}><circle cx={x} cy={y} r="7" data-pareto={item.pareto} /><text x={Math.min(x + 10, 520)} y={y - 10}>{item.label}: {percent(item.reliability)} {item.pareto ? 'Pareto' : 'non-Pareto'}</text><title>{`${item.label}: reliability ${percent(item.reliability)}, cost ${currency(item.cost)}, latency ${unknown(item.latencyMs, 0)} ms, ${item.pareto ? 'Pareto' : 'not Pareto'}`}</title></g>})}</svg>}
    {incomplete.length > 0 && <section className="wbv-pareto-incomplete" aria-label="Unpriced or incomplete"><h3>Unpriced or incomplete</h3><p>These rows have no geometric position or Pareto status because reported cost or latency is missing.</p><ul>{incomplete.map((item) => <li key={item.label}><strong>{item.label}</strong> — reliability {percent(item.reliability)}; cost {currency(item.cost)}; latency {item.latencyMs === null ? 'Unknown' : `${unknown(item.latencyMs, 0)} ms`}</li>)}</ul></section>}
    <SemanticTable label="Reliability cost latency values" headers={['Treatment', 'Reliability', 'Cost', 'Latency', 'Pareto status']} rows={data.map((item) => [item.label, percent(item.reliability), currency(item.cost), item.latencyMs === null ? 'Unknown' : `${unknown(item.latencyMs, 0)} ms`, item.cost === null || item.latencyMs === null ? 'Not assessed (incomplete inputs)' : item.pareto ? 'Pareto' : 'Not Pareto'])} />
  </VisualizationFrame>
}

export interface SevereFailure {
  id: string
  category: string
  description: string
  affectedAttempts: readonly string[]
  resolution: string
}

export function SevereFailureMatrix({ data, evidence, state, onResolve }: VisualizationProps<readonly SevereFailure[]> & { onResolve?: () => void }) {
  return <section className="wbv-severe" aria-label="Severe failure matrix" data-severe-visible="true">
    {data.length > 0
      ? <SevereFailureBanner title={`Severe failures (${data.length})`} action={onResolve && <WorkbenchButton tone="danger" onClick={onResolve}>Resolve severe failures</WorkbenchButton>}>These failures are always visible and are not changed by chart filters.</SevereFailureBanner>
      : <section className="wbv-severe-clear" role="status"><strong>Severe failures (0)</strong><p>No severe failures reported. This is not a claim that evidence is complete.</p></section>}
    <VisualizationStateView state={state} />
    <SemanticTable label="All severe failures" headers={['Category', 'Description', 'Affected attempts', 'Resolution']} rows={data.map((item) => [item.category, item.description, item.affectedAttempts.join(', ') || 'None recorded', item.resolution])} />
    <EvidenceMetadataDisclosure evidence={evidence} />
  </section>
}

export interface AttemptConsistency {
  treatment: string
  passAt1: KnownValue
  passAtK: KnownValue
  passPowerK: KnownValue
  k: number
}

export function AttemptConsistencyDistribution({ data, evidence, state }: VisualizationProps<readonly AttemptConsistency[]>) {
  return <VisualizationFrame title="Attempt consistency" description="pass@1, pass@k, and pass^k are distinct measures and remain separately labelled." evidence={evidence} state={state}>
    <div className="wbv-consistency" aria-label="Attempt consistency metrics">{data.map((item) => <article key={item.treatment}><h3>{item.treatment}</h3><dl><div><dt>pass@1</dt><dd>{percent(item.passAt1)}</dd></div><div><dt>pass@{item.k}</dt><dd>{percent(item.passAtK)}</dd></div><div><dt>pass^{item.k}</dt><dd>{percent(item.passPowerK)}</dd></div></dl></article>)}</div>
    <SemanticTable label="Attempt consistency values" headers={['Treatment', 'pass@1', 'pass@k', 'pass^k', 'k']} rows={data.map((item) => [item.treatment, percent(item.passAt1), percent(item.passAtK), percent(item.passPowerK), String(item.k)])} />
  </VisualizationFrame>
}

export interface AlignedTraceEvent {
  position: number
  left: string | null
  right: string | null
  alignment: 'aligned' | 'left_only' | 'right_only' | 'diverged'
}

export interface TraceAnalysis {
  leftAttemptId: string
  rightAttemptId: string
  firstDivergence: number | null
  confidence: KnownValue
  events: readonly AlignedTraceEvent[]
}

export function AlignedTraceTimeline({ data, evidence, state }: VisualizationProps<TraceAnalysis>) {
  return <VisualizationFrame title="Aligned trace timeline" description="DIAGNOSTIC_ONLY — alignment identifies observed divergence; it does not establish cause, reconstruct missing events, or prove outcome correctness." evidence={evidence} state={state}>
    <p className="wbv-diagnostic">DIAGNOSTIC_ONLY</p><p className="wbv-trace-summary">First divergence: {data.firstDivergence === null ? 'Unknown' : `event ${data.firstDivergence}`} · confidence: {percent(data.confidence)}</p>
    <div className="wbv-trace-scroll" aria-label="Aligned trace events"><ol className="wbv-trace">{data.events.map((event) => <li key={event.position} data-alignment={event.alignment}><span>{event.position}</span><strong>{event.alignment.replace('_', ' ')}</strong><span>{event.left ?? 'Unknown'}</span><span>{event.right ?? 'Unknown'}</span></li>)}</ol></div>
    <SemanticTable label="Aligned trace events" headers={['Position', 'Alignment', data.leftAttemptId, data.rightAttemptId]} rows={data.events.map((event) => [String(event.position), event.alignment.replace('_', ' '), event.left ?? 'Unknown', event.right ?? 'Unknown'])} />
  </VisualizationFrame>
}

export interface StateChange {
  field: string
  before: string | null
  after: string | null
  status: 'changed' | 'unchanged' | 'unknown'
}

export function StateBeforeAfterComparison({ data, evidence, state }: VisualizationProps<readonly StateChange[]>) {
  return <VisualizationFrame title="State before and after" description="Observed state comparison only; unknown is preserved when either state cannot be read." evidence={evidence} state={state}>
    <div className="wbv-state-grid" aria-label="State comparison">{data.map((item) => <article key={item.field} data-state={item.status}><h3>{item.field}</h3><p><span>Before</span>{item.before ?? 'Unknown'}</p><p><span>After</span>{item.after ?? 'Unknown'}</p><small>{item.status}</small></article>)}</div>
    <SemanticTable label="State before and after values" headers={['Field', 'Before', 'After', 'Status']} rows={data.map((item) => [item.field, item.before ?? 'Unknown', item.after ?? 'Unknown', item.status])} />
  </VisualizationFrame>
}

export interface BudgetLineItem {
  label: string
  forecast: KnownValue
  actual: KnownValue
  unit: 'usd' | 'tokens' | 'tool_calls' | 'seconds'
}

function budgetValue(value: KnownValue, unit: BudgetLineItem['unit']) {
  if (value === null) return 'Unknown'
  if (unit === 'usd') return currency(value)
  if (unit === 'tokens') return `${value.toLocaleString('en-US')} tokens`
  if (unit === 'tool_calls') return `${value.toLocaleString('en-US')} tool calls`
  return `${value.toFixed(2)} seconds`
}

export function BudgetForecastActualView({ data, evidence, state }: VisualizationProps<readonly BudgetLineItem[]>) {
  return <VisualizationFrame title="Budget forecast and actual" description="Unknown actuals are distinct from zero and remain actionable rather than being silently treated as no cost." evidence={evidence} state={state}>
    <div className="wbv-budget-list" aria-label="Budget forecast and actual values">{data.map((item) => <div key={item.label}><strong>{item.label}</strong><span>Forecast <b>{budgetValue(item.forecast, item.unit)}</b></span><span>Actual <b data-value-state={item.actual === null ? 'unknown' : item.actual === 0 ? 'zero' : 'known'}>{budgetValue(item.actual, item.unit)}</b></span></div>)}</div>
    <SemanticTable label="Budget forecast and actual values" headers={['Budget item', 'Unit', 'Forecast', 'Actual']} rows={data.map((item) => [item.label, item.unit.replace('_', ' '), budgetValue(item.forecast, item.unit), budgetValue(item.actual, item.unit)])} />
  </VisualizationFrame>
}

export interface EvidenceMaturityStep {
  stage: string
  status: 'complete' | 'current' | 'blocked' | 'unknown'
  evidence: string
  reproduction: string
  claimCeiling: string
}

export function EvidenceMaturityReproductionLadder({ data, evidence, state }: VisualizationProps<readonly EvidenceMaturityStep[]>) {
  return <VisualizationFrame title="Evidence maturity and reproduction" description="The ladder separates custody, verification, and reproduction status from outcome correctness or independence claims." evidence={evidence} state={state}>
    <ol className="wbv-ladder" aria-label="Evidence maturity and reproduction ladder">{data.map((item, index) => <li key={item.stage} data-status={item.status}><span>{index + 1}</span><div><h3>{item.stage}</h3><p>{item.evidence}</p><p><strong>Reproduction:</strong> {item.reproduction}</p><p><strong>Ceiling:</strong> {item.claimCeiling}</p></div></li>)}</ol>
    <SemanticTable label="Evidence maturity and reproduction values" headers={['Stage', 'Status', 'Evidence', 'Reproduction', 'Claim ceiling']} rows={data.map((item) => [item.stage, item.status, item.evidence, item.reproduction, item.claimCeiling])} />
  </VisualizationFrame>
}

function SemanticTable({ label, headers, rows }: { label: string; headers: readonly string[]; rows: readonly (readonly string[])[] }) {
  return <div className="wbv-table" aria-label={`${label} source-of-truth table`}><WorkbenchTable aria-label={label}><thead><tr>{headers.map((header) => <th key={header} scope="col">{header}</th>)}</tr></thead><tbody>{rows.length ? rows.map((row, rowIndex) => <tr key={`${label}-${rowIndex}`}>{row.map((cell, cellIndex) => <td key={`${rowIndex}-${cellIndex}`}>{cell}</td>)}</tr>) : <tr><td colSpan={headers.length}>No values available.</td></tr>}</tbody></WorkbenchTable></div>
}
