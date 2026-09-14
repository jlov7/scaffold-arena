import { useState } from 'react'

import { ApiProblem, type CounterfactualBranchOutcome, type CounterfactualReplayReport, type CounterfactualReplayRequest, type HarnessCIReport, type createArenaV1 } from '../../../api/v1/client'
import { DisclosureRow, SevereFailureBanner, StatusIndicator, WorkbenchButton, WorkbenchPanel, WorkbenchState, WorkbenchTable } from '../../design-system'

import './counterfactual.css'

type Client = ReturnType<typeof createArenaV1>
type State = 'idle' | 'loading-replay' | 'loading-ci' | 'hold' | 'offline' | 'permission' | 'error'

export interface CounterfactualSurfaceProps {
  client: Client
  projectId?: string
  mode: 'guided' | 'lab'
}

const digest = (character: string) => `sha256:${character.repeat(64)}`

function branch(result: string, trace: string, evaluator: string, quality: number, latency: number): CounterfactualBranchOutcome {
  return {
    result_digest: digest(result), trace_digest: digest(trace), evaluator_output_digest: digest(evaluator), quality_score: quality,
    latency_state: 'observed', latency_ms: latency, usage: { state: 'unknown' }, fidelity_state: 'observed', fidelity_level: 'applied', process_safety: 'pass', severe_failure_codes: [],
  }
}

const fixtureReplay: CounterfactualReplayRequest = {
  schema_version: 'scaffold-arena.counterfactual-replay/1',
  mode: 'fixture',
  binding: {
    checkpoint_digest: digest('a'), initial_state_digest: digest('b'), pre_divergence_trace_digest: digest('c'), environment_digest: digest('d'), dependencies_digest: digest('e'), model_identity_digest: digest('f'), runtime_identity_digest: digest('0'), task_pack_digest: digest('1'), evaluator_digest: digest('2'), evaluator_configuration_digest: digest('3'), evaluation_configuration_digest: digest('4'), evaluator_blinded: true, base_genome_digest: digest('5'), candidate_genome_digest: digest('6'),
  },
  intervention: { mechanism_id: 'context_compaction', base_mechanism_digest: digest('7'), candidate_mechanism_digest: digest('8'), intervention_spec_digest: digest('9'), applied_control_receipt_digest: digest('a'), declared_change_count: 1 },
  semantic_diff: { source_diff_digest: digest('b'), changed_mechanism_ids: ['context_compaction'], recommended_packs: ['context-survival-v1'] },
  allocation: { allocation_digest: digest('c'), allocation_kind: 'paired', development_item_digests: [digest('d')], holdout_item_digests: [digest('e')], replay_item_digests: [digest('d')] },
  analysis_plan: { preregistration_digest: digest('0'), stopping_rule_digest: digest('1'), exclusion_rule_digest: digest('2'), primary_endpoint: 'quality_score', planned_repetitions: 2, deterministic_score_weight: 0.7, evaluator_blinded: true, confirmatory_holdout_declared: true, causal_claim_requested: false },
  pairs: [
    { pair_id: 'fixture-one', task_item_digest: digest('d'), repetition: 1, base: branch('3', '4', '5', 0.60, 100), candidate: branch('6', '7', '8', 0.70, 105) },
    { pair_id: 'fixture-two', task_item_digest: digest('d'), repetition: 2, base: branch('9', 'a', 'b', 0.55, 102), candidate: branch('c', 'd', 'e', 0.68, 107) },
  ],
}

function issue(error: unknown): { state: Exclude<State, 'idle' | 'loading-replay' | 'loading-ci'>; message: string } {
  if (error instanceof ApiProblem) {
    if (error.isHold) return { state: 'hold', message: error.message }
    if (error.status === 401 || error.status === 403 || error.code === 'project_context_required' || error.code === 'unknown_project') return { state: 'permission', message: error.message }
    return { state: error.status >= 500 ? 'offline' : 'error', message: error.message }
  }
  return { state: 'offline', message: error instanceof Error ? error.message : 'Counterfactual Replay could not be reached.' }
}

function effect(value: number | null, suffix = ''): string {
  return value === null ? 'Unknown' : `${value > 0 ? '+' : ''}${value.toFixed(3)}${suffix}`
}

export function CounterfactualSurface({ client, projectId, mode }: CounterfactualSurfaceProps) {
  const [state, setState] = useState<State>('idle')
  const [message, setMessage] = useState('Fixture mode is ready. It uses recorded references only and starts neither a provider nor a network operation.')
  const [replay, setReplay] = useState<CounterfactualReplayReport | null>(null)
  const [ci, setCi] = useState<HarnessCIReport | null>(null)

  const runReplay = async () => {
    setState('loading-replay')
    setMessage('Binding the fixed synthetic checkpoint, environment, task pack, evaluator, and two paired fixture references. No provider is started.')
    setReplay(null)
    setCi(null)
    try {
      const next = await client.counterfactual.create(fixtureReplay, { projectId })
      setReplay(next)
      setState(next.verdict === 'HOLD' ? 'hold' : 'idle')
      setMessage(next.verdict === 'HOLD' ? 'Fixture replay is truthfully HOLD: provider usage and cost are unknown, not zero.' : 'Fixture replay report recovered.')
    } catch (error) {
      const next = issue(error)
      setState(next.state)
      setMessage(next.message)
    }
  }

  const runCi = async () => {
    if (!replay) return
    setState('loading-ci')
    setMessage('Checking the recorded replay against a single context-compaction source change. The source excerpt is classified in memory and is not stored in the report.')
    setCi(null)
    try {
      const next = await client.harnessCi.create({
        replay_report_digest: replay.report_digest,
        base_source_digest: digest('1'), candidate_source_digest: digest('2'),
        source_changes: [{ path: 'fixture/context-policy.json', diff_text: '- context_strategy: verbatim\n+ context_strategy: context compaction' }],
        policy: { required_cohorts: ['development'], unknown_usage: 'hold', required_evidence_maturity: 'paired_replay', minimum_paired_repetitions: 2, minimum_fidelity: 'applied', allow_fixture_evidence: true },
      }, { projectId })
      setCi(next)
      setState(next.verdict === 'HOLD' ? 'hold' : 'idle')
      setMessage(`${next.verdict}: Harness CI retained its JSON report, step summary, and PR-comment body. It has not posted a comment.`)
    } catch (error) {
      const next = issue(error)
      setState(next.state)
      setMessage(next.message)
    }
  }

  if (state === 'offline') return <WorkbenchState kind="offline" title="Counterfactual Replay unavailable" action={<WorkbenchButton onClick={() => void runReplay()}>Retry fixture replay</WorkbenchButton>}>{message}</WorkbenchState>
  if (state === 'permission') return <SevereFailureBanner title="Project context required" action={<WorkbenchButton onClick={() => void runReplay()}>Retry with project context</WorkbenchButton>}>{message}</SevereFailureBanner>

  return <section className="sa-counterfactual" aria-labelledby="counterfactual-heading">
    <WorkbenchPanel title={<span id="counterfactual-heading">Counterfactual Replay</span>} action={<StatusIndicator tone="info">Provider-free fixture</StatusIndicator>}>
      <p className="sa-counterfactual-boundary">Run a checkpointed paired fixture only: shared pre-divergence state, checkpoint, environment, dependencies, model/runtime identity, task pack, and blinded evaluator; exactly one declared mechanism changes.</p>
      <div className="sa-counterfactual-grid" aria-label="Fixture controls and budget">
        <div><strong>Provider budget</strong><span>$0.00 consumed</span><small>Default fixture mode cannot start a provider.</small></div>
        <div><strong>Live replay</strong><span>Unavailable here</span><small>Requires explicit credentials attestation, positive budget, and a policy digest outside this surface.</small></div>
        <div><strong>Claim ceiling</strong><span>Fixture mechanics only</span><small>Replay is not causal proof or a model-performance claim.</small></div>
      </div>
      <div className="sa-journey-actions">
        <WorkbenchButton tone="primary" disabled={state === 'loading-replay' || state === 'loading-ci'} onClick={() => void runReplay()}>Run provider-free fixture replay</WorkbenchButton>
        <WorkbenchButton disabled={!replay || state === 'loading-replay' || state === 'loading-ci'} onClick={() => void runCi()}>Run Harness CI check</WorkbenchButton>
      </div>
      <p className="sa-counterfactual-status" role="status" aria-live="polite">{message}</p>
      {state === 'error' && <WorkbenchState kind="error" title="Counterfactual Replay failed" action={<WorkbenchButton onClick={() => void runReplay()}>Retry fixture replay</WorkbenchButton>}>{message}</WorkbenchState>}
      {state === 'hold' && <SevereFailureBanner title="Evidence HOLD">{message}</SevereFailureBanner>}
      <DisclosureRow title="What the fixture binds and forbids"><p>Branch-specific initial state, environment, dependency, model, runtime, task-pack, and evaluator changes are absent from the contract. Holdout overlap, more than one mechanism, evaluator leakage, unknown usage rendered as zero, and causal claims are rejected before a report is produced.</p></DisclosureRow>
    </WorkbenchPanel>
    {replay && <ReplayReport report={replay} mode={mode} />}
    {ci && <HarnessReport report={ci} mode={mode} />}
  </section>
}

function ReplayReport({ report, mode }: { report: CounterfactualReplayReport; mode: 'guided' | 'lab' }) {
  return <div className="sa-counterfactual-report">
    <WorkbenchPanel title="Paired replay result" action={<StatusIndicator tone={report.verdict === 'PASS' ? 'ready' : report.verdict === 'FAIL' ? 'failure' : 'warning'}>{report.verdict}</StatusIndicator>}>
      <dl className="sa-counterfactual-facts"><div><dt>Evidence maturity</dt><dd>{report.evidence_maturity.replaceAll('_', ' ')}</dd></div><div><dt>Repetitions</dt><dd>{report.pair_count} / {report.planned_repetitions}</dd></div><div><dt>Usage</dt><dd>{report.usage_state}</dd></div><div><dt>Fidelity</dt><dd>{report.fidelity_level ?? 'Unknown'}</dd></div>{mode === 'lab' && <div><dt>Report digest</dt><dd><code>{report.report_digest}</code></dd></div>}</dl>
      <p className="sa-counterfactual-boundary">{report.claim_ceiling}</p>
    </WorkbenchPanel>
    <WorkbenchPanel title="Effect and uncertainty">
      <WorkbenchTable aria-label="Paired effect and uncertainty"><thead><tr><th scope="col">Metric</th><th scope="col">Effect</th><th scope="col">95% interval</th><th scope="col">Evidence state</th></tr></thead><tbody>{report.effects.map((item) => <tr key={item.metric}><td>{item.metric}</td><td>{effect(item.point_estimate)}</td><td>{item.ci95_low === null || item.ci95_high === null ? 'Unknown' : `${effect(item.ci95_low)} to ${effect(item.ci95_high)}`}</td><td>{item.state}</td></tr>)}</tbody></WorkbenchTable>
      <p className="sa-counterfactual-note">Unknown usage/cost remains unknown. The interval describes recorded paired differences only; it does not identify a cause.</p>
    </WorkbenchPanel>
    <WorkbenchPanel title="Conditional measures"><WorkbenchTable aria-label="Conditional causal-family measures"><thead><tr><th scope="col">Measure</th><th scope="col">State</th><th scope="col">Value</th><th scope="col">Reason</th></tr></thead><tbody>{report.conditional_measures.map((item) => <tr key={item.measure}><td>{item.measure.replaceAll('_', ' ')}</td><td>{item.state}</td><td>Not estimated</td><td>{item.reason}</td></tr>)}</tbody></WorkbenchTable><p className="sa-counterfactual-note">ITT, opportunity, activation, fidelity failure, and treatment-on-the-treated remain unestimated unless their own assumptions are evidenced.</p></WorkbenchPanel>
    <WorkbenchPanel title="Evidence maturity ladder"><ol className="sa-counterfactual-ladder">{report.maturity_ladder.map((item) => <li key={item.maturity}><strong>{item.maturity.replaceAll('_', ' ')}</strong><span>{item.state}</span><p>{item.reason}</p></li>)}</ol></WorkbenchPanel>
  </div>
}

function HarnessReport({ report, mode }: { report: HarnessCIReport; mode: 'guided' | 'lab' }) {
  return <div className="sa-counterfactual-report">
    <WorkbenchPanel title="Harness CI policy result" action={<StatusIndicator tone={report.verdict === 'PASS' ? 'ready' : report.verdict === 'FAIL' ? 'failure' : 'warning'}>{report.verdict}</StatusIndicator>}>
      <p className="sa-counterfactual-boundary">{report.claim_ceiling}</p>
      <p className="sa-counterfactual-note">Recommended pack: {report.semantic_diff.recommended_packs.join(', ') || 'Unknown'}. PR-comment text is a retained artifact, not an automatic post.</p>
      {mode === 'lab' && <p className="sa-counterfactual-note"><code>{report.reproduction_command}</code></p>}
    </WorkbenchPanel>
    <WorkbenchPanel title="Policy checks">
      <WorkbenchTable aria-label="Harness CI policy checks"><thead><tr><th scope="col">Check</th><th scope="col">Verdict</th><th scope="col">Detail</th></tr></thead><tbody>{report.checks.map((check) => <tr key={check.check_id}><td>{check.check_id.replaceAll('_', ' ')}</td><td>{check.verdict}</td><td>{check.detail}</td></tr>)}</tbody></WorkbenchTable>
    </WorkbenchPanel>
  </div>
}
