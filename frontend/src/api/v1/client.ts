import {
  ApiProblem,
  type AdjudicationSubmission,
  type AnalysisRequest,
  type AnalysisReportDetail,
  type AnalysisReportList,
  type AnalysisReportPageOptions,
  type AnnotationBatch,
  type AnnotationBatchCreated,
  type AnnotationBatchList,
  type AnnotationBatchPageOptions,
  type AnnotationBatchView,
  type AnnotationSubmission,
  type AssignmentView,
  type AttemptTraceView,
  type AttemptView,
  type ArenaSession,
  type DecisionBriefCreated,
  type DecisionBriefDetail,
  type DecisionBriefList,
  type DecisionBriefPageOptions,
  type DecisionAdmissionRequest,
  type DerivedEvidenceReceipt,
  type DerivedEvidenceRequest,
  type DeploymentReadiness,
  type DownloadResult,
  type EvidenceAdmissionRequest,
  type EvidenceList,
  type EvidencePageOptions,
  type EvidenceReceiptCreated,
  type EvidenceReceiptDetail,
  type EvidenceVerification,
  type ExecutionCreated,
  type ExecutionDetail,
  type ExecutionEvent,
  type ExecutionList,
  type ExecutionPageOptions,
  type ExecutionProvenance,
  type ExperimentDetail,
  type ExperimentSpec,
  type ExperimentSummary,
  type JsonObject,
  type PreflightReport,
  type ReproductionCreated,
  type ReproductionRequest,
  type RetentionPlan,
  type RetentionPreview,
  type StudyPackSummary,
  type StudyPackDetail,
  type TraceAnalysisRequest,
  type XRayRequest,
  type ObservatoryRequest,
  type XRayReport,
  type ObservatoryReport,
  type CounterfactualReplayRequest,
  type CounterfactualReplayReport,
  type HarnessCIRequest,
  type HarnessCIReport,
  type ForgeProposalRequest,
  type ForgeProposalRecord,
  type ForgeApprovalRequest,
  type EvolutionReceipt,
  type NextBestExperimentRequest,
  type NextBestExperimentReport,
  type ProcessSafetyRequest,
  type ProcessSafetyReport,
} from './types'

export * from './types'

const configuredBase = (import.meta.env.VITE_API_V1_BASE_URL as string | undefined)?.trim()
const BASE = configuredBase && configuredBase.length > 0 ? configuredBase.replace(/\/$/, '') : '/api/v1'

export interface ArenaV1Options {
  baseUrl?: string
  fetch?: typeof fetch
  projectId?: string
}

export interface RequestOptions {
  signal?: AbortSignal
  projectId?: string
  csrfToken?: string
}

export interface EventStreamOptions extends RequestOptions {
  cursor?: string
  reconnectAttempts?: number
}

function isObject(value: unknown): value is JsonObject {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function objectWith(value: unknown, ...keys: string[]): JsonObject {
  if (!isObject(value) || keys.some((key) => !(key in value))) {
    throw new TypeError('Malformed /api/v1 JSON response.')
  }
  return value
}

function query(path: string, values: Record<string, string | undefined>): string {
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(values)) if (value) params.set(key, value)
  const suffix = params.toString()
  return suffix ? `${path}?${suffix}` : path
}

function headers(projectId: string | undefined, extra?: HeadersInit, csrfToken?: string): Headers {
  const value = new Headers(extra)
  value.set('Accept', 'application/json')
  if (projectId) value.set('X-Arena-Project-ID', projectId)
  if (csrfToken) value.set('X-Arena-CSRF', csrfToken)
  return value
}

function filename(header: string | null): string | undefined {
  const match = header?.match(/filename="?([^";]+)"?/i)
  return match?.[1]
}

function isExecutionTerminal(event: ExecutionEvent, executionId: string): boolean {
  return event.event === 'terminal'
    && event.data.execution_id === executionId
    && typeof event.data.status === 'string'
    && /^(completed|failed|cancelled)$/.test(event.data.status)
}

export function createArenaV1(options: ArenaV1Options = {}) {
  const baseUrl = (options.baseUrl ?? BASE).replace(/\/$/, '')
  const requestFetch = options.fetch ?? fetch
  const project = (request: RequestOptions) => request.projectId ?? options.projectId
  let sessionCsrfToken: string | undefined
  const csrf = (request: RequestOptions) => request.csrfToken ?? sessionCsrfToken

  async function requestJson<T extends object>(path: string, init: RequestInit = {}, request: RequestOptions = {}, required: string[] = []): Promise<T> {
    const response = await requestFetch(`${baseUrl}${path}`, {
      ...init,
      signal: request.signal,
      credentials: 'include',
      headers: headers(project(request), init.headers, csrf(request)),
    })
    const text = await response.text()
    let body: unknown = undefined
    try { body = text ? JSON.parse(text) : undefined } catch { /* non-JSON errors retain their HTTP status */ }
    if (!response.ok) {
      const errorBody = isObject(body) ? body : {}
      throw new ApiProblem(response.status, errorBody, response.statusText || `HTTP ${response.status}`)
    }
    if (text && body === undefined) throw new TypeError('Malformed /api/v1 JSON response.')
    return objectWith(body, ...required) as unknown as T
  }

  function json(method: 'POST' | 'PATCH' | 'PUT', payload: object, request: RequestOptions, extra?: HeadersInit): RequestInit {
    const bodyHeaders = new Headers(extra)
    bodyHeaders.set('Content-Type', 'application/json')
    const csrfToken = csrf(request)
    if (csrfToken) bodyHeaders.set('X-Arena-CSRF', csrfToken)
    return { method, body: JSON.stringify(payload), headers: bodyHeaders, signal: request.signal }
  }

  async function download(payload: object, request: RequestOptions): Promise<DownloadResult> {
    const response = await requestFetch(`${baseUrl}/exports`, {
      ...json('POST', payload, request),
      credentials: 'include',
      headers: headers(project(request), { 'Content-Type': 'application/json', Accept: 'application/octet-stream' }, csrf(request)),
    })
    if (!response.ok) {
      const text = await response.text()
      let body: unknown = undefined
      try { body = text ? JSON.parse(text) : undefined } catch { /* error details remain unknown */ }
      throw new ApiProblem(response.status, isObject(body) ? body : {}, response.statusText || `HTTP ${response.status}`)
    }
    const digests: Record<string, string> = {}
    for (const [key, value] of response.headers.entries()) if (key.startsWith('x-') && (key.endsWith('-digest') || key.endsWith('-hash'))) digests[key] = value
    return { blob: await response.blob(), filename: filename(response.headers.get('Content-Disposition')), mediaType: response.headers.get('Content-Type'), digests }
  }

  async function* events(executionId: string, streamOptions: EventStreamOptions = {}): AsyncGenerator<ExecutionEvent> {
    let cursor = streamOptions.cursor
    let reconnects = 0
    const delivered = new Set<string>()
    const maxReconnects = streamOptions.reconnectAttempts ?? 3
    while (!streamOptions.signal?.aborted) {
      const eventHeaders = headers(project(streamOptions), { Accept: 'text/event-stream', ...(cursor ? { 'Last-Event-ID': cursor } : {}) }, csrf(streamOptions))
      let response: Response
      try {
        response = await requestFetch(
          `${baseUrl}${query(`/executions/${encodeURIComponent(executionId)}/events`, { cursor })}`,
          { method: 'GET', credentials: 'include', headers: eventHeaders, signal: streamOptions.signal },
        )
      } catch (error) {
        if (streamOptions.signal?.aborted) return
        if (reconnects++ >= maxReconnects) throw error
        continue
      }
      if (!response.ok) {
        const text = await response.text()
        let body: unknown = undefined
        try { body = text ? JSON.parse(text) : undefined } catch { /* unknown */ }
        throw new ApiProblem(response.status, isObject(body) ? body : {}, response.statusText || `HTTP ${response.status}`)
      }
      if (!response.body) throw new TypeError('Malformed SSE response: missing body.')
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let ended = false
      try {
        while (!ended) {
          const next = await reader.read()
          ended = next.done
          buffer += decoder.decode(next.value, { stream: !ended })
          let boundary = buffer.indexOf('\n\n')
          while (boundary >= 0) {
            const frame = buffer.slice(0, boundary)
            buffer = buffer.slice(boundary + 2)
            boundary = buffer.indexOf('\n\n')
            const parsed = parseSseFrame(frame, cursor)
            if (!parsed) continue
            cursor = parsed.cursor
            const logicalId = typeof parsed.data.event_id === 'string'
              ? parsed.data.event_id
              : parsed.event === 'terminal'
                ? `terminal:${String(parsed.data.execution_id)}:${String(parsed.data.status)}`
                : `${parsed.event}:${parsed.cursor}`
            if (delivered.has(logicalId)) continue
            delivered.add(logicalId)
            yield parsed
            if (isExecutionTerminal(parsed, executionId)) return
          }
        }
      } finally {
        reader.releaseLock()
      }
      if (streamOptions.signal?.aborted) return
      if (reconnects++ >= maxReconnects) {
        throw new TypeError('Execution event observation ended before an execution terminal event.')
      }
    }
  }

  return {
    auth: {
      session: async (request: RequestOptions = {}) => {
        const session = await requestJson<ArenaSession>('/session', {}, request, ['authenticated', 'mode'])
        sessionCsrfToken = typeof session.csrf_token === 'string' ? session.csrf_token : undefined
        return session
      },
      logout: async (request: RequestOptions = {}) => {
        const result = await requestJson<{ authenticated: false }>('/logout', json('POST', {}, request), request, ['authenticated'])
        sessionCsrfToken = undefined
        return result
      },
    },
    settings: {
      get: (request: RequestOptions = {}) => requestJson<DeploymentReadiness>('/settings', {}, request, ['deployment_profile', 'storage', 'authentication', 'adapters', 'budget', 'retention', 'secrets']),
      update: (payload: { retention_days?: number | null }, request: RequestOptions = {}) => requestJson<{ settings: JsonObject; retention: DeploymentReadiness['retention'] }>('/settings', json('PATCH', payload, request), request, ['settings', 'retention']),
    },
    retention: {
      preview: (projectId: string, request: RequestOptions = {}) => requestJson<RetentionPreview>(`/projects/${encodeURIComponent(projectId)}/retention/preview`, {}, { ...request, projectId }, ['project_id', 'snapshot_digest', 'confirmation_token', 'eligible_purge', 'claim_ceiling']),
      plans: (projectId: string, request: RequestOptions = {}) => requestJson<{ project_id: string; plans: RetentionPlan[]; claim_ceiling: string }>(`/projects/${encodeURIComponent(projectId)}/retention/plans`, {}, { ...request, projectId }, ['project_id', 'plans', 'claim_ceiling']),
      schedule: (projectId: string, payload: { snapshot_digest: string; confirmation_token: string; grace_seconds?: number }, request: RequestOptions = {}) => requestJson<{ plan_id: string; state: 'scheduled'; due_at: string; claim_ceiling: string }>(`/projects/${encodeURIComponent(projectId)}/retention/plans`, json('POST', payload, request), { ...request, projectId }, ['plan_id', 'state', 'due_at', 'claim_ceiling']),
      cancel: (projectId: string, planId: string, request: RequestOptions = {}) => requestJson<{ plan_id: string; state: 'cancelled' }>(`/projects/${encodeURIComponent(projectId)}/retention/plans/${encodeURIComponent(planId)}/cancel`, json('POST', {}, request), { ...request, projectId }, ['plan_id', 'state']),
      execute: (projectId: string, planId: string, request: RequestOptions = {}) => requestJson<{ plan_id: string; state: 'executed'; export_manifest_digest: string; claim_ceiling: string }>(`/projects/${encodeURIComponent(projectId)}/retention/plans/${encodeURIComponent(planId)}/execute`, json('POST', {}, request), { ...request, projectId }, ['plan_id', 'state', 'export_manifest_digest', 'claim_ceiling']),
    },
    studyPacks: {
      validate: (pack: BodyInit, contentType = 'application/json', request: RequestOptions = {}) => requestJson<JsonObject>('/study-packs/validate', { method: 'POST', body: pack, headers: { 'Content-Type': contentType }, signal: request.signal }, request, ['valid']),
      import: (pack: BodyInit, contentType = 'application/json', request: RequestOptions = {}) => requestJson<JsonObject>('/study-packs/import', { method: 'POST', body: pack, headers: { 'Content-Type': contentType }, signal: request.signal }, request),
      list: (request: RequestOptions = {}) => requestJson<JsonObject & { study_packs: StudyPackSummary[]; authority_ceiling: string }>('/study-packs', {}, request, ['study_packs', 'authority_ceiling']),
      get: (packKey: string, version: string, request: RequestOptions = {}) => requestJson<StudyPackDetail>(`/study-packs/${encodeURIComponent(packKey)}/versions/${encodeURIComponent(version)}`, {}, request, ['study_pack', 'canonical_study_pack', 'custody']),
    },
    experiments: {
      create: (payload: ExperimentSpec, request: RequestOptions = {}) => requestJson<JsonObject>('/experiments', json('POST', payload, request), request),
      list: (options: { studyPackId?: string; studyPackVersion?: string } = {}, request: RequestOptions = {}) => requestJson<JsonObject & { experiments: ExperimentSummary[] }>(query('/experiments', {
        study_pack_id: options.studyPackId,
        study_pack_version: options.studyPackVersion,
      }), {}, request, ['experiments']),
      get: (experimentId: string, request: RequestOptions = {}) => requestJson<ExperimentDetail>(`/experiments/${encodeURIComponent(experimentId)}`, {}, request, ['experiment_id', 'definition', 'immutable_identity']),
      freeze: (experimentId: string, request: RequestOptions = {}) => requestJson<JsonObject & { frozen: boolean }>(`/experiments/${encodeURIComponent(experimentId)}/freeze`, { method: 'POST', signal: request.signal }, request, ['frozen']),
      preflight: (experimentId: string, request: RequestOptions = {}) => requestJson<PreflightReport>(`/experiments/${encodeURIComponent(experimentId)}/preflight`, { method: 'POST', signal: request.signal }, request, ['verdict', 'blockers', 'study_pack_readiness']),
    },
    executions: {
      create: (experimentId: string, provenance: ExecutionProvenance, request: RequestOptions & { idempotencyKey?: string } = {}) => requestJson<ExecutionCreated>(`/experiments/${encodeURIComponent(experimentId)}/executions`, json('POST', provenance, request, request.idempotencyKey ? { 'Idempotency-Key': request.idempotencyKey } : undefined), request, ['execution_id', 'expected_attempts', 'job_ids']),
      list: (page: ExecutionPageOptions = {}, request: RequestOptions = {}) => requestJson<ExecutionList>(query('/executions', {
        experiment_id: page.experimentId,
        limit: page.limit?.toString(),
        offset: page.offset?.toString(),
      }), {}, request, ['executions', 'pagination', 'claim_ceiling']),
      get: (executionId: string, request: RequestOptions = {}) => requestJson<ExecutionDetail>(`/executions/${encodeURIComponent(executionId)}`, {}, request, ['execution_id', 'attempts', 'jobs', 'counts', 'claim_ceiling']),
      events,
      cancel: (executionId: string, request: RequestOptions = {}) => requestJson<JsonObject>(`/executions/${encodeURIComponent(executionId)}/cancel`, { method: 'POST', signal: request.signal }, request, ['execution_id', 'status']),
      resume: (executionId: string, request: RequestOptions = {}) => requestJson<JsonObject>(`/executions/${encodeURIComponent(executionId)}/resume`, { method: 'POST', signal: request.signal }, request, ['execution_id']),
    },
    offlineDemo: {
      start: (request: RequestOptions = {}) => requestJson<{ study_pack_id: string; version: string; idempotent_replay: boolean; execution_started: false; claim_ceiling: string }>('/offline-demo', { method: 'POST', signal: request.signal }, request, ['study_pack_id', 'version', 'execution_started']),
      execute: (experimentId: string, request: RequestOptions & { idempotencyKey?: string } = {}) => requestJson<ExecutionCreated & { fixture_execution_scheduled: boolean }>(`/offline-demo/experiments/${encodeURIComponent(experimentId)}/execute`, { method: 'POST', signal: request.signal, headers: request.idempotencyKey ? { 'Idempotency-Key': request.idempotencyKey } : undefined }, request, ['execution_id', 'expected_attempts', 'job_ids', 'fixture_execution_scheduled']),
    },
    attempts: {
      get: (attemptId: string, request: RequestOptions = {}) => requestJson<AttemptView>(`/attempts/${encodeURIComponent(attemptId)}`, {}, request, ['attempt_id', 'execution_id', 'status']),
      trace: (attemptId: string, request: RequestOptions = {}) => requestJson<AttemptTraceView>(`/attempts/${encodeURIComponent(attemptId)}/trace`, {}, request, ['attempt_id', 'events']),
    },
    review: {
      createBatch: (payload: AnnotationBatch, request: RequestOptions = {}) => requestJson<AnnotationBatchCreated>('/annotation-batches', json('POST', payload, request), request, ['batch_id', 'status', 'idempotent_replay']),
      list: (page: AnnotationBatchPageOptions = {}, request: RequestOptions = {}) => requestJson<AnnotationBatchList>(query('/annotation-batches', {
        status: page.status,
        limit: page.limit?.toString(),
        offset: page.offset?.toString(),
      }), {}, request, ['annotation_batches', 'pagination', 'identity_state', 'claim_ceiling']),
      getBatch: (batchId: string, annotatorPseudonym: string, request: RequestOptions = {}) => requestJson<AnnotationBatchView>(query(`/annotation-batches/${encodeURIComponent(batchId)}`, { annotator_pseudonym: annotatorPseudonym }), {}, request, ['batch_id', 'protocol_hash', 'status', 'assignments', 'claim_ceiling']),
      getAssignment: (batchId: string, assignmentId: string, annotatorPseudonym: string, request: RequestOptions = {}) => requestJson<AssignmentView>(query(`/annotation-batches/${encodeURIComponent(batchId)}/assignments/${encodeURIComponent(assignmentId)}`, { annotator_pseudonym: annotatorPseudonym }), {}, request, ['assignment_id', 'item_id', 'blind_payload_digest', 'blinded_content', 'claim_ceiling']),
      submitAnnotation: (batchId: string, payload: AnnotationSubmission, request: RequestOptions = {}) => requestJson<AnnotationBatchCreated>(`/annotation-batches/${encodeURIComponent(batchId)}/annotations`, json('POST', payload, request), request, ['batch_id', 'status', 'idempotent_replay']),
      submitAdjudication: (batchId: string, payload: AdjudicationSubmission, request: RequestOptions = {}) => requestJson<AnnotationBatchCreated>(`/annotation-batches/${encodeURIComponent(batchId)}/adjudications`, json('POST', payload, request), request, ['batch_id', 'status', 'idempotent_replay']),
    },
    analysis: (payload: AnalysisRequest, request: RequestOptions = {}) => requestJson<JsonObject>('/analysis', json('POST', payload, request), request, ['report_digest']),
    analysisReports: {
      list: (page: AnalysisReportPageOptions = {}, request: RequestOptions = {}) => requestJson<AnalysisReportList>(query('/analysis-reports', {
        experiment_id: page.experimentId,
        execution_id: page.executionId,
        limit: page.limit?.toString(),
        offset: page.offset?.toString(),
      }), {}, request, ['analysis_reports', 'pagination', 'integrity_not_truth', 'claim_ceiling']),
      get: (reportDigest: string, request: RequestOptions = {}) => requestJson<AnalysisReportDetail>(`/analysis-reports/${encodeURIComponent(reportDigest)}`, {}, request, [
        'report', 'binding', 'report_digest', 'artifact_digest', 'artifact_ref', 'source_digests', 'adequacy', 'claim_ceiling', 'integrity_not_truth',
      ]),
    },
    exports: {
      studyPack: (studyPackId: string, version: string, request: RequestOptions = {}) => download({ kind: 'study_pack', study_pack_id: studyPackId, version }, request),
      analysis: (reportDigest: string, format: 'csv' | 'parquet', request: RequestOptions = {}) => download({ kind: 'analysis', report_digest: reportDigest, format }, request),
    },
    evidence: {
      record: (payload: EvidenceAdmissionRequest, request: RequestOptions = {}) => requestJson<EvidenceReceiptCreated>('/evidence', json('POST', payload, request), request, ['receipt_id', 'integrity_not_truth', 'idempotent_replay']),
      list: (page: EvidencePageOptions = {}, request: RequestOptions = {}) => requestJson<EvidenceList>(query('/evidence', {
        execution_id: page.executionId,
        kind: page.kind,
        limit: page.limit?.toString(),
        offset: page.offset?.toString(),
      }), {}, request, ['evidence', 'pagination', 'integrity_not_truth', 'claim_ceiling']),
      derive: (payload: DerivedEvidenceRequest, request: RequestOptions = {}) => requestJson<DerivedEvidenceReceipt>('/evidence/derive', json('POST', payload, request), request, ['receipt_id', 'admission_workflow', 'integrity_not_truth', 'idempotent_replay']),
      get: (receiptId: string, request: RequestOptions = {}) => requestJson<EvidenceReceiptDetail>(`/evidence/${encodeURIComponent(receiptId)}`, {}, request, ['receipt_id', 'artifacts', 'integrity_not_truth']),
      verify: (receiptId: string, request: RequestOptions = {}) => requestJson<EvidenceVerification>(`/evidence/${encodeURIComponent(receiptId)}/verify`, { method: 'POST', signal: request.signal }, request, ['receipt_id', 'verified', 'errors', 'integrity_not_truth']),
      reproduce: (payload: ReproductionRequest, request: RequestOptions = {}) => requestJson<ReproductionCreated>('/reproductions', json('POST', payload, request), request, ['reproduction_receipt_id', 'integrity_not_truth', 'idempotent_replay']),
    },
    traceLab: {
      analyze: (payload: TraceAnalysisRequest, request: RequestOptions = {}) => requestJson<JsonObject>('/trace-analyses', json('POST', payload, request), request, ['analysis_digest']),
    },
    xray: {
      create: (payload: XRayRequest, request: RequestOptions = {}) => requestJson<XRayReport>('/xray-analyses', json('POST', payload, request), request, ['analysis_digest', 'report_digest', 'claim_ceiling', 'execution_started', 'network_requested']),
      get: (digest: string, request: RequestOptions = {}) => requestJson<XRayReport>(`/xray-analyses/${encodeURIComponent(digest)}`, {}, request, ['analysis_digest', 'report_digest', 'claim_ceiling', 'execution_started', 'network_requested']),
    },
    observatory: {
      create: (payload: ObservatoryRequest, request: RequestOptions = {}) => requestJson<ObservatoryReport>('/observatory-analyses', json('POST', payload, request), request, ['analysis_digest', 'report_digest', 'claim_ceiling', 'execution_started', 'network_requested']),
      get: (digest: string, request: RequestOptions = {}) => requestJson<ObservatoryReport>(`/observatory-analyses/${encodeURIComponent(digest)}`, {}, request, ['analysis_digest', 'report_digest', 'claim_ceiling', 'execution_started', 'network_requested']),
    },
    counterfactual: {
      create: (payload: CounterfactualReplayRequest, request: RequestOptions = {}) => requestJson<CounterfactualReplayReport>('/counterfactual-replays', json('POST', payload, request), request, ['report_digest', 'verdict', 'effects', 'claim_ceiling', 'provider_execution_started', 'execution_started', 'network_requested']),
      get: (digest: string, request: RequestOptions = {}) => requestJson<CounterfactualReplayReport>(`/counterfactual-replays/${encodeURIComponent(digest)}`, {}, request, ['report_digest', 'verdict', 'effects', 'claim_ceiling', 'provider_execution_started', 'execution_started', 'network_requested']),
    },
    harnessCi: {
      create: (payload: HarnessCIRequest, request: RequestOptions = {}) => requestJson<HarnessCIReport>('/harness-ci/checks', json('POST', payload, request), request, ['report_digest', 'verdict', 'checks', 'step_summary', 'pr_comment_body', 'claim_ceiling', 'provider_execution_started', 'execution_started', 'network_requested']),
      get: (digest: string, request: RequestOptions = {}) => requestJson<HarnessCIReport>(`/harness-ci/checks/${encodeURIComponent(digest)}`, {}, request, ['report_digest', 'verdict', 'checks', 'step_summary', 'pr_comment_body', 'claim_ceiling', 'provider_execution_started', 'execution_started', 'network_requested']),
    },
    forge: {
      proposals: {
        create: (payload: ForgeProposalRequest, request: RequestOptions = {}) => requestJson<ForgeProposalRecord>('/forge/proposals', json('POST', payload, request), request, ['proposal_digest', 'state', 'claim_ceiling', 'execution_started', 'automatic_merge']),
        get: (digest: string, request: RequestOptions = {}) => requestJson<ForgeProposalRecord>(`/forge/proposals/${encodeURIComponent(digest)}`, {}, request, ['proposal_digest', 'state', 'claim_ceiling', 'execution_started', 'automatic_merge']),
        approve: (digest: string, payload: ForgeApprovalRequest, request: RequestOptions = {}) => requestJson<{ proposal_digest: string; approval_digest: string; decision: 'APPROVED' | 'REJECTED'; execution_authorized: false; merge_authorized: false }>('/forge/proposals/' + encodeURIComponent(digest) + '/approval', json('POST', payload, request), request, ['proposal_digest', 'approval_digest', 'decision', 'execution_authorized', 'merge_authorized']),
      },
      evaluations: {
        create: (payload: JsonObject, request: RequestOptions = {}) => requestJson<EvolutionReceipt>('/forge/evaluations', json('POST', payload, request), request, ['receipt_digest', 'outcome', 'immutable', 'execution_started', 'automatic_merge']),
      },
      receipts: {
        get: (digest: string, request: RequestOptions = {}) => requestJson<EvolutionReceipt>(`/forge/evolution-receipts/${encodeURIComponent(digest)}`, {}, request, ['receipt_digest', 'outcome', 'immutable', 'execution_started', 'automatic_merge']),
      },
    },
    experimentPlanner: {
      create: (payload: NextBestExperimentRequest, request: RequestOptions = {}) => requestJson<NextBestExperimentReport>('/experiment-plans/next-best', json('POST', payload, request), request, ['report_digest', 'verdict', 'recommendations', 'excluded_designs', 'claim_ceiling', 'execution_started', 'network_requested']),
      get: (digest: string, request: RequestOptions = {}) => requestJson<NextBestExperimentReport>(`/experiment-plans/${encodeURIComponent(digest)}`, {}, request, ['report_digest', 'verdict', 'recommendations', 'excluded_designs', 'claim_ceiling', 'execution_started', 'network_requested']),
    },
    processSafety: {
      create: (payload: ProcessSafetyRequest, request: RequestOptions = {}) => requestJson<ProcessSafetyReport>('/process-safety-reports', json('POST', payload, request), request, ['report_digest', 'verdict', 'checks', 'claim_ceiling', 'raw_sensitive_content_retained', 'execution_started', 'network_requested']),
      get: (digest: string, request: RequestOptions = {}) => requestJson<ProcessSafetyReport>(`/process-safety-reports/${encodeURIComponent(digest)}`, {}, request, ['report_digest', 'verdict', 'checks', 'claim_ceiling', 'raw_sensitive_content_retained', 'execution_started', 'network_requested']),
    },
    decisionBriefs: {
      create: (payload: DecisionAdmissionRequest, request: RequestOptions = {}) => requestJson<DecisionBriefCreated>('/decision-briefs', json('POST', payload, request), request, ['decision_brief_id', 'claim_refs', 'integrity_not_truth', 'idempotent_replay']),
      list: (page: DecisionBriefPageOptions = {}, request: RequestOptions = {}) => requestJson<DecisionBriefList>(query('/decision-briefs', {
        execution_id: page.executionId,
        report_digest: page.reportDigest,
        verdict: page.verdict,
        limit: page.limit?.toString(),
        offset: page.offset?.toString(),
      }), {}, request, ['decision_briefs', 'pagination', 'integrity_not_truth', 'claim_ceiling']),
      get: (decisionId: string, request: RequestOptions = {}) => requestJson<DecisionBriefDetail>(`/decision-briefs/${encodeURIComponent(decisionId)}`, {}, request, ['decision_brief_id', 'claim_refs', 'artifact_content', 'integrity_not_truth']),
    },
  }
}

function parseSseFrame(frame: string, currentCursor: string | undefined): ExecutionEvent | undefined {
  const lines = frame.replace(/\r/g, '').split('\n')
  const id = lines.find((line) => line.startsWith('id:'))?.slice(3).trim()
  const event = lines.find((line) => line.startsWith('event:'))?.slice(6).trim()
  const data = lines.filter((line) => line.startsWith('data:')).map((line) => line.slice(5).trim()).join('\n')
  if (!event || !data || (!id && event !== 'terminal')) return undefined
  let payload: unknown
  try { payload = JSON.parse(data) } catch { throw new TypeError('Malformed SSE event payload.') }
  const body = objectWith(payload)
  return {
    cursor: id ?? currentCursor ?? '',
    event,
    data: body,
    ...(typeof body.event_id === 'string' ? { event_id: body.event_id } : {}),
  }
}

export const arenaV1 = createArenaV1()
