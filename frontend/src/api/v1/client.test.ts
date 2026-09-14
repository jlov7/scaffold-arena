import { describe, expect, it, vi } from 'vitest'

import { ApiProblem, createArenaV1 } from './client'

const jsonResponse = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const streamResponse = (chunks: string[]) => new Response(new ReadableStream({
  start(controller) {
    for (const chunk of chunks) controller.enqueue(new TextEncoder().encode(chunk))
    controller.close()
  },
}))

describe('arenaV1', () => {
  it('uses the canonical URL, JSON body, project and idempotency headers', async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(jsonResponse({ execution_id: 'exec-1', expected_attempts: 1, job_ids: [] }))
    const client = createArenaV1({ baseUrl: 'https://arena.test/api/v1', fetch: fetchMock, projectId: 'personal' })
    await client.executions.create('experiment one', {
      code_revision: 'r1', code_hash: 'a'.repeat(64), runtime_image: 'image', runtime_image_hash: 'b'.repeat(64), environment_hash: 'c'.repeat(64), prompt_hash: 'd'.repeat(64), context_hash: 'e'.repeat(64), tool_hash: 'f'.repeat(64), source_refs: [{ source_uri: 'synthetic://source', content_hash: '0'.repeat(64) }], captured_at: '2026-08-14T00:00:00Z',
    }, { idempotencyKey: 'request-1' })
    expect(fetchMock).toHaveBeenCalledWith('https://arena.test/api/v1/experiments/experiment%20one/executions', expect.objectContaining({ method: 'POST' }))
    const init = fetchMock.mock.calls[0]?.[1] as RequestInit
    expect(new Headers(init.headers).get('Idempotency-Key')).toBe('request-1')
    expect(new Headers(init.headers).get('X-Arena-Project-ID')).toBe('personal')
    expect(init.body).toContain('"code_revision":"r1"')
    expect(init.credentials).toBe('include')
  })

  it('keeps the server session CSRF token in memory and applies it to cookie-authenticated mutations', async () => {
    const fetchMock = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ authenticated: true, mode: 'team', csrf_token: 'csrf-mem' }))
      .mockResolvedValueOnce(jsonResponse({ execution_id: 'exec-1', expected_attempts: 1, job_ids: [] }))
      .mockResolvedValueOnce(jsonResponse({ authenticated: false }))
    const client = createArenaV1({ baseUrl: '/api/v1', fetch: fetchMock, projectId: 'project-one' })
    await client.auth.session()
    await client.executions.create('experiment-1', {
      code_revision: 'r1', code_hash: 'a'.repeat(64), runtime_image: 'image', runtime_image_hash: 'b'.repeat(64), environment_hash: 'c'.repeat(64), prompt_hash: 'd'.repeat(64), context_hash: 'e'.repeat(64), tool_hash: 'f'.repeat(64), source_refs: [{ source_uri: 'synthetic://source', content_hash: '0'.repeat(64) }], captured_at: '2026-08-14T00:00:00Z',
    })
    await client.auth.logout()
    const createInit = fetchMock.mock.calls[1]?.[1] as RequestInit
    const logoutInit = fetchMock.mock.calls[2]?.[1] as RequestInit
    expect(new Headers(createInit.headers).get('X-Arena-CSRF')).toBe('csrf-mem')
    expect(new Headers(logoutInit.headers).get('X-Arena-CSRF')).toBe('csrf-mem')
    expect([createInit, logoutInit]).toEqual(expect.arrayContaining([expect.objectContaining({ credentials: 'include' })]))
  })

  it('uses the project-scoped recoverable retention contracts', async () => {
    const digest = 'a'.repeat(64)
    const fetchMock = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ project_id: 'project-one', snapshot_digest: digest, confirmation_token: 'b'.repeat(64), retention_days: 30, eligible_purge: { idempotency_records: 1, artifact_bytes: 0 }, immutable_exclusions: [], claim_ceiling: 'archival only' }))
      .mockResolvedValueOnce(jsonResponse({ plan_id: 'plan-one', state: 'scheduled', due_at: '2026-08-14T00:01:00Z', claim_ceiling: 'archival only' }))
    const client = createArenaV1({ baseUrl: '/api/v1', fetch: fetchMock, projectId: 'project-one' })
    const preview = await client.retention.preview('project-one')
    await client.retention.schedule('project-one', { snapshot_digest: preview.snapshot_digest, confirmation_token: preview.confirmation_token, grace_seconds: 60 }, { csrfToken: 'csrf' })
    expect(fetchMock.mock.calls.map(([url, init]) => [url, (init as RequestInit).method ?? 'GET'])).toEqual([
      ['/api/v1/projects/project-one/retention/preview', 'GET'],
      ['/api/v1/projects/project-one/retention/plans', 'POST'],
    ])
    expect(new Headers((fetchMock.mock.calls[1]?.[1] as RequestInit).headers).get('X-Arena-CSRF')).toBe('csrf')
  })

  it('preserves a 409 HOLD without fabricating error details', async () => {
    const client = createArenaV1({ fetch: vi.fn<typeof fetch>().mockResolvedValue(jsonResponse({ verdict: 'HOLD', error: { code: 'preflight_hold', message: 'blocked' } }, 409)) })
    await expect(client.executions.resume('exec-1')).rejects.toMatchObject({ status: 409, code: 'preflight_hold', verdict: 'HOLD', isHold: true, details: undefined } satisfies Partial<ApiProblem>)
  })

  it('preserves an HTTP failure when its body is not JSON', async () => {
    const client = createArenaV1({ fetch: vi.fn<typeof fetch>().mockResolvedValue(new Response('upstream unavailable', { status: 503, statusText: 'Service Unavailable' })) })
    await expect(client.studyPacks.list()).rejects.toMatchObject({ name: 'ApiProblem', status: 503, code: undefined, details: undefined })
  })

  it('uses the provider-free counterfactual replay and Harness CI mutation boundaries', async () => {
    const fetchMock = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ report_digest: `sha256:${'a'.repeat(64)}`, verdict: 'HOLD', effects: [], claim_ceiling: 'fixture only', provider_execution_started: false, execution_started: false, network_requested: false }))
      .mockResolvedValueOnce(jsonResponse({ report_digest: `sha256:${'b'.repeat(64)}`, verdict: 'HOLD', checks: [], step_summary: 'summary', pr_comment_body: 'comment', claim_ceiling: 'policy only', provider_execution_started: false, execution_started: false, network_requested: false }))
    const client = createArenaV1({ baseUrl: '/api/v1', fetch: fetchMock, projectId: 'personal' })
    await client.counterfactual.create({ mode: 'fixture' } as never)
    await client.harnessCi.create({ replay_report_digest: `sha256:${'a'.repeat(64)}` } as never)
    expect(fetchMock.mock.calls.map(([url, init]) => [url, (init as RequestInit).method])).toEqual([
      ['/api/v1/counterfactual-replays', 'POST'],
      ['/api/v1/harness-ci/checks', 'POST'],
    ])
    for (const [, init] of fetchMock.mock.calls) expect(new Headers((init as RequestInit).headers).get('X-Arena-Project-ID')).toBe('personal')
  })

  it('uses project-scoped Forge, planner, and process-safety boundaries without an execution endpoint', async () => {
    const fetchMock = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ proposal_digest: `sha256:${'a'.repeat(64)}`, state: 'PENDING_APPROVAL', claim_ceiling: 'controls only', execution_started: false, automatic_merge: false }))
      .mockResolvedValueOnce(jsonResponse({ receipt_digest: `sha256:${'d'.repeat(64)}`, outcome: 'INCONCLUSIVE', immutable: true, execution_started: false, automatic_merge: false }))
      .mockResolvedValueOnce(jsonResponse({ report_digest: `sha256:${'b'.repeat(64)}`, verdict: 'READY', recommendations: [], excluded_designs: [], claim_ceiling: 'planner only', execution_started: false, network_requested: false }))
      .mockResolvedValueOnce(jsonResponse({ report_digest: `sha256:${'c'.repeat(64)}`, verdict: 'PASS', checks: [], claim_ceiling: 'controls only', raw_sensitive_content_retained: false, execution_started: false, network_requested: false }))
    const client = createArenaV1({ baseUrl: '/api/v1', fetch: fetchMock, projectId: 'personal' })
    await client.forge.proposals.create({ proposal_id: 'fixture-proposal' } as never)
    await client.forge.evaluations.create({ proposal_digest: `sha256:${'a'.repeat(64)}` })
    await client.experimentPlanner.create({ request_id: 'fixture-plan' } as never)
    await client.processSafety.create({ request_id: 'fixture-safety' } as never)
    expect(fetchMock.mock.calls.map(([url, init]) => [url, (init as RequestInit).method])).toEqual([
      ['/api/v1/forge/proposals', 'POST'],
      ['/api/v1/forge/evaluations', 'POST'],
      ['/api/v1/experiment-plans/next-best', 'POST'],
      ['/api/v1/process-safety-reports', 'POST'],
    ])
    for (const [, init] of fetchMock.mock.calls) expect(new Headers((init as RequestInit).headers).get('X-Arena-Project-ID')).toBe('personal')
  })

  it('passes abort signals to fetch', async () => {
    const controller = new AbortController()
    const fetchMock = vi.fn<typeof fetch>().mockRejectedValue(new DOMException('Aborted', 'AbortError'))
    const client = createArenaV1({ fetch: fetchMock })
    controller.abort()
    await expect(client.studyPacks.list({ signal: controller.signal })).rejects.toThrow('Aborted')
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({ signal: controller.signal })
  })

  it('rejects malformed successful JSON at the boundary', async () => {
    const client = createArenaV1({ fetch: vi.fn<typeof fetch>().mockResolvedValue(jsonResponse([])) })
    await expect(client.studyPacks.list()).rejects.toThrow('Malformed /api/v1 JSON response.')
  })

  it('uses read-only recovery routes with their exact filters and bounded pagination fields', async () => {
    const fetchMock = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ study_pack: {}, canonical_study_pack: {}, custody: {} }))
      .mockResolvedValueOnce(jsonResponse({ experiments: [] }))
      .mockResolvedValueOnce(jsonResponse({ experiment_id: 'experiment-1', definition: {}, immutable_identity: {} }))
      .mockResolvedValueOnce(jsonResponse({ executions: [], pagination: { limit: 1, offset: 0, next_offset: null }, claim_ceiling: 'status only' }))
      .mockResolvedValueOnce(jsonResponse({ execution_id: 'execution-1', attempts: [], jobs: [], counts: {}, claim_ceiling: 'status only' }))
      .mockResolvedValueOnce(jsonResponse({ analysis_reports: [], pagination: { limit: 1, offset: 0, next_offset: null }, integrity_not_truth: true, claim_ceiling: 'report-specific' }))
      .mockResolvedValueOnce(jsonResponse({ report: {}, binding: {}, report_digest: 'a'.repeat(64), artifact_digest: 'a'.repeat(64), artifact_ref: `sha256:${'a'.repeat(64)}`, source_digests: {}, adequacy: {}, claim_ceiling: 'DESCRIPTIVE_ONLY', integrity_not_truth: true }))
    const client = createArenaV1({ baseUrl: '/api/v1', fetch: fetchMock })
    await client.studyPacks.get('pack one', '1.0.0')
    await client.experiments.list({ studyPackId: 'pack-one', studyPackVersion: '1.0.0' })
    await client.experiments.get('experiment-1')
    await client.executions.list({ experimentId: 'experiment-1', limit: 1, offset: 0 })
    await client.executions.get('execution-1')
    await client.analysisReports.list({ experimentId: 'experiment-1', executionId: 'execution-1', limit: 1, offset: 0 })
    await client.analysisReports.get('a/b')
    expect(fetchMock.mock.calls.map(([url, init]) => [url, (init as RequestInit).method ?? 'GET'])).toEqual([
      ['/api/v1/study-packs/pack%20one/versions/1.0.0', 'GET'],
      ['/api/v1/experiments?study_pack_id=pack-one&study_pack_version=1.0.0', 'GET'],
      ['/api/v1/experiments/experiment-1', 'GET'],
      ['/api/v1/executions?experiment_id=experiment-1&limit=1&offset=0', 'GET'],
      ['/api/v1/executions/execution-1', 'GET'],
      ['/api/v1/analysis-reports?experiment_id=experiment-1&execution_id=execution-1&limit=1&offset=0', 'GET'],
      ['/api/v1/analysis-reports/a%2Fb', 'GET'],
    ])
  })

  it('preserves an analysis-report integrity HOLD as an ApiProblem', async () => {
    const client = createArenaV1({ fetch: vi.fn<typeof fetch>().mockResolvedValue(jsonResponse({
      verdict: 'HOLD', error: { code: 'analysis_report_integrity_error', message: 'cannot verify' },
    }, 409)) })
    await expect(client.analysisReports.get('a'.repeat(64))).rejects.toMatchObject({
      status: 409,
      code: 'analysis_report_integrity_error',
      verdict: 'HOLD',
      isHold: true,
    } satisfies Partial<ApiProblem>)
  })

  it('uses project-scoped review, evidence, and decision recovery endpoints with exact filters', async () => {
    const fetchMock = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ annotation_batches: [], pagination: {}, identity_state: 'identity_unverified', claim_ceiling: 'protocol only' }))
      .mockResolvedValueOnce(jsonResponse({ batch_id: 'batch-1', protocol_hash: 'a'.repeat(64), status: 'PENDING', assignments: [], claim_ceiling: 'protocol only' }))
      .mockResolvedValueOnce(jsonResponse({ assignment_id: 'assignment-1', item_id: 'item-1', blind_payload_digest: 'a'.repeat(64), blinded_content: {}, claim_ceiling: 'protocol only' }))
      .mockResolvedValueOnce(jsonResponse({ evidence: [], pagination: {}, integrity_not_truth: true, claim_ceiling: 'custody only' }))
      .mockResolvedValueOnce(jsonResponse({ receipt_id: 'receipt-1', artifacts: [], integrity_not_truth: true }))
      .mockResolvedValueOnce(jsonResponse({ receipt_id: 'receipt-1', verified: true, errors: [], integrity_not_truth: true }))
      .mockResolvedValueOnce(jsonResponse({ decision_briefs: [], pagination: {}, integrity_not_truth: true, claim_ceiling: 'brief only' }))
      .mockResolvedValueOnce(jsonResponse({ decision_brief_id: 'decision-1', claim_refs: [], artifact_content: 'withheld', integrity_not_truth: true }))
    const client = createArenaV1({ baseUrl: '/api/v1', fetch: fetchMock, projectId: 'personal' })
    await client.review.list({ status: 'PENDING', limit: 1, offset: 0 })
    await client.review.getBatch('batch/1', 'red')
    await client.review.getAssignment('batch/1', 'assignment/1', 'red')
    await client.evidence.list({ executionId: 'execution-1', kind: 'derived_fixture', limit: 1, offset: 0 })
    await client.evidence.get('receipt/1')
    await client.evidence.verify('receipt/1')
    await client.decisionBriefs.list({ executionId: 'execution-1', reportDigest: 'a'.repeat(64), verdict: 'HOLD', limit: 1, offset: 0 })
    await client.decisionBriefs.get('decision/1')
    expect(fetchMock.mock.calls.map(([url, init]) => [url, (init as RequestInit).method ?? 'GET'])).toEqual([
      ['/api/v1/annotation-batches?status=PENDING&limit=1&offset=0', 'GET'],
      ['/api/v1/annotation-batches/batch%2F1?annotator_pseudonym=red', 'GET'],
      ['/api/v1/annotation-batches/batch%2F1/assignments/assignment%2F1?annotator_pseudonym=red', 'GET'],
      ['/api/v1/evidence?execution_id=execution-1&kind=derived_fixture&limit=1&offset=0', 'GET'],
      ['/api/v1/evidence/receipt%2F1', 'GET'],
      ['/api/v1/evidence/receipt%2F1/verify', 'POST'],
      [`/api/v1/decision-briefs?execution_id=execution-1&report_digest=${'a'.repeat(64)}&verdict=HOLD&limit=1&offset=0`, 'GET'],
      ['/api/v1/decision-briefs/decision%2F1', 'GET'],
    ])
    for (const [, init] of fetchMock.mock.calls) expect(new Headers((init as RequestInit).headers).get('X-Arena-Project-ID')).toBe('personal')
  })

  it('posts exact review, evidence, and decision mutation contracts', async () => {
    const fetchMock = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ batch_id: 'batch-1', status: 'PENDING', idempotent_replay: false }))
      .mockResolvedValueOnce(jsonResponse({ batch_id: 'batch-1', status: 'IN_REVIEW', idempotent_replay: false }))
      .mockResolvedValueOnce(jsonResponse({ batch_id: 'batch-1', status: 'COMPLETE', idempotent_replay: false }))
      .mockResolvedValueOnce(jsonResponse({ receipt_id: 'derived-1', admission_workflow: 'derived_execution', integrity_not_truth: true, idempotent_replay: false }))
      .mockResolvedValueOnce(jsonResponse({ reproduction_receipt_id: 'reproduction-1', integrity_not_truth: true, idempotent_replay: false }))
      .mockResolvedValueOnce(jsonResponse({ decision_brief_id: 'decision-1', claim_refs: [], integrity_not_truth: true, idempotent_replay: false }))
    const client = createArenaV1({ baseUrl: '/api/v1', fetch: fetchMock })
    const digest = 'a'.repeat(64)
    await client.review.createBatch({
      batch_id: 'batch-1', protocol_hash: digest,
      evaluator: { evaluator_id: 'evaluator', version: '1', digest },
      grader_plan: { bindings: [
        { metric_id: 'deterministic', weight: 0.7, kind: 'deterministic', installation: { grader_id: 'deterministic', version: '1', digest } },
        { metric_id: 'quality', weight: 0.3, kind: 'qualitative', installation: { grader_id: 'qualitative', version: '1', digest } },
      ] },
      rubric: { rubric_id: 'rubric', version: '1', digest, dimensions: [{ metric_id: 'quality', instruction: 'Rate quality.', anchor_0: 'Poor', anchor_1: 'Strong' }] },
      annotator_pseudonyms: ['red', 'blue', 'green'], items: [{ item_id: 'item-1', attempt_id: 'attempt-1' }],
    })
    await client.review.submitAnnotation('batch-1', { assignment_id: 'assignment-1', annotator_pseudonym: 'red', dimension_scores: { quality: 0.5 } })
    await client.review.submitAdjudication('batch-1', { item_id: 'item-1', adjudicator_pseudonym: 'lead', final_scores: { quality: 0.5 }, decision: 'accept', rationale: 'bound evidence', evidence_artifact_digest: digest })
    await client.evidence.derive({ execution_id: 'execution-1', request_key: 'request-1' })
    await client.evidence.reproduce({
      receipt: { receipt_id: 'reproduction-1', original_operator_id: 'original-operator', original_authority_id: 'original-authority', reproducer_operator_id: 'reproducer-operator', reproducer_authority_id: 'reproducer-authority', original_environment_hash: digest, reproducer_environment_hash: digest, original_manifest_hash: digest, reproduced_manifest_hash: digest },
      original_evidence_receipt_id: 'receipt-1', reproduced_evidence_receipt_id: 'receipt-2', external_attestation: null,
    })
    await client.decisionBriefs.create({
      analysis_report_id: 'report-1',
      risk_constraints: { severe_failure_disposition: 'HOLD', require_zero_exclusions: true, require_estimated_effect_for_effect_claims: true, maximum_claim_ceiling: 'independent' },
      proposed_claims: [{ claim_id: 'claim-1', statement: 'A fixture observation was recorded.', kind: 'fixture_observation', linked_receipt_ids: ['receipt-1'] }],
    })
    expect(fetchMock.mock.calls.map(([url, init]) => [url, (init as RequestInit).method])).toEqual([
      ['/api/v1/annotation-batches', 'POST'],
      ['/api/v1/annotation-batches/batch-1/annotations', 'POST'],
      ['/api/v1/annotation-batches/batch-1/adjudications', 'POST'],
      ['/api/v1/evidence/derive', 'POST'],
      ['/api/v1/reproductions', 'POST'],
      ['/api/v1/decision-briefs', 'POST'],
    ])
    expect((fetchMock.mock.calls[5]?.[1] as RequestInit).body).toContain('"analysis_report_id":"report-1"')
  })

  it('preserves read-model integrity HOLD errors', async () => {
    const client = createArenaV1({ fetch: vi.fn<typeof fetch>().mockResolvedValue(jsonResponse({
      verdict: 'HOLD', error: { code: 'evidence_integrity_hold', message: 'cannot verify' },
    }, 409)) })
    await expect(client.evidence.list()).rejects.toMatchObject({
      status: 409, code: 'evidence_integrity_hold', verdict: 'HOLD', isHold: true,
    } satisfies Partial<ApiProblem>)
  })

  it('reconnects GET-only SSE, preserves attempt terminals, and stops only at the execution terminal', async () => {
    const fetchMock = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(streamResponse(['id: 1\nevent: queued\ndata: {"event_id":"event-1"}\n\n']))
      .mockResolvedValueOnce(streamResponse(['id: 1\nevent: queued\ndata: {"event_id":"event-1"}\n\nid: 2\nevent: terminal\ndata: {"event_id":"attempt-terminal","attempt_id":"attempt-1","status":"completed"}\n\nevent: terminal\ndata: {"execution_id":"exec-1","status":"cancelled"}\n\n']))
    const client = createArenaV1({ baseUrl: '/api/v1', fetch: fetchMock })
    const received = []
    for await (const event of client.executions.events('exec-1', { reconnectAttempts: 2 })) received.push(event)
    expect(received.map((event) => [event.event, event.data.event_id ?? event.data.execution_id])).toEqual([
      ['queued', 'event-1'],
      ['terminal', 'attempt-terminal'],
      ['terminal', 'exec-1'],
    ])
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(fetchMock.mock.calls[1]?.[0]).toBe('/api/v1/executions/exec-1/events?cursor=1')
    expect(new Headers((fetchMock.mock.calls[1]?.[1] as RequestInit).headers).get('Last-Event-ID')).toBe('1')
    expect((fetchMock.mock.calls[0]?.[1] as RequestInit).method).toBe('GET')
  })

  it('reports a stream that ends before the execution terminal', async () => {
    const client = createArenaV1({
      baseUrl: '/api/v1',
      fetch: vi.fn<typeof fetch>().mockResolvedValue(streamResponse([
        'id: 1\nevent: terminal\ndata: {"event_id":"attempt-terminal","attempt_id":"attempt-1","status":"completed"}\n\n',
      ])),
    })
    const collect = async () => {
      for await (const event of client.executions.events('exec-1', { reconnectAttempts: 0 })) void event
    }
    await expect(collect()).rejects.toThrow('ended before an execution terminal event')
  })
})
