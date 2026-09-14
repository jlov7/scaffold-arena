import type { Page, Route } from '@playwright/test'

const HASH = 'a'.repeat(64)

const buildMetadata = {
  schema_version: 'build-meta.v1',
  app_version: '0.9.1',
  protocol_version: '1.0',
  git_sha: 'dev',
  build_environment: 'test',
  build_time: 'unknown',
}

export const fixturePack = {
  study_pack_id: 'offline-demo-v1',
  version: '1.0.0',
  title: 'Offline demonstration StudyPack',
  authority_ceiling: 'synthetic fixture only',
}

const canonicalPack = {
  ...fixturePack,
  allowed_claims: ['Synthetic fixture journeys only.'],
  limitations: ['Not benchmark evidence.'],
  scenarios: [{ scenario_id: 'synthetic-task', title: 'Synthetic task', source_label: 'synthetic' }],
  harnesses: [{ harness_id: 'offline-harness', title: 'Offline harness' }],
  experiments: [{
    experiment_id: 'offline-experiment', study_pack_id: fixturePack.study_pack_id,
    scenario_ids: ['synthetic-task'], harness_ids: ['offline-harness'],
    model_endpoints: [{ endpoint_id: 'fixture-endpoint', title: 'Fixture endpoint' }],
    deterministic_weight: 0.8, repetitions: 1, design: 'full', frozen: false,
    factors: [{ factor_id: 'scaffold', description: 'Synthetic scaffold comparison', levels: ['control', 'structured'], manipulation_checks: [] }],
  }],
}

export const personalSession = {
  authenticated: true,
  mode: 'personal',
  csrf_token: 'csrf-test',
  authority_ceiling: 'local synthetic fixture only',
}

const readiness = {
  deployment_profile: 'personal',
  storage: { kind: 'local', configured: true },
  authentication: { mode: 'personal', configured: true },
  adapters: { configured: false, provider_started: false },
  budget: { max_cost_per_run_usd: 0, daily_budget_usd: 0 },
  retention: { status: 'HOLD', reason: 'Synthetic fixture has no retention authority.' },
  secrets: { exposed: false, source: 'not collected' },
}

const holdPreflight = {
  verdict: 'HOLD', blockers: [{ code: 'FIXTURE_ONLY', message: 'Synthetic fixture is intentionally not eligible for provider execution.' }],
  expected_attempts: 2, design_expansion_count: 2, provider_execution_started: false,
  claim_ceiling: 'local protocol admissibility only', authority_ceiling: 'synthetic fixture only',
  study_pack_readiness: { task_family_deterministic_weights: { extraction: 0.8 }, issues: [] },
  manipulation_checks: { varied_factor_ids: ['scaffold'], declared_check_factor_ids: [], valid: true, missing_factor_ids: [], missing_required_checks: [], required_scenario_checks: [] },
  budget: { max_total_cost_usd: 0 }, endpoint_pins: [], harnesses: [],
}

const counterfactualReplay = {
  schema_version: 'scaffold-arena.counterfactual-replay-report/1', report_id: 'fixture-replay', report_digest: `sha256:${'b'.repeat(64)}`, report_artifact_digest: `sha256:${'b'.repeat(64)}`, request_digest: `sha256:${'c'.repeat(64)}`, binding_digest: `sha256:${'d'.repeat(64)}`,
  mode: 'fixture', verdict: 'HOLD', evidence_maturity: 'paired_replay',
  maturity_ladder: [
    { maturity: 'temporal_correlation', state: 'observed', reason: 'Observation only.' },
    { maturity: 'diagnostic_divergence', state: 'observed', reason: 'Diagnostic only.' },
    { maturity: 'paired_replay', state: 'observed', reason: 'Common bindings recorded.' },
    { maturity: 'replicated_intervention', state: 'unknown', reason: 'Additional repeats unavailable.' },
    { maturity: 'confirmatory_eligibility', state: 'ineligible', reason: 'No holdout result.' },
  ],
  pair_count: 2, planned_repetitions: 2,
  effects: [
    { metric: 'quality', state: 'observed', point_estimate: 0.1, ci95_low: 0.02, ci95_high: 0.18, base_mean: 0.55, candidate_mean: 0.65, paired_samples: 2, reason: 'Recorded fixture values only.' },
    { metric: 'cost_usd', state: 'unknown', point_estimate: null, ci95_low: null, ci95_high: null, base_mean: null, candidate_mean: null, paired_samples: 0, reason: 'No provider usage.' },
  ],
  conditional_measures: [
    { measure: 'intention_to_treat', state: 'ineligible', value: null, reason: 'Not randomized.' },
    { measure: 'opportunity', state: 'ineligible', value: null, reason: 'No denominator.' },
    { measure: 'activation', state: 'ineligible', value: null, reason: 'Not observed.' },
    { measure: 'fidelity_failure', state: 'ineligible', value: null, reason: 'Not estimated.' },
    { measure: 'treatment_on_the_treated', state: 'ineligible', value: null, reason: 'No uptake binding.' },
  ],
  new_severe_failures: [], usage_state: 'unknown', fidelity_level: 'applied', process_safety: 'pass', claim_ceiling: 'Fixture mechanics only; not causal proof.', limitations: ['Usage remains unknown.'], provider_execution_started: false, execution_started: false, network_requested: false, idempotent_replay: false,
}

const harnessCi = {
  schema_version: 'scaffold-arena.harness-ci-report/1', report_id: 'fixture-hci', report_digest: `sha256:${'e'.repeat(64)}`, report_artifact_digest: `sha256:${'e'.repeat(64)}`, replay_report_digest: counterfactualReplay.report_digest,
  verdict: 'HOLD', checks: [{ check_id: 'usage', verdict: 'HOLD', detail: 'Usage is unknown, not zero.' }], effects: counterfactualReplay.effects, severe_failures: [], usage_state: 'unknown', fidelity_level: 'applied', evidence_maturity: 'paired_replay', semantic_diff: { affected_mechanisms: ['context_compaction'], recommended_packs: ['context-survival-v1'], classification_state: 'observed' }, reproduction_command: 'arena harness-ci', step_summary: '## Harness CI — HOLD', pr_comment_body: '## Harness CI — HOLD', claim_ceiling: 'Bounded policy check only; not causal proof.', provider_execution_started: false, execution_started: false, network_requested: false, idempotent_replay: false,
}

const forgeProposal = {
  proposal_id: 'forge-fixture-proposal', proposal_digest: `sha256:${'f'.repeat(64)}`, proposal_artifact_digest: `sha256:${'f'.repeat(64)}`,
  state: 'PENDING_APPROVAL', proposal: { mechanism_change: { mechanism_id: 'context_compaction' }, requested_claim_scope: 'fixture_contract' },
  claim_ceiling: 'Fixture product controls only.', execution_started: false, automatic_merge: false, idempotent_replay: false,
}

const forgePlan = {
  schema_version: 'scaffold-arena.next-best-experiment-report/1', report_id: 'forge-plan', report_digest: `sha256:${'1'.repeat(64)}`, report_artifact_digest: `sha256:${'1'.repeat(64)}`, request_digest: `sha256:${'2'.repeat(64)}`,
  mode: 'exploratory', verdict: 'READY', recommendations: [{ rank: 1, proposed_design: { design_id: 'context-design' }, expected_information_gain: 0.42, attempts: 2, cost_interval: { lower_usd: 2, upper_usd: 5 }, risk: 0.2, assumptions: ['Fixed evaluator.'], claim_ceiling: 'Fixture product controls only.', alternatives: [] }],
  excluded_designs: [{ design_id: 'retry-design', reason: 'Remaining budget cannot fund the minimum attempt count.' }], claim_ceiling: 'Fixture product controls only.', execution_started: false, network_requested: false, idempotent_replay: false,
}

const forgeSafety = {
  schema_version: 'scaffold-arena.process-safety-report/1', report_id: 'forge-safety', report_digest: `sha256:${'3'.repeat(64)}`, report_artifact_digest: `sha256:${'3'.repeat(64)}`, request_digest: `sha256:${'4'.repeat(64)}`,
  verdict: 'PASS', checks: [{ check_id: 'network_egress', verdict: 'PASS', detail: 'No external destination is declared.' }], retained_manifest_digests: [`sha256:${'5'.repeat(64)}`], claim_ceiling: 'Fixture product controls only.', raw_sensitive_content_retained: false, execution_started: false, network_requested: false, idempotent_replay: false,
}

function json(route: Route, body: object, status = 200): Promise<void> {
  return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
}

export async function mockWorkbenchV1(page: Page, options: { session?: object; unavailable?: boolean } = {}): Promise<void> {
  let frozen = false
  await page.route((url) => url.pathname === '/build-meta', (route) => json(route, buildMetadata))
  await page.route((url) => url.pathname.startsWith('/api/v1/'), async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname.replace(/^\/api\/v1/, '')
    if (path === '/session') return json(route, options.session ?? personalSession)
    if (options.unavailable) return json(route, { code: 'fixture_service_unavailable', message: 'Synthetic local fixture service unavailable.' }, 503)
    if (path === '/study-packs') {
      return json(route, route.request().method() === 'GET'
        ? { study_packs: [fixturePack], authority_ceiling: 'synthetic fixture only' }
        : { study_pack_id: fixturePack.study_pack_id, version: fixturePack.version })
    }
    if (path === '/study-packs/validate') return json(route, { valid: true, message: 'Synthetic fixture validated locally.' })
    if (path === '/counterfactual-replays' && route.request().method() === 'POST') return json(route, counterfactualReplay)
    if (path === '/harness-ci/checks' && route.request().method() === 'POST') return json(route, harnessCi)
    if (path === '/forge/proposals' && route.request().method() === 'POST') return json(route, forgeProposal)
    if (path === '/experiment-plans/next-best' && route.request().method() === 'POST') return json(route, forgePlan)
    if (path === '/process-safety-reports' && route.request().method() === 'POST') return json(route, forgeSafety)
    if (path === `/study-packs/${fixturePack.study_pack_id}/versions/${fixturePack.version}`) {
      return json(route, { study_pack: canonicalPack, canonical_study_pack: canonicalPack, custody: { claim_ceiling: 'synthetic fixture only' } })
    }
    if (path === '/experiments' && route.request().method() === 'POST') return json(route, { experiment_id: 'fixture-created-experiment' })
    if (path === '/experiments/fixture-created-experiment') return json(route, experimentDetail(frozen))
    if (path === '/experiments/fixture-created-experiment/freeze') {
      frozen = true
      return json(route, { frozen: true })
    }
    if (path === '/experiments/fixture-created-experiment/preflight') return json(route, holdPreflight)
    if (path === '/executions') return json(route, { executions: [], pagination: { next_offset: null }, claim_ceiling: 'fixture only' })
    if (path === '/settings') return json(route, readiness)
    if (path === '/xray/snapshots') return json(route, { snapshots: [], claim_ceiling: 'synthetic fixture only' })
    if (path === '/annotation-batches') return json(route, { annotation_batches: [], pagination: { next_offset: null }, identity_state: 'unverified', claim_ceiling: 'fixture only' })
    if (path === '/evidence') return json(route, { evidence: [], pagination: { next_offset: null }, integrity_not_truth: true, claim_ceiling: 'fixture only' })
    if (path === '/decision-briefs') return json(route, { decision_briefs: [], pagination: { next_offset: null }, integrity_not_truth: true, claim_ceiling: 'fixture only' })
    if (path.startsWith('/analysis-reports')) return json(route, { analysis_reports: [], pagination: { next_offset: null }, integrity_not_truth: true, claim_ceiling: 'fixture only' })
    if (path.startsWith('/executions/')) return json(route, { execution_id: 'fixture-execution', attempts: [], jobs: [], counts: {}, claim_ceiling: 'fixture only' })
    return json(route, { code: 'fixture_unhandled', message: `Unhandled synthetic fixture route: ${path}` }, 404)
  })
}

function experimentDetail(frozen: boolean) {
  return {
    experiment_id: 'fixture-created-experiment', definition: { ...canonicalPack.experiments[0], experiment_id: 'fixture-created-experiment' },
    immutable_identity: { frozen, freeze_hash: frozen ? HASH : null }, owner_approval: 'approved',
    study_pack_hash: HASH,
  }
}
