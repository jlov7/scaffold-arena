# Evidence API v1

Evidence is project-scoped. Supply `X-Arena-Project-ID` (or `project_id`) when the local personal-project default is not appropriate. Unknown, cross-project, malformed, or incomplete records are non-disclosing.

`GET /api/v1/evidence/{receipt_id}` returns receipt hashes, evidence class, claim ceiling, and structured withheld-artifact descriptors. It does not return artifact bytes, manifest internals, credentials, private prompts, or an outcome/correctness assertion.

`POST /api/v1/evidence/{receipt_id}/verify` ignores request-body assertions. It re-reads the stored manifest, receipt bindings, DB artifact registrations, and artifact-store bytes, then hashes them again. Its verifier identity is local service metadata, not independent verification. A successful response establishes custody/integrity only, never result correctness, scientific validity, or independence.

`POST /api/v1/evidence` is a fixture-custody upload only. It accepts a caller-supplied manifest and receipt only when both declare `fixture`; caller-supplied `local_live`, reproduction, cross-model, human-calibration, and independent-reproduction labels return `409 HOLD`.

`POST /api/v1/evidence/derive` accepts exactly `execution_id` and `request_key`. It creates an immutable receipt ID deterministically from the project and request key, then reloads the completed frozen execution, every attempt/job/harness binding, terminal envelope, provider usage, price records, evaluation, and registered artifacts. A request cannot supply its own class, hashes, ceiling, scores, or manifest.

The derived workflow emits `derived_fixture` only when every persisted harness is fixture-only; mixed fixture and live executions are `409 HOLD`. Otherwise it may emit `derived_local_live` only after every attempt has a non-fixture harness, pinned and observed provider endpoint identity, provider-reported usage, required tool/state isolation, input and trace evidence, completed-output evidence where applicable, and exactly one immutable evaluator/result/result-artifact binding. The evaluator result artifact is re-read and must hash to its stored `result_hash`; request and terminal envelopes must preserve all immutable request fields. Missing evidence is `409 HOLD`; unknown cost is recorded as a limitation rather than converted into a price claim. Decision admission recognizes local-live maturity only for `derived_local_live`, never for a generic or legacy caller-labelled `local_live` row.

Derived aggregate hashes are canonical identities over sorted persisted rows: `code_hash` binds harness adapter/configuration digests, `runtime_hash` binds attempt provenance, `adapter_hash` binds adapter identity/digest, `model_hash` binds declared and observed provider identity, `price_hash` binds usage plus matching central price rows, and `evaluator_hashes` binds immutable evaluator/result/artifact rows. These hashes describe custody inputs, not code correctness, model behavior, pricing accuracy, or evaluation validity.

`POST /api/v1/reproductions` accepts exactly `receipt`, `original_evidence_receipt_id`, `reproduced_evidence_receipt_id`, and `external_attestation`. The two evidence receipt IDs must be distinct, durable, and in the same project. The reproduction receipt binds both manifest hashes and preserves deviations. `independent` is always false: an independent claim cannot be self-asserted. An optional `external_attestation` must satisfy the distinct-authority contract and bind the calculated reproduction hash; it is recorded as external evidence, not treated as locally verified identity independence.

Receipts are immutable. Exact repeats are idempotent; any differing content for a receipt ID or content hash returns `409 HOLD`.

Generic admission has a fixture-only custody/integrity ceiling. Dedicated workflows are required for all mature classes. Reproduction creation freshly verifies both source receipts before recording any relationship.

`protocol_v1.DecisionBrief` is an offline-only frozen protocol artifact and is intentionally absent from the active public schema index. `POST /api/v1/decision-briefs` uses the public `analysis-v1-decision-admission-request` contract: exactly one immutable analysis-report selector (`analysis_report_id`, or `experiment_id` plus `execution_id`), strict risk constraints, and proposed claims. It derives the decision brief and claim ledger from persisted evidence; callers cannot supply an AnalysisReport, evidence receipts, maturity labels, hashes, scores, or ceilings.

## Counterfactual Replay and Harness CI

`POST /api/v1/counterfactual-replays` accepts a strict checkpointed paired-replay contract. It binds shared pre-divergence checkpoint/state/environment/dependency/model/runtime/task-pack/evaluator identities once, permits exactly one declared mechanism difference, rejects evaluator leakage and holdout overlap, and preserves unknown usage/cost as `unknown`. It stores a content-addressed report only; it never starts a provider, process, or network request. `GET /api/v1/counterfactual-replays/{report_digest}` recovers only a report visible to the selected project. The `/counterfactual/replays` paths are compatibility aliases.

`POST /api/v1/harness-ci/checks` evaluates an existing project-visible replay report against source-digest and policy bindings. Source change text is used only in memory for semantic mechanism classification and is not retained in the report or custody table. Responses contain the machine report, GitHub step-summary body, and PR-comment body; the API never posts a comment. `GET /api/v1/harness-ci/checks/{report_digest}` is project-scoped recovery; `/harness-ci-reports` is a compatibility alias.

Both endpoints use `PASS`, `HOLD`, and `FAIL` as bounded policy states. `PASS` is not causal proof, model-performance evidence, deployment authorization, security assurance, or independent validation. Fixture and recorded reports keep ITT, opportunity, activation, fidelity failure, and treatment-on-the-treated unestimated until their own assumptions are evidenced.
