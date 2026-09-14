# API reference

The FastAPI OpenAPI document is the authoritative request and response schema. Run the backend and open `/docs` or `/openapi.json` for field-level definitions. It is generated from the runtime routes and strict models, so the repository does not maintain a second checked-in OpenAPI copy that could drift from the served contract.

Base URL: `http://localhost:8000`

## Operational endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Process liveness. |
| `GET` | `/ready` | Narrow runtime and storage readiness. |
| `GET` | `/build-meta` | Non-secret, non-cacheable application/protocol/build identity for frontend–backend deployment-coherence checks. |
| `GET` | `/metrics` | Bounded operational metrics without secrets or user identifiers. |

`GET /build-meta` is intentionally outside the authenticated product API so the browser can compare its own complete build SHA with the backend in both personal and team deployments. Its fields are limited to schema version, application version, protocol version, complete Git SHA or `dev`, build environment, and build time. A matching SHA establishes deployment coherence only; it does not establish correct configuration, scientific validity, security assurance, or independent reproduction. See [deployment coherence](ops/deployment-coherence.md).

## Protocol-v1 resources

### Studies and experiments

| Method | Path |
| --- | --- |
| `POST` | `/api/v1/study-packs/validate` |
| `POST` | `/api/v1/study-packs/import` |
| `GET` | `/api/v1/study-packs` |
| `GET` | `/api/v1/study-packs/{pack_key}/versions/{version}` |
| `POST` | `/api/v1/experiments` |
| `GET` | `/api/v1/experiments` |
| `GET` | `/api/v1/experiments/{experiment_id}` |
| `POST` | `/api/v1/experiments/{experiment_id}/freeze` |
| `POST` | `/api/v1/experiments/{experiment_id}/preflight` |

### Execution and traces

| Method | Path |
| --- | --- |
| `POST` | `/api/v1/experiments/{experiment_id}/executions` |
| `GET` | `/api/v1/executions` |
| `GET` | `/api/v1/executions/{execution_id}` |
| `GET` | `/api/v1/executions/{execution_id}/events` |
| `POST` | `/api/v1/executions/{execution_id}/cancel` |
| `POST` | `/api/v1/executions/{execution_id}/resume` |
| `GET` | `/api/v1/attempts/{attempt_id}` |
| `GET` | `/api/v1/attempts/{attempt_id}/trace` |
| `POST` | `/api/v1/trace-analyses` |

The event stream is GET-only. Resume with the last persisted integer event cursor; clients must deduplicate terminal markers.

### Evaluation, analysis, and review

| Method | Path |
| --- | --- |
| `POST` | `/api/v1/analysis` |
| `GET` | `/api/v1/analysis-reports` |
| `GET` | `/api/v1/analysis-reports/{report_digest}` |
| `POST` | `/api/v1/annotation-batches` |
| `GET` | `/api/v1/annotation-batches` |
| `GET` | `/api/v1/annotation-batches/{batch_id}` |
| `GET` | `/api/v1/annotation-batches/{batch_id}/assignments/{assignment_id}` |
| `POST` | `/api/v1/annotation-batches/{batch_id}/annotations` |
| `POST` | `/api/v1/annotation-batches/{batch_id}/adjudications` |

### Harness X-Ray and observatory

| Method | Path |
| --- | --- |
| `POST` | `/api/v1/xray/validate` |
| `POST` | `/api/v1/xray/snapshots` |
| `GET` | `/api/v1/xray/snapshots` |
| `GET` | `/api/v1/xray/snapshots/{snapshot_id}` |
| `POST` | `/api/v1/xray-analyses` |
| `GET` | `/api/v1/xray-analyses/{report_digest}` |
| `POST` | `/api/v1/observatory-analyses` |
| `GET` | `/api/v1/observatory-analyses/{report_digest}` |

The snapshot registry stores strict, content-addressed static captures and exposes project-scoped summaries. Guided X-Ray discovers only those durable captures, keeps raw artifact identities hidden, and fixes source profiling to `auto`; Lab mode may inspect an existing immutable artifact digest and explicitly declare a static source kind.

`POST /xray-analyses` accepts only an already captured SHA-256 artifact and a declared static source kind; it cannot take a local path, source text, URL, command, or provider configuration. It never executes or fetches that source. `POST /observatory-analyses` accepts only named persisted attempt IDs, an optional project-visible X-Ray report digest, and an optional captured source-artifact digest; partial reconstruction is disabled by contract. Both reports are content-addressed and redact raw source and event payloads. The `/api/v1/xray/reports` and `/api/v1/observatory/reports` aliases remain available; the latter dispatches a digest to the analysis report and an ordinary report id to the legacy single-attempt ledger.

### Counterfactual Replay and Harness CI

| Method | Path |
| --- | --- |
| `POST` | `/api/v1/counterfactual-replays` |
| `GET` | `/api/v1/counterfactual-replays/{report_digest}` |
| `POST` | `/api/v1/harness-ci/checks` |
| `GET` | `/api/v1/harness-ci/checks/{report_digest}` |

Counterfactual Replay accepts only a strict, checkpointed paired-record contract; it is provider-free and cannot execute a source or a model. Harness CI evaluates an existing project-visible replay against source digest and policy bindings, returning JSON plus step-summary and PR-comment body text without posting a comment. Unknown usage remains unknown, and `PASS` is a bounded policy result rather than causal, deployment, model-performance, or independent-assurance evidence. Compatibility aliases are `/api/v1/counterfactual/replays` and `/api/v1/harness-ci-reports`.

### Arena Forge, next-best-experiment planning, and process safety

| Method | Path |
| --- | --- |
| `POST` | `/api/v1/forge/proposals` |
| `GET` | `/api/v1/forge/proposals/{proposal_digest}` |
| `POST` | `/api/v1/forge/proposals/{proposal_digest}/approval` |
| `POST` | `/api/v1/forge/evaluations` |
| `GET` | `/api/v1/forge/evolution-receipts/{receipt_digest}` |
| `POST` | `/api/v1/experiment-plans/next-best` |
| `GET` | `/api/v1/experiment-plans/{report_digest}` |
| `POST` | `/api/v1/process-safety-reports` |
| `GET` | `/api/v1/process-safety-reports/{report_digest}` |

Forge records untrusted candidate proposals, not executable patch instructions. Proposal approval is distinct from the proposer and, in team mode, requires an administrator role; it grants no execution or merge authority. Evaluation requires independent approved custody, a distinct evaluator/admitter, a project-scoped PASS process-safety report, frozen evaluation/analysis bindings, retained failures, and all four matched controls. The sealed holdout is represented only by sealed manifest and runner receipt digests. Planner reports rank declared designs under explicit budget/risk constraints but do not execute them. Process-safety reports retain digests or redacted manifests rather than raw sensitive content and fail closed for data scope, tools, egress, delegation, secrets, unsafe transitions, retry bypass, and cleanup. See [Arena Forge v1](arena-forge-planner-process-safety-v1.md) for the full evidence boundary.

### Evidence and decisions

| Method | Path |
| --- | --- |
| `POST` | `/api/v1/evidence/derive` |
| `GET` | `/api/v1/evidence` |
| `GET` | `/api/v1/evidence/{receipt_id}` |
| `POST` | `/api/v1/evidence/{receipt_id}/verify` |
| `POST` | `/api/v1/reproductions` |
| `POST` | `/api/v1/decision-briefs` |
| `GET` | `/api/v1/decision-briefs` |
| `GET` | `/api/v1/decision-briefs/{decision_id}` |
| `POST` | `/api/v1/exports` |

Generic evidence upload is deliberately restricted. Live, human-calibrated, cross-model, and independent evidence require their dedicated linked workflows and cannot be promoted by a caller-supplied label.

### Session, settings, membership, and retention

| Method | Path |
| --- | --- |
| `GET` | `/api/v1/session` |
| `GET` or `POST` | `/api/v1/login` |
| `GET` | `/api/v1/callback` |
| `POST` | `/api/v1/logout` |
| `GET` | `/api/v1/settings` |
| `PATCH` or `POST` | `/api/v1/settings` |
| `GET` or `PUT` | `/api/v1/projects/{project_id}/memberships` |
| `GET` | `/api/v1/projects/{project_id}/retention/preview` |
| `GET` or `POST` | `/api/v1/projects/{project_id}/retention/plans` |
| `POST` | `/api/v1/projects/{project_id}/retention/plans/{plan_id}/cancel` |
| `POST` | `/api/v1/projects/{project_id}/retention/plans/{plan_id}/execute` |

Team-mode mutations require an authenticated server session, the `X-Arena-CSRF` token, the `X-Arena-Project-Id` header where applicable, and the required project role. Detailed membership identity data is administrator-only.

Retention is archival-only: the service can produce recovery-bound plans and expire project idempotency rows, but does not delete immutable evidence, audit history, tombstones, projects, or shared artifact bytes.

## Compatibility API

The legacy `/api/runs` interface remains available in personal mode as a temporary compatibility surface. It is disabled with `404 legacy_api_disabled` in team mode. New integrations should use `/api/v1`.

## Error model

Fail-closed operations return a structured error or `HOLD` body with a stable code and prerequisite. Clients must not interpret missing usage as zero, missing preflight as PASS, or a receipt as proof of outcome correctness.
