import { useState } from 'react'

import { ApiProblem, type ForgeProposalRecord, type ForgeProposalRequest, type NextBestExperimentReport, type NextBestExperimentRequest, type ProcessSafetyReport, type ProcessSafetyRequest, type createArenaV1 } from '../../../api/v1/client'
import { DisclosureRow, SevereFailureBanner, StatusIndicator, WorkbenchButton, WorkbenchPanel, WorkbenchState, WorkbenchTable } from '../../design-system'

import './forge.css'

type Client = ReturnType<typeof createArenaV1>
type State = 'idle' | 'proposal' | 'planner' | 'safety' | 'hold' | 'offline' | 'permission' | 'error'

export interface ForgeSurfaceProps {
  client: Client
  projectId?: string
  mode: 'guided' | 'lab'
}

const digest = (character: string) => `sha256:${character.repeat(64)}`
const safetyOutcomes = [
  'unnecessary_sensitive_data_access', 'prohibited_tool', 'permission_escalation', 'network_egress', 'secret_exposure',
  'unsafe_intermediate_artifact', 'policy_bypassing_retry', 'sensitive_persistent_memory', 'trace_log_leakage', 'cleanup_failure',
]

const fixtureProposal: ForgeProposalRequest = {
  proposal_id: 'forge-fixture-proposal', proposer_identity: 'fixture-proposer', source_provenance_digest: digest('a'), base_genome_digest: digest('b'), candidate_genome_digest: digest('c'),
  mechanism_change: { mechanism_id: 'context_compaction', base_mechanism_digest: digest('d'), candidate_mechanism_digest: digest('e'), patch_or_config_digest: digest('f'), declared_change_count: 1 },
  falsifiable_prediction: { metric_id: 'quality', direction: 'increase', threshold: 0.02, prediction_digest: digest('1') },
  expected_tradeoff: { quality: 'improve', safety: 'neutral', cost: 'increase', latency: 'increase', rationale_digest: digest('2') },
  triggering_evidence_digests: [digest('3')], rollback: { rollback_id: 'fixture-rollback', rollback_digest: digest('4'), recovery_plan_digest: digest('5') },
  requested_claim_scope: 'fixture_contract', untrusted: true, execution_requested: false, automatic_merge_requested: false, self_evaluation_requested: false, scalar_optimization_requested: false,
}

const fixturePlanner: NextBestExperimentRequest = {
  request_id: 'forge-fixture-plan', mode: 'exploratory',
  mechanisms: [{ mechanism_id: 'context_compaction', uncertainty: 0.8, expected_effect: 0.2, interaction_uncertainty: 0.1 }, { mechanism_id: 'retry_stopping', uncertainty: 0.4, expected_effect: 0.05, interaction_uncertainty: 0 }],
  coverage: [{ coverage_id: 'research', fraction: 0.8 }, { coverage_id: 'safety', fraction: 0.6 }],
  prior_evidence: [{ evidence_digest: digest('6'), mechanism_id: 'context_compaction', evidence_strength: 0.2 }],
  candidate_designs: [
    { design_id: 'context-design', mechanism_id: 'context_compaction', coverage_ids: ['research', 'safety'], cost_per_attempt_usd: 1, minimum_attempts: 2, maximum_attempts: 5, risk: 0.2, assumptions: ['Evaluator and analysis plan remain fixed.'] },
    { design_id: 'retry-design', mechanism_id: 'retry_stopping', coverage_ids: ['research'], cost_per_attempt_usd: 10, minimum_attempts: 2, maximum_attempts: 4, risk: 0.1, assumptions: ['Cost catalog remains pinned.'] },
  ],
  minimum_detectable_effect: 0.1, remaining_budget_usd: 6, maximum_risk: 0.3, frozen_analysis_plan_digest: null, exploratory_adaptation: false,
  source_evidence_digests: [digest('7')], execution_requested: false, automatic_admission_requested: false,
}

const fixtureSafety: ProcessSafetyRequest = {
  request_id: 'forge-fixture-safety',
  policy: { policy_digest: digest('8'), maximum_sensitivity: 'SECRET', allowed_tool_digests: [], allow_external_egress: false, maximum_delegation_depth: 0, secret_retention: 'digests_and_redacted_manifests_only', required_cleanup: true },
  flows: [{ flow_id: 'fixture-flow', source: 'artifact', destination: 'context', sensitivity: 'PUBLIC', content_digest: digest('9'), redacted_manifest_digest: digest('a'), tool_digest: null, delegation_depth: 0 }],
  outcomes: safetyOutcomes.map((outcome_type) => ({ outcome_type, state: 'NOT_OBSERVED' as const, evidence_digest: digest('b') })),
  transitions: [{ from_state: 'DRAFT', to_state: 'PENDING_APPROVAL', transition_digest: digest('c') }],
  cleanup_receipt_digest: digest('d'), source_manifest_digest: digest('e'), execution_started: false, network_requested: false,
}

function issue(error: unknown): { state: 'hold' | 'offline' | 'permission' | 'error'; message: string } {
  if (error instanceof ApiProblem) {
    if (error.isHold) return { state: 'hold', message: error.message }
    if (error.status === 401 || error.status === 403 || error.code === 'project_context_required' || error.code === 'unknown_project') return { state: 'permission', message: error.message }
    return { state: error.status >= 500 ? 'offline' : 'error', message: error.message }
  }
  return { state: 'offline', message: error instanceof Error ? error.message : 'Arena Forge could not be reached.' }
}

function tone(value: 'PASS' | 'HOLD' | 'FAIL' | 'READY' | 'PENDING_APPROVAL' | 'APPROVED' | 'REJECTED') {
  return value === 'PASS' || value === 'READY' || value === 'APPROVED' ? 'ready' : value === 'FAIL' || value === 'REJECTED' ? 'failure' : value === 'HOLD' ? 'warning' : 'info'
}

export function ForgeSurface({ client, projectId, mode }: ForgeSurfaceProps) {
  const [state, setState] = useState<State>('idle')
  const [message, setMessage] = useState('Forge stages untrusted, digest-bound records only. It cannot inspect sealed holdouts, choose its evaluator, execute a patch, or merge a change.')
  const [proposal, setProposal] = useState<ForgeProposalRecord | null>(null)
  const [plan, setPlan] = useState<NextBestExperimentReport | null>(null)
  const [safety, setSafety] = useState<ProcessSafetyReport | null>(null)

  const stageProposal = async () => {
    setState('proposal'); setMessage('Staging one untrusted fixture proposal. It remains PENDING_APPROVAL and does not create an execution path.')
    try {
      const next = await client.forge.proposals.create(fixtureProposal, { projectId })
      setProposal(next); setState('hold'); setMessage('Proposal recorded as untrusted and PENDING_APPROVAL. An independent human or policy must make a durable decision outside this surface.')
    } catch (error) { const next = issue(error); setState(next.state); setMessage(next.message) }
  }
  const simulatePlan = async () => {
    setState('planner'); setMessage('Simulating declared designs within the fixed budget and risk bounds. No experiment is being started.')
    try {
      const next = await client.experimentPlanner.create(fixturePlanner, { projectId })
      setPlan(next); setState(next.verdict === 'HOLD' ? 'hold' : 'idle'); setMessage(next.verdict === 'READY' ? 'Design simulation is ready for human review. It is not an execution or admission decision.' : 'No candidate design fits the declared constraints.')
    } catch (error) { const next = issue(error); setState(next.state); setMessage(next.message) }
  }
  const checkSafety = async () => {
    setState('safety'); setMessage('Checking digest-only fixture flows against fail-closed data, tool, network, delegation, secret, transition, and cleanup controls.')
    try {
      const next = await client.processSafety.create(fixtureSafety, { projectId })
      setSafety(next); setState(next.verdict === 'PASS' ? 'idle' : 'hold'); setMessage(`${next.verdict}: process-safety control record retained. It does not establish containment or a security assessment.`)
    } catch (error) { const next = issue(error); setState(next.state); setMessage(next.message) }
  }

  if (state === 'offline') return <WorkbenchState kind="offline" title="Arena Forge unavailable" action={<WorkbenchButton onClick={() => void simulatePlan()}>Retry design simulation</WorkbenchButton>}>{message}</WorkbenchState>
  if (state === 'permission') return <SevereFailureBanner title="Project context required" action={<WorkbenchButton onClick={() => void stageProposal()}>Retry with project context</WorkbenchButton>}>{message}</SevereFailureBanner>

  return <section className="sa-forge" aria-labelledby="forge-heading">
    <WorkbenchPanel title={<span id="forge-heading">Arena Forge</span>} action={<StatusIndicator tone="warning">Untrusted proposals</StatusIndicator>}>
      <p className="sa-forge-boundary">Forge proposes. Arena Core evaluates. Humans or policy admit. This fixture surface retains custody records only; it never executes, inspects a sealed holdout, changes an evaluator, self-grades, promotes itself, optimizes one unconstrained scalar, or auto-merges.</p>
      <div className="sa-forge-grid" aria-label="Forge control boundaries">
        <div><strong>Candidate change</strong><span>Exactly one mechanism</span><small>Base/candidate Genome, patch/config digest, falsifiable prediction, trade-off, evidence, rollback, and scope are bound.</small></div>
        <div><strong>Evaluation</strong><span>Independent and frozen</span><small>Development, sealed holdout, safety, optional transfer, controls, effects, uncertainty, failures, cost, and usage are distinct records.</small></div>
        <div><strong>Admission</strong><span>Human or policy only</span><small>No action in this surface grants execution, promotion, merge, or a security claim.</small></div>
      </div>
      <div className="sa-journey-actions">
        <WorkbenchButton tone="primary" disabled={state === 'proposal' || state === 'planner' || state === 'safety'} onClick={() => void stageProposal()}>Stage untrusted fixture proposal</WorkbenchButton>
        <WorkbenchButton disabled={state === 'proposal' || state === 'planner' || state === 'safety'} onClick={() => void simulatePlan()}>Simulate next best experiment</WorkbenchButton>
        <WorkbenchButton disabled={state === 'proposal' || state === 'planner' || state === 'safety'} onClick={() => void checkSafety()}>Check process-safety controls</WorkbenchButton>
      </div>
      <p className="sa-forge-status" role="status" aria-live="polite">{message}</p>
      {state === 'error' && <WorkbenchState kind="error" title="Arena Forge request failed" action={<WorkbenchButton onClick={() => void simulatePlan()}>Retry design simulation</WorkbenchButton>}>{message}</WorkbenchState>}
      {state === 'hold' && <SevereFailureBanner title="Approval or evidence HOLD">{message}</SevereFailureBanner>}
      <DisclosureRow title="Separated pathways"><p>Exploratory adaptation ranks only declared candidate designs. Confirmatory analysis requires a separate frozen analysis plan. The API holds evaluations until an independently approved proposal and a project-scoped PASS process-safety report are present.</p></DisclosureRow>
    </WorkbenchPanel>
    {proposal && <WorkbenchPanel title="Untrusted proposal record" action={<StatusIndicator tone={tone(proposal.state)}>{proposal.state.replaceAll('_', ' ')}</StatusIndicator>}><dl className="sa-forge-facts"><div><dt>Mechanism</dt><dd>{proposal.proposal.mechanism_change.mechanism_id.replaceAll('_', ' ')}</dd></div><div><dt>Claim scope</dt><dd>{proposal.proposal.requested_claim_scope.replaceAll('_', ' ')}</dd></div><div><dt>Merge authority</dt><dd>None</dd></div>{mode === 'lab' && <div><dt>Proposal digest</dt><dd><code>{proposal.proposal_digest}</code></dd></div>}</dl><p className="sa-forge-boundary">{proposal.claim_ceiling}</p></WorkbenchPanel>}
    {plan && <WorkbenchPanel title="Next-best-experiment design simulation" action={<StatusIndicator tone={tone(plan.verdict)}>{plan.verdict}</StatusIndicator>}><WorkbenchTable aria-label="Ranked constrained experiment designs"><thead><tr><th scope="col">Rank</th><th scope="col">Design</th><th scope="col">Information gain</th><th scope="col">Attempts</th><th scope="col">Cost interval</th><th scope="col">Risk</th></tr></thead><tbody>{plan.recommendations.map((item) => <tr key={item.proposed_design.design_id}><td>{item.rank}</td><td>{item.proposed_design.design_id}</td><td>{item.expected_information_gain.toFixed(3)}</td><td>{item.attempts}</td><td>${item.cost_interval.lower_usd.toFixed(2)}–${item.cost_interval.upper_usd.toFixed(2)}</td><td>{item.risk.toFixed(2)}</td></tr>)}</tbody></WorkbenchTable>{plan.excluded_designs.length > 0 && <p className="sa-forge-note">Excluded: {plan.excluded_designs.map((item) => `${item.design_id} (${item.reason})`).join('; ')}</p>}<p className="sa-forge-boundary">{plan.claim_ceiling}</p></WorkbenchPanel>}
    {safety && <WorkbenchPanel title="Process-safety and information-flow checks" action={<StatusIndicator tone={tone(safety.verdict)}>{safety.verdict}</StatusIndicator>}><WorkbenchTable aria-label="Process-safety checks"><thead><tr><th scope="col">Control</th><th scope="col">Verdict</th><th scope="col">Detail</th></tr></thead><tbody>{safety.checks.map((check) => <tr key={check.check_id}><td>{check.check_id.replaceAll('-', ' ').replaceAll('_', ' ')}</td><td>{check.verdict}</td><td>{check.detail}</td></tr>)}</tbody></WorkbenchTable><p className="sa-forge-note">Retained evidence is digest-only or a redacted manifest; raw sensitive content is not retained by this contract.</p><p className="sa-forge-boundary">{safety.claim_ceiling}</p></WorkbenchPanel>}
  </section>
}
