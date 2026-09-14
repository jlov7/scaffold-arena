export type JsonPrimitive = string | number | boolean | null
export type JsonValue = JsonPrimitive | JsonObject | JsonValue[]
export interface JsonObject {
  [key: string]: JsonValue
}

export type ProtocolVersion = '1.0'
export type HoldVerdict = 'HOLD'
export type ReadinessVerdict = 'PASS' | HoldVerdict

export interface ApiProblemBody {
  error?: {
    code?: string
    message?: string
  }
  detail?: unknown
  verdict?: unknown
}

export interface ArenaSession {
  authenticated: boolean
  mode: 'personal' | 'team'
  project_id?: string
  authority_ceiling?: string
  login?: 'not_applicable'
  user?: { issuer: string; subject: string; email: string | null; display_name: string | null }
  memberships?: Array<{ project_id: string; role: 'admin' | 'operator' | 'reviewer' | 'viewer' }>
  csrf_token?: string
  expires_at?: string
}

export interface DeploymentReadiness {
  deployment_profile: 'personal' | 'team'
  storage: { configured: boolean; kind: 'sqlite' | 'postgresql'; team_ready: boolean }
  authentication: { mode: string; configured: boolean }
  adapters: { configured: boolean; provider_started: false }
  budget: { max_cost_per_run_usd: number; daily_budget_usd: number }
  retention: { status: string; reason: string }
  secrets: { exposed: false; source: string }
}

export interface RetentionPreview {
  project_id: string
  snapshot_digest: string
  confirmation_token: string
  retention_days: number | null
  eligible_purge: { idempotency_records: number; artifact_bytes: number }
  immutable_exclusions: string[]
  claim_ceiling: string
}

export interface RetentionPlan {
  id: string
  project_id: string
  state: 'scheduled' | 'cancelled' | 'executed' | 'blocked'
  snapshot_digest: string
  due_at: string
  grace_seconds: number
}

/** A truthful HTTP failure: fields unavailable from the response stay undefined. */
export class ApiProblem extends Error {
  readonly status: number
  readonly code?: string
  readonly details?: unknown
  readonly verdict?: HoldVerdict

  constructor(status: number, body: ApiProblemBody, fallbackMessage: string) {
    super(body.error?.message ?? fallbackMessage)
    this.name = 'ApiProblem'
    this.status = status
    this.code = body.error?.code
    this.details = body.detail
    this.verdict = body.verdict === 'HOLD' ? 'HOLD' : undefined
  }

  get isHold(): boolean {
    return this.status === 409 && this.verdict === 'HOLD'
  }
}

export interface SourceRef {
  source_uri: string
  content_hash: string
}

export interface ExecutionProvenance {
  protocol_version?: ProtocolVersion
  code_revision: string
  code_hash: string
  runtime_image: string
  runtime_image_hash: string
  environment_hash: string
  prompt_hash: string
  context_hash: string
  tool_hash: string
  source_refs: SourceRef[]
  captured_at: string
}

export interface BudgetSpec {
  max_attempts: number
  max_cost_usd: number
  max_latency_seconds: number
  max_tokens: number
  max_tool_calls: number
  max_context_tokens: number
}

export interface AggregateBudgetSpec {
  max_total_cost_usd: number
  max_total_tokens: number
  max_total_tool_calls: number
  max_wall_time_seconds: number
  max_attempts: number
}

export interface ExperimentSpec {
  protocol_version?: ProtocolVersion
  experiment_id: string
  study_pack_id: string
  scenario_ids: string[]
  harness_ids: string[]
  deterministic_weight: number
  factors?: JsonValue[]
  repetitions?: number
  sampling?: JsonObject
  budgets?: BudgetSpec | null
  aggregate_budget?: AggregateBudgetSpec | null
  owner_approval?: 'pending' | 'approved' | 'rejected'
  frozen?: boolean
  freeze_hash?: string | null
}

export interface StudyPack {
  protocol_version?: ProtocolVersion
  study_pack_id: string
  version: string
  title: string
  license_spdx: string
  authors: JsonObject[]
  compatibility: JsonObject
  allowed_claims: string[]
  limitations: string[]
  preregistration: JsonObject
  scenarios: JsonObject[]
  harnesses: JsonObject[]
  experiments: ExperimentSpec[]
}

/** Registry metadata returned by GET /study-packs; this is not the StudyPack document. */
export interface StudyPackSummary {
  id: string
  study_pack_id: string
  version: string
  content_digest: string
  manifest_hash: string
  title: string
  license_spdx: string
  authors: JsonObject[]
  allowed_claims: string[]
  limitations: string[]
  created_at: string
  authority_ceiling: string
  idempotent_replay: boolean
}

export interface StudyPackDetail {
  study_pack: StudyPackSummary
  canonical_study_pack: StudyPack
  custody: {
    content_digest: string
    manifest_hash: string
    artifact_integrity_verified: true
  }
  claim_ceiling: string
  authority_ceiling: string
}

export interface ExperimentSummary {
  experiment_id: string
  study_pack_registry_id: string
  study_pack_id: string
  study_pack_version: string
  protocol_version: ProtocolVersion
  predecessor_id: string | null
  owner_approval: 'pending' | 'approved' | 'rejected'
  frozen: boolean
  freeze_hash: string | null
  study_pack_hash: string | null
  frozen_at: string | null
  created_at: string
  authority_ceiling: string
}

export interface ExperimentDetail extends ExperimentSummary {
  definition: JsonObject
  immutable_identity: {
    frozen: boolean
    freeze_hash: string | null
    study_pack_hash: string | null
    frozen_at: string | null
  }
}

export interface ExecutionSummary {
  execution_id: string
  experiment_id: string
  status: string
  started_at: string | null
  completed_at: string | null
  created_at: string
}

export interface ExecutionList {
  executions: ExecutionSummary[]
  pagination: {
    limit: number
    offset: number
    next_offset: number | null
  }
  claim_ceiling: string
}

export interface ExecutionDetail extends ExecutionSummary {
  attempts: Array<{
    attempt_id: string
    episode_id: string
    episode_ordinal: number
    scenario_id: string
    ordinal: number
    status: string
    created_at: string
  }>
  jobs: Array<{
    job_id: string
    attempt_id: string | null
    kind: string
    status: string
    attempt_count: number
    available_at: string | null
    cancel_requested_at: string | null
    created_at: string
  }>
  counts: {
    attempts: number
    jobs: number
  }
  claim_ceiling: string
}

/** Backend-enforced bounds are 1..100 for limit and >= 0 for offset. */
export interface ExecutionPageOptions {
  experimentId?: string
  limit?: number
  offset?: number
}

export interface ReadinessIssue {
  code: string
  scope: string
  message: string
}

export interface ProtocolReadinessReport {
  protocol_version?: ProtocolVersion
  verdict: ReadinessVerdict
  task_family_deterministic_weights: Record<string, number>
  issues: ReadinessIssue[]
}

export interface PreflightReport {
  verdict: ReadinessVerdict
  blockers: ReadinessIssue[]
  study_pack_readiness: ProtocolReadinessReport
  design_expansion_count: number
  expected_attempts: number
  budget: JsonObject
  harnesses: JsonObject[]
  manipulation_checks: {
    varied_factor_ids: string[]
    declared_check_factor_ids: string[]
    required_scenario_checks: JsonObject[]
    missing_required_checks: JsonObject[]
    missing_factor_ids: string[]
    valid: boolean
  }
  endpoint_pins: JsonObject[]
  provider_execution_started: boolean
  claim_ceiling: string
  authority_ceiling: string
}

export interface ExecutionCreated {
  execution_id: string
  expected_attempts: number
  job_ids: string[]
  idempotent_replay: boolean
  provider_execution_started_by_request: false
  claim_ceiling: string
}

export interface ExecutionEvent {
  cursor: string
  event: string
  data: JsonObject
  event_id?: string
}

export interface TerminalExecutionEvent extends ExecutionEvent {
  event: 'terminal'
  data: JsonObject & { execution_id: string; status: string }
}

export interface AttemptView {
  attempt_id: string
  execution_id: string
  status: string
  execution_status: string
  ordinal: number
  request: JsonObject
  result: JsonObject
}

export interface AttemptTraceView {
  attempt_id: string
  events: Array<JsonObject & { event_id: string; sequence: number; event_type: string; payload: JsonObject; created_at: string }>
}

export interface DerivedEvidenceRequest {
  execution_id: string
  request_key: string
}

export type EvidenceType = 'fixture' | 'local_live' | 'reproduction' | 'cross_model' | 'human_calibration' | 'independent_reproduction'
export type EvidenceReceiptKind = EvidenceType | 'derived_fixture' | 'derived_local_live'
export type EvidenceClass = 'fixture' | 'local_live' | 'replicated' | 'cross_model' | 'human_calibrated' | 'independently_reproduced'

export interface EvidenceManifest {
  experiment_id: string
  experiment_hash: string
  study_pack_hash: string
  spec_hash: string
  code_hash: string
  runtime_hash: string
  adapter_hash: string
  model_hash: string
  price_hash: string
  evaluator_hashes: string[]
  artifact_hashes: string[]
  exclusions?: string[]
  limitations?: string[]
  evidence_class: EvidenceClass
  claim_ceiling: string
  integrity_not_truth?: true
}

export interface EvidenceReceipt {
  receipt_id: string
  manifest_hash: string
  artifact_hashes: string[]
  receipt_hash: string
  integrity_not_truth?: true
}

export interface EvidenceAdmissionRequest {
  manifest: EvidenceManifest
  receipt: EvidenceReceipt
  evidence_type: EvidenceType
  execution_id: string | null
}

export interface ReproductionReceipt {
  receipt_id: string
  original_operator_id: string
  original_authority_id: string
  reproducer_operator_id: string
  reproducer_authority_id: string
  original_environment_hash: string
  reproducer_environment_hash: string
  original_manifest_hash: string
  reproduced_manifest_hash: string
  deviations?: string[]
  independent?: false
  integrity_not_truth?: true
}

export interface ExternalIndependenceAttestation {
  reproduction_receipt_hash: string
  original_operator_id: string
  original_authority_id: string
  reproducer_operator_id: string
  reproducer_authority_id: string
  attester_authority_id: string
  attestation_evidence_ref: string
  externally_attested?: true
}

export interface ReproductionRequest {
  receipt: ReproductionReceipt
  original_evidence_receipt_id: string
  reproduced_evidence_receipt_id: string
  external_attestation: ExternalIndependenceAttestation | null
}

export interface EvaluatorIdentity {
  evaluator_id: string
  version: string
  digest: string
}

export interface GraderInstallation {
  grader_id: string
  version: string
  digest: string
  trusted?: true
}

export interface GraderBinding {
  metric_id: string
  weight: number
  kind: 'deterministic' | 'qualitative'
  installation: GraderInstallation
}

export interface HumanCalibrationReceipt {
  receipt_id: string
  batch_hash: string
  protocol_hash: string
  review_completion_digest: string
  annotator_count: number
  resolved_conflicts?: true
  identity_state?: 'verified'
  authority_id: string
  attestation_ref: string
}

export interface GraderPlan {
  bindings: GraderBinding[]
  human_calibration_receipt?: HumanCalibrationReceipt | null
}

export interface RubricDimension {
  metric_id: string
  instruction: string
  anchor_0: string
  anchor_1: string
}

export interface HumanRubric {
  rubric_id: string
  version: string
  digest: string
  dimensions: RubricDimension[]
}

export interface AnnotationItem {
  item_id: string
  attempt_id: string
}

export interface AnnotationBatch {
  batch_id: string
  protocol_hash: string
  evaluator: EvaluatorIdentity
  grader_plan: GraderPlan
  rubric: HumanRubric
  annotator_pseudonyms: string[]
  items: AnnotationItem[]
}

export interface AnnotationSubmission {
  assignment_id: string
  annotator_pseudonym: string
  dimension_scores: Record<string, number>
}

export interface AdjudicationSubmission {
  item_id: string
  adjudicator_pseudonym: string
  final_scores: Record<string, number>
  decision: string
  rationale: string
  evidence_artifact_digest: string
}

export type ClaimKind = 'fixture_observation' | 'local_live_observation' | 'causal_effect' | 'generalized_effect' | 'cost_comparison' | 'pareto_comparison' | 'cross_model_replication' | 'human_calibrated_assessment' | 'independent_validation'
export type ClaimCeiling = 'no_claim' | 'fixture_only' | 'local_live_only' | 'confirmatory_analysis' | 'replicated' | 'cross_model' | 'human_calibrated' | 'independent'
export type DecisionVerdict = 'PASS' | 'HOLD' | 'REJECT'

export interface RiskConstraints {
  severe_failure_disposition?: 'HOLD' | 'REJECT'
  require_zero_exclusions?: true
  require_estimated_effect_for_effect_claims?: true
  maximum_claim_ceiling?: ClaimCeiling
}

export interface ProposedClaim {
  claim_id: string
  statement: string
  kind: ClaimKind
  linked_receipt_ids: string[]
}

interface DecisionAdmissionBase {
  risk_constraints: RiskConstraints
  proposed_claims: ProposedClaim[]
}

export type DecisionAdmissionRequest =
  | (DecisionAdmissionBase & { analysis_report_id: string; experiment_id?: never; execution_id?: never })
  | (DecisionAdmissionBase & { analysis_report_id?: never; experiment_id: string; execution_id: string })

export interface ReviewProtocolSummary {
  batch_id: string
  status: 'PENDING' | 'IN_REVIEW' | 'NEEDS_ADJUDICATION' | 'COMPLETE'
  assignment_count: number
  submitted_annotation_count: number
  conflicted_items: string[]
  conflicted_dimensions: Record<string, string[]>
  incomplete_items: string[]
  protocol_completion_digest: string
  protocol_complete: boolean
  identity_state: 'identity_unverified'
  human_calibration_receipt: null
  human_validated: false
  independently_validated: false
  claim_ceiling: string
}

export interface AnnotationBatchCreated extends ReviewProtocolSummary {
  idempotent_replay: boolean
}

export interface AnnotationBatchListItem {
  batch_id: string
  created_at: string
  protocol_hash: string
  evaluator: EvaluatorIdentity
  status: ReviewProtocolSummary['status']
  assignment_count: number
  submitted_annotation_count: number
  conflicted_items: string[]
  incomplete_items: string[]
  protocol_complete: boolean
  identity_state: 'identity_unverified'
  claim_ceiling: string
}

export interface AnnotationBatchList {
  annotation_batches: AnnotationBatchListItem[]
  pagination: { limit: number; offset: number; next_offset: number | null }
  identity_state: 'identity_unverified'
  claim_ceiling: string
}

export interface BlindAssignment {
  assignment_id: string
  item_id: string
  blind_payload_digest: string
}

export interface AnnotationBatchView {
  batch_id: string
  protocol_hash: string
  status: ReviewProtocolSummary['status']
  conflicted_dimensions: Record<string, string[]>
  identity_state: 'identity_unverified'
  assignments: BlindAssignment[]
  claim_ceiling: string
}

export interface AssignmentView extends BlindAssignment {
  blinded_content: JsonObject
  identity_state: 'identity_unverified'
  claim_ceiling: string
}

export interface EvidenceReceiptDetail {
  receipt_id: string
  receipt_hash: string
  manifest_hash: string
  evidence_type: EvidenceReceiptKind
  evidence_class: EvidenceClass
  claim_ceiling: string
  integrity_not_truth: true
  artifacts: Array<{ sha256: string; disposition: 'withheld'; reason: string }>
  admission_workflow?: 'derived_execution'
}

export interface EvidenceReceiptCreated extends EvidenceReceiptDetail {
  idempotent_replay: boolean
}

export interface DerivedEvidenceReceipt extends EvidenceReceiptCreated {
  admission_workflow: 'derived_execution'
}

export interface EvidenceListItem {
  receipt_id: string
  created_at: string
  execution_id: string | null
  receipt_hash: string
  manifest_hash: string
  evidence_type: EvidenceReceiptKind
  evidence_class: EvidenceClass
  artifact_count: number
  artifact_content: 'withheld'
  claim_ceiling: string
  integrity_not_truth: true
  admission_workflow?: 'derived_execution'
}

export interface EvidenceList {
  evidence: EvidenceListItem[]
  pagination: { limit: number; offset: number; next_offset: number | null }
  integrity_not_truth: true
  claim_ceiling: string
}

export interface EvidenceVerification {
  receipt_id: string
  verified: boolean
  errors: string[]
  receipt_hash: string
  manifest_hash: string
  integrity_not_truth: true
  claim_ceiling: string
}

export interface ReproductionCreated {
  reproduction_receipt_id: string
  reproduction_hash: string
  original_evidence_receipt_id: string
  reproduced_evidence_receipt_id: string
  external_attestation_contract: 'recorded' | 'missing'
  independently_verified: false
  claim_ceiling: string
  integrity_not_truth: true
  idempotent_replay: boolean
}

export interface DecisionClaimReference {
  claim_id: string
  receipt_ids: string[]
}

export interface DecisionBriefDetail {
  decision_brief_id: string
  analysis_report_id: string
  experiment_id: string
  execution_id: string
  report_digest: string
  verdict: DecisionVerdict
  claim_ceiling: ClaimCeiling
  claim_refs: DecisionClaimReference[]
  brief_ref: string
  ledger_ref: string
  brief_hash: string
  ledger_hash: string
  artifact_content: 'withheld'
  integrity_not_truth: true
}

export interface DecisionBriefCreated extends DecisionBriefDetail {
  idempotent_replay: boolean
}

export interface DecisionBriefListItem {
  decision_brief_id: string
  created_at: string
  analysis_report_id: string
  experiment_id: string
  execution_id: string
  report_digest: string
  verdict: DecisionVerdict
  claim_ceiling: ClaimCeiling
  claim_count: number
  artifact_content: 'withheld'
  integrity_not_truth: true
}

export interface DecisionBriefList {
  decision_briefs: DecisionBriefListItem[]
  pagination: { limit: number; offset: number; next_offset: number | null }
  integrity_not_truth: true
  claim_ceiling: string
}

/** Backend-enforced bounds are 1..100 for limit and >= 0 for offset. */
export interface AnnotationBatchPageOptions {
  status?: ReviewProtocolSummary['status']
  limit?: number
  offset?: number
}

/** Backend-enforced bounds are 1..100 for limit and >= 0 for offset. */
export interface EvidencePageOptions {
  executionId?: string
  kind?: EvidenceReceiptKind
  limit?: number
  offset?: number
}

/** Backend-enforced bounds are 1..100 for limit and >= 0 for offset. */
export interface DecisionBriefPageOptions {
  executionId?: string
  reportDigest?: string
  verdict?: DecisionVerdict
  limit?: number
  offset?: number
}

export interface AnalysisRequest {
  experiment_id: string
  execution_id: string
  analysis_config: JsonObject
}

export interface AnalysisExternalFitterReceipt {
  receipt_id: string
  fitter: string
  fitter_version: string
  immutable: true
  input_digest: string
  output_digest: string
  result_ref: string
}

export interface AnalysisAdequacyReport {
  claim_level: string
  reasons: string[]
  manipulation_fidelity: number
  trace_completeness: number
  evaluator_independence: number
  held_out_coverage: number
  mixed_effect_status: 'NOT_RUN'
  external_fitter_receipt: AnalysisExternalFitterReceipt | null
}

/** Canonical chart values preserve NULL/UNKNOWN rather than replacing them with zero. */
export interface AnalysisChartSeries {
  series_id: string
  numerator: number
  denominator: number
  exclusions: Array<[string, string]>
  attempt_ids: string[]
  constituent_attempt_ids: string[]
  value: number | null
}

export interface AnalysisEffectReport {
  effect_id: string
  kind: 'main' | 'interaction'
  outcome: string
  estimate: number | null
  confidence_interval: [number | null, number | null]
  cluster_count: number
  effective_pairs: number
  status: 'ESTIMATED' | 'HOLD'
  reason: string | null
  raw_p_value: number | null
  adjusted_p_value: number | null
  rejected_after_correction: boolean | null
  control_attempt_ids: string[]
  treatment_attempt_ids: string[]
  series: AnalysisChartSeries
}

export interface AnalysisProfileReport {
  profile_id: string
  attempt_ids: string[]
  pass_at_1: AnalysisChartSeries
  pass_at_k: AnalysisChartSeries
  pass_power_k: AnalysisChartSeries
  severe_failure: AnalysisChartSeries
  auditability: AnalysisChartSeries
  latency_seconds: AnalysisChartSeries
  cost_status: 'reconciled' | 'unknown'
  cost_usd: AnalysisChartSeries
  provider_usage_refs: string[]
  price_references: string[]
}

export interface ResearchAnalysisEffect {
  term: string
  estimate: number
  credible_interval: [number, number]
}

export interface ResearchAnalysisReport {
  status: 'NOT_RUN' | 'RESEARCH_EXTRA_UNAVAILABLE' | 'HOLD_ADEQUACY' | 'HOLD_SEPARATION' | 'HOLD_SINGULAR' | 'HOLD_NONCONVERGED' | 'ESTIMATED'
  reason: string | null
  estimator: string | null
  package_versions: Array<[string, string]>
  formula: string | null
  random_effects: string | null
  converged: boolean | null
  effects: ResearchAnalysisEffect[]
  data_digest: string | null
}

/** Immutable canonical JSON from GET /analysis-reports/{report_digest}. */
export interface AnalysisReport {
  schema_version: 'analysis-report-v1'
  experiment_id: string
  included_attempt_ids: string[]
  exclusions: Array<[string, string]>
  severe_failures_before_composites: Array<[string, number]>
  profiles: AnalysisProfileReport[]
  clean_vs_stressed_tax: AnalysisEffectReport[]
  main_effects: AnalysisEffectReport[]
  secondary_interactions: AnalysisEffectReport[]
  secondary_correction: string
  adequacy: AnalysisAdequacyReport
  research: ResearchAnalysisReport
  pareto_profile_ids: string[]
  pareto_exclusions: Array<[string, string]>
  minimum_sufficient_profile_id: string | null
  minimum_sufficient_status: string | null
  trace_attribution: 'DIAGNOSTIC_ONLY'
  trace_attribution_note: string
  canonical_hash: string
}

export interface AnalysisReportBinding {
  id: string
  project_id: string
  experiment_id: string
  execution_id: string
  spec_hash: string
  study_pack_hash: string
  configuration_digest: string
  input_digest: string
  report_digest: string
  artifact_digest: string
}

export interface AnalysisReportSourceDigests {
  spec_hash: string
  study_pack_hash: string
  configuration_digest: string
  input_digest: string
}

export interface AnalysisReportSummary {
  report_digest: string
  artifact_digest: string
  artifact_ref: string
  experiment_id: string
  execution_id: string
  created_at: string
  adequacy: AnalysisAdequacyReport
  claim_ceiling: string
  integrity_not_truth: true
}

export interface AnalysisReportList {
  analysis_reports: AnalysisReportSummary[]
  pagination: {
    limit: number
    offset: number
    next_offset: number | null
  }
  integrity_not_truth: true
  claim_ceiling: string
}

export interface AnalysisReportDetail {
  report: AnalysisReport
  binding: AnalysisReportBinding
  report_digest: string
  artifact_digest: string
  artifact_ref: string
  source_digests: AnalysisReportSourceDigests
  adequacy: AnalysisAdequacyReport
  claim_ceiling: string
  integrity_not_truth: true
}

/** Backend-enforced bounds are 1..100 for limit and >= 0 for offset. */
export interface AnalysisReportPageOptions {
  experimentId?: string
  executionId?: string
  limit?: number
  offset?: number
}

export interface TraceAnalysisRequest {
  left_attempt_id: string
  right_attempt_id: string
  diagnostic_partial_mode?: boolean
  declared_semantic_anchors?: string[]
}

export type XRaySourceKind = 'auto' | 'repository' | 'acp' | 'cli' | 'sdk' | 'otel_bundle' | 'recorded_run'
export interface XRayRequest { source_artifact_digest: string; source_kind: XRaySourceKind; profile_id?: string }
export interface ObservatoryRequest { attempt_ids: string[]; xray_analysis_digest?: string; source_artifact_digest?: string; diagnostic_partial_mode: false }
export interface DiagnosticMetric { metric_id: string; value: string | number | null; numerator: number | null; denominator: number | null; exclusions: string[] }
export type XRayEvidenceStatus = 'declared' | 'observed' | 'inferred' | 'verified' | 'unsupported' | 'unknown'
export interface DetectedMechanism { mechanism_id: string; status: XRayEvidenceStatus; evidence_refs: string[]; inference_basis?: string; verification_method?: string; limitation?: string }
export interface XRayReport {
  report_id: string
  report_digest: string
  analysis_digest: string
  claim_ceiling: string
  report_artifact_digest: string
  candidate_genome: Record<string, unknown>
  mechanism_graph: Record<string, unknown>
  detected_mechanisms: DetectedMechanism[]
  mechanisms: DetectedMechanism[]
  unobservable_controls: string[]
  confounds: string[]
  security_paths: string[]
  first_study: Record<string, unknown>
  expected_attempts: number | null
  expected_cost_interval: Record<string, unknown>
  evidence_ceiling: string
  limitations: string[]
  provider_execution_started: false
  execution_started: false
  network_requested: false
  idempotent_replay: boolean
}
export interface InterventionFidelity { stage: string; status: string; reason: string }
export interface ObservatoryReport {
  report_id: string
  report_digest: string
  analysis_digest: string
  claim_ceiling: string
  report_artifact_digest: string
  evidence_ceiling: string
  context_ledger: Record<string, unknown>
  memory_ledger: Record<string, unknown>
  loop_microscope: Array<Record<string, unknown>>
  graph_microscope: Record<string, unknown>
  intervention_fidelity: InterventionFidelity[]
  fidelity_ladder: string[]
  fidelity_level: string
  metrics: DiagnosticMetric[]
  attempt_ids: string[]
  xray_analysis_digest: string | null
  source_artifact_digest: string | null
  limitations: string[]
  provider_execution_started: false
  execution_started: false
  network_requested: false
  idempotent_replay: boolean
}
export type DiagnosticReport = XRayReport | ObservatoryReport

export type CounterfactualReplayMode = 'fixture' | 'recorded' | 'live'
export type CounterfactualVerdict = 'PASS' | 'HOLD' | 'FAIL'
export type CounterfactualValueState = 'observed' | 'unknown'
export type CounterfactualEvidenceMaturity = 'temporal_correlation' | 'diagnostic_divergence' | 'paired_replay' | 'replicated_intervention' | 'confirmatory_eligibility'
export type CounterfactualFidelityLevel = 'declared' | 'assigned' | 'available' | 'triggered' | 'applied' | 'activated' | 'observed' | 'downstream_pathway_detected'

export interface CounterfactualReplayBinding {
  checkpoint_digest: string
  initial_state_digest: string
  pre_divergence_trace_digest: string
  environment_digest: string
  dependencies_digest: string
  model_identity_digest: string
  runtime_identity_digest: string
  task_pack_digest: string
  evaluator_digest: string
  evaluator_configuration_digest: string
  evaluation_configuration_digest: string
  evaluator_blinded?: true
  base_genome_digest: string
  candidate_genome_digest: string
}

export interface CounterfactualBranchOutcome {
  result_digest: string
  trace_digest: string
  evaluator_output_digest: string
  quality_score: number
  latency_state: CounterfactualValueState
  latency_ms?: number | null
  usage: {
    state: CounterfactualValueState
    provider_usage_digest?: string | null
    price_catalog_revision?: string | null
    input_tokens?: number | null
    output_tokens?: number | null
    cost_usd?: number | null
  }
  fidelity_state: 'observed' | 'unknown' | 'ineligible'
  fidelity_level?: CounterfactualFidelityLevel | null
  process_safety: 'pass' | 'fail' | 'unknown'
  severe_failure_codes: string[]
}

export interface CounterfactualReplayRequest {
  schema_version?: 'scaffold-arena.counterfactual-replay/1'
  mode: CounterfactualReplayMode
  binding: CounterfactualReplayBinding
  intervention: {
    mechanism_id: string
    base_mechanism_digest: string
    candidate_mechanism_digest: string
    intervention_spec_digest: string
    applied_control_receipt_digest: string
    declared_change_count: 1
  }
  semantic_diff: { source_diff_digest: string; changed_mechanism_ids: string[]; recommended_packs: string[] }
  allocation: { allocation_digest: string; allocation_kind: 'paired' | 'randomized_paired'; development_item_digests: string[]; holdout_item_digests: string[]; replay_item_digests: string[] }
  analysis_plan: { preregistration_digest: string; stopping_rule_digest: string; exclusion_rule_digest: string; primary_endpoint: string; planned_repetitions: number; deterministic_score_weight: number; evaluator_blinded: true; confirmatory_holdout_declared: boolean; causal_claim_requested: false }
  pairs: Array<{ pair_id: string; task_item_digest: string; repetition: number; base: CounterfactualBranchOutcome; candidate: CounterfactualBranchOutcome }>
  live_authorization?: { credentials_configured: true; budget_usd: number; policy_digest: string } | null
}

export interface CounterfactualEffectEstimate {
  metric: 'quality' | 'cost_usd' | 'latency_ms'
  state: CounterfactualValueState
  point_estimate: number | null
  ci95_low: number | null
  ci95_high: number | null
  base_mean: number | null
  candidate_mean: number | null
  paired_samples: number
  reason: string
}

export interface CounterfactualReplayReport {
  schema_version: 'scaffold-arena.counterfactual-replay-report/1'
  report_id: string
  report_digest: string
  report_artifact_digest: string
  request_digest: string
  binding_digest: string
  mode: CounterfactualReplayMode
  verdict: CounterfactualVerdict
  evidence_maturity: CounterfactualEvidenceMaturity
  maturity_ladder: Array<{ maturity: CounterfactualEvidenceMaturity; state: 'observed' | 'unknown' | 'ineligible'; reason: string }>
  pair_count: number
  planned_repetitions: number
  effects: CounterfactualEffectEstimate[]
  conditional_measures: Array<{ measure: 'intention_to_treat' | 'opportunity' | 'activation' | 'fidelity_failure' | 'treatment_on_the_treated'; state: 'unknown' | 'ineligible'; value: null; reason: string }>
  new_severe_failures: string[]
  usage_state: CounterfactualValueState
  fidelity_level: CounterfactualFidelityLevel | null
  process_safety: 'pass' | 'fail' | 'unknown'
  claim_ceiling: string
  limitations: string[]
  provider_execution_started: false
  execution_started: false
  network_requested: false
  idempotent_replay: boolean
}

export interface HarnessCIRequest {
  schema_version?: 'scaffold-arena.harness-ci/1'
  replay_report_digest: string
  base_source_digest: string
  candidate_source_digest: string
  source_changes: Array<{ path: string; diff_text: string }>
  policy: {
    fail_on_new_severe_failures?: boolean
    max_quality_regression?: number
    max_cost_increase_ratio?: number
    max_latency_increase_ratio?: number
    required_cohorts?: Array<'development' | 'holdout'>
    unknown_usage?: 'hold' | 'fail'
    required_evidence_maturity?: CounterfactualEvidenceMaturity
    minimum_paired_repetitions?: number
    minimum_fidelity?: CounterfactualFidelityLevel
    require_process_safety?: boolean
    allow_fixture_evidence?: boolean
  }
}

export interface HarnessCIReport {
  schema_version: 'scaffold-arena.harness-ci-report/1'
  report_id: string
  report_digest: string
  report_artifact_digest: string
  replay_report_digest: string
  verdict: CounterfactualVerdict
  checks: Array<{ check_id: string; verdict: CounterfactualVerdict; detail: string }>
  effects: CounterfactualEffectEstimate[]
  severe_failures: string[]
  usage_state: CounterfactualValueState
  fidelity_level: CounterfactualFidelityLevel | null
  evidence_maturity: CounterfactualEvidenceMaturity
  semantic_diff: { affected_mechanisms: string[]; recommended_packs: string[]; classification_state: 'observed' | 'unknown' | 'multiple' }
  reproduction_command: string
  step_summary: string
  pr_comment_body: string
  claim_ceiling: string
  provider_execution_started: false
  execution_started: false
  network_requested: false
  idempotent_replay: boolean
}

export type ForgeOutcome = 'ADMITTED' | 'REJECTED' | 'QUARANTINED' | 'INCONCLUSIVE'

export interface ForgeProposalRequest {
  schema_version?: 'scaffold-arena.forge-proposal/1'
  proposal_id: string
  proposer_identity: string
  source_provenance_digest: string
  base_genome_digest: string
  candidate_genome_digest: string
  mechanism_change: { mechanism_id: string; base_mechanism_digest: string; candidate_mechanism_digest: string; patch_or_config_digest: string; declared_change_count: 1 }
  falsifiable_prediction: { metric_id: string; direction: 'increase' | 'decrease' | 'no_more_than'; threshold: number; prediction_digest: string }
  expected_tradeoff: { quality: 'improve' | 'regress' | 'neutral' | 'unknown'; safety: 'improve' | 'regress' | 'neutral' | 'unknown'; cost: 'increase' | 'decrease' | 'neutral' | 'unknown'; latency: 'increase' | 'decrease' | 'neutral' | 'unknown'; rationale_digest: string }
  triggering_evidence_digests: string[]
  rollback: { rollback_id: string; rollback_digest: string; recovery_plan_digest: string }
  requested_claim_scope: 'fixture_contract' | 'recorded_observation' | 'product_control'
  untrusted: true
  execution_requested: false
  automatic_merge_requested: false
  self_evaluation_requested: false
  scalar_optimization_requested: false
}

export interface ForgeProposalRecord {
  proposal_id: string
  proposal_digest: string
  proposal_artifact_digest: string
  state: 'PENDING_APPROVAL' | 'APPROVED' | 'REJECTED'
  proposal: ForgeProposalRequest
  claim_ceiling: string
  execution_started: false
  automatic_merge: false
  idempotent_replay: boolean
}

export interface ForgeApprovalRequest {
  schema_version?: 'scaffold-arena.forge-approval/1'
  proposal_digest: string
  approver_identity: string
  authority_kind: 'human' | 'policy'
  decision: 'APPROVED' | 'REJECTED'
  policy_digest: string
  decision_evidence_digest: string
  execution_authorized: false
  merge_authorized: false
}

export interface EvolutionReceipt {
  schema_version: 'scaffold-arena.evolution-receipt/1'
  receipt_id: string
  receipt_digest: string
  receipt_artifact_digest: string
  proposal_digest: string
  approval_digest: string
  evaluation_digest: string
  outcome: ForgeOutcome
  evaluator_identity: string
  admitting_identity: string
  claim_ceiling: string
  immutable: true
  execution_started: false
  automatic_merge: false
  idempotent_replay: boolean
}

export interface NextBestExperimentRequest {
  schema_version?: 'scaffold-arena.next-best-experiment/1'
  request_id: string
  mode: 'exploratory' | 'confirmatory'
  mechanisms: Array<{ mechanism_id: string; uncertainty: number; expected_effect: number; interaction_uncertainty?: number }>
  coverage: Array<{ coverage_id: string; fraction: number }>
  prior_evidence?: Array<{ evidence_digest: string; mechanism_id: string; evidence_strength: number }>
  candidate_designs: Array<{ design_id: string; mechanism_id: string; coverage_ids: string[]; cost_per_attempt_usd: number; minimum_attempts: number; maximum_attempts: number; risk: number; assumptions: string[] }>
  minimum_detectable_effect: number
  remaining_budget_usd: number
  maximum_risk: number
  frozen_analysis_plan_digest?: string | null
  exploratory_adaptation: boolean
  source_evidence_digests: string[]
  execution_requested: false
  automatic_admission_requested: false
}

export interface NextBestExperimentReport {
  schema_version: 'scaffold-arena.next-best-experiment-report/1'
  report_id: string
  report_digest: string
  report_artifact_digest: string
  request_digest: string
  mode: 'exploratory' | 'confirmatory'
  verdict: 'READY' | 'HOLD'
  recommendations: Array<{ rank: number; proposed_design: NextBestExperimentRequest['candidate_designs'][number]; expected_information_gain: number; attempts: number; cost_interval: { lower_usd: number; upper_usd: number }; risk: number; assumptions: string[]; claim_ceiling: string; alternatives: string[] }>
  excluded_designs: Array<{ design_id: string; reason: string }>
  claim_ceiling: string
  execution_started: false
  network_requested: false
  idempotent_replay: boolean
}

export interface ProcessSafetyRequest {
  schema_version?: 'scaffold-arena.process-safety/1'
  request_id: string
  policy: { policy_digest: string; maximum_sensitivity: 'PUBLIC' | 'INTERNAL' | 'CONFIDENTIAL' | 'RESTRICTED' | 'SECRET'; allowed_tool_digests: string[]; allow_external_egress: false; maximum_delegation_depth: number; secret_retention: 'digests_and_redacted_manifests_only'; required_cleanup: true }
  flows: Array<{ flow_id: string; source: 'context' | 'model' | 'tool' | 'memory' | 'artifact' | 'external'; destination: 'context' | 'model' | 'tool' | 'memory' | 'artifact' | 'external'; sensitivity: 'PUBLIC' | 'INTERNAL' | 'CONFIDENTIAL' | 'RESTRICTED' | 'SECRET'; content_digest?: string | null; redacted_manifest_digest?: string | null; tool_digest?: string | null; delegation_depth: number }>
  outcomes: Array<{ outcome_type: string; state: 'NOT_OBSERVED' | 'BLOCKED' | 'DETECTED' | 'UNKNOWN'; evidence_digest: string }>
  transitions: Array<{ from_state: string; to_state: string; transition_digest: string }>
  cleanup_receipt_digest?: string | null
  source_manifest_digest: string
  execution_started: false
  network_requested: false
}

export interface ProcessSafetyReport {
  schema_version: 'scaffold-arena.process-safety-report/1'
  report_id: string
  report_digest: string
  report_artifact_digest: string
  request_digest: string
  verdict: 'PASS' | 'HOLD' | 'FAIL'
  checks: Array<{ check_id: string; verdict: 'PASS' | 'HOLD' | 'FAIL'; detail: string }>
  retained_manifest_digests: string[]
  claim_ceiling: string
  raw_sensitive_content_retained: false
  execution_started: false
  network_requested: false
  idempotent_replay: boolean
}

export interface DownloadResult {
  blob: Blob
  filename?: string
  mediaType: string | null
  digests: Record<string, string>
}
