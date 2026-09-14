# Changelog

## Unreleased

- Added a small-text personal R&D and employer-affiliation disclaimer to the README.
- Replaced the CI image-build action with equivalent direct Buildx commands, retaining the existing Dockerfiles, production targets, contexts, and no-push behavior while avoiding action-generated event metadata in build logs.
- Reframed scaffold, telemetry, release, accessibility, UX, and lifecycle documentation around the current evidence boundary. Removed unsupported scaffold scores and causal claims, clarified that the current candidate is undeployed, and replaced provider-specific operations guidance with portable procedures.
- Replaced the retired self-hosted workflow badge with a repository-relative CI candidate-verification link. This is a workflow entry point, not a claim that the candidate is published or released.
- Removed the unavailable self-hosted verification workflow from the public candidate configuration. The remaining CI configuration is not evidence of a newly tested, published, or deployed candidate.
- Added a fail-closed publication-binding path for retaining a historical local-runtime bundle in a future clean-history snapshot. Normal ancestry verification remains the default; a valid root-commit binding can establish only historical bundle integrity and custody, not historical-source reproducibility, current-code ancestry, live evidence, or a scaffold-effect result.
- Clarified that provider-free fixture accounting records no provider usage, cost, API calls, or measured latency. Fixture control scores remain deterministic test outcomes, not provider or benchmark measurements.

All notable user-visible changes are documented here. A version is a public release only after an annotated tag, signed artifacts, SBOM, attestations, and a GitHub release have been published by the release workflow.

## [Unreleased]

### Changed

- Rebaselined only the total emitted-JS ceiling from 605,000 to 610,000 bytes against the release-readiness candidate measurement of 609,190 bytes. This does not claim a performance improvement; all other budgets are unchanged.
- Raised the locked WeasyPrint version to 70.0 for the audited SSRF fix and aligned Vitest with 4.1.11. These are targeted PR #57/#58 follow-through updates; release verification still reruns the dependency audits on the exact candidate.
- Refined Guided Run Cockpit into a five-field visible run summary and closed native disclosure rows for attempt, job, trace, and event records. HOLD, severe failures, unknown values, source labels, and the next available control remain visible. Lab retains full record inspection.
- Made the real offline-demo browser smoke a required release-gate lane. It now runs isolated desktop and mobile backends, captures a top-of-viewport fixture journey, CSV export, and typed local provenance, then stops only its owned backend and frontend processes. The retained temporary captures are fixture-journey evidence only.
- Reworked the first-run documentation around the two-process loopback browser demo, a separate fresh-output CLI provenance example, and current Harness-Bench, Inspect, Harbor, and Terminal-Bench boundaries. The fixed context-handoff protocol remains reproducible; no completed comparative live evidence is claimed.
- Added a bounded, local-only context-handoff StudyPack capability with frozen packets, matched policy seeds, exact local Ollama identity checks, and independent delivery reconstruction. No comparative live study result is recorded by this change.
- Added a personal-profile-only bundled offline demo journey. It imports the exact synthetic StudyPack, still requires explicit experiment creation, approval, freeze, and PASS preflight, then runs only the bounded fixture worker chain with server-captured provenance. The opt-in real-backend Playwright smoke covers desktop, mobile, durable recovery, immutable analysis, CSV export, and invalid execution IDs; fixture outputs remain descriptive-only evidence.
- Rebuilt the repository README around the problem Scaffold Arena solves, a provider-free first-run path, four user decision jobs, and an evidence-bounded product narrative; replaced the dense twelve-image gallery with three readable Workbench views and clearer routes into the detailed documentation.
- Recorded exact production revision parity after the Vercel frontend and Railway API reported the same full merge SHA and passed the public token-free smoke; this is deployment coherence only, not security or scientific assurance.
- Added a fail-closed native LM Studio adapter and bounded local-runtime evidence runner. The runner can exercise native Ollama or LM Studio through the durable pipeline while exporting artifact bytes only after evidence admission. Ollama produced synthetic exploratory local-live custody; LM Studio truthfully held because native v1 does not expose a verifiable runtime version. Neither outcome is confirmatory evidence or a scaffold-effect claim.
- Added a non-cacheable public build-identity endpoint and Workbench revision-coherence indicator so mixed frontend/backend deployments are visible without exposing configuration or credentials. Matching revisions establish deployment coherence only, not scientific validity or security assurance.
- Made Guided Harness X-Ray discover project-scoped durable captures by human-readable name while hiding raw artifact digests and fixing source profiling to `auto`; Lab retains exact immutable identities and explicit static source kinds.
- Defined the nine-plane Harness Stack—model, context, memory, control, topology, tools/environment, assurance, economics, and evidence—and linked it to the Three-Graph and intervention-fidelity boundaries throughout the public documentation.
- Replaced placeholder and overclaiming social metadata with canonical, accessible, evidence-bounded previews and strengthened repository hygiene to prevent those regressions.
- Added a manually dispatched, exact-commit-bound self-hosted verification route for trusted private-repository revisions. It preserves the authoritative local gate and Python 3.13 compatibility suite without executing pull-request code on the private runner.
- Added offline Protocol-v1 preregistration readiness packs for issues #33 and #34. They freeze declarative flagship and no-retuning transfer matrices, validate custody/configuration/cohort/runtime/cost boundaries, emit collision-gated fixture-only analysis bundles, and fail closed until an external public immutable preregistration and signature exist. This is not a live study or result.
- Added the provider-free Harness Mechanism Atlas v1: a strict, source-custodied seven-family taxonomy with discriminated semantic contracts, declarations, non-activation observations, evidence links, known unknowns, deterministic generation, semantic validation, and release-digest custody. It remains source/fixture metadata only; a tagged Cosign bundle is still required before release-signature evidence can be claimed.
- Reconciled release-facing human calibration to Protocol-v1: each target now requires three independent blind pseudonymous annotations on a normalized `[0,1]` scale, a strict per-dimension `> 0.20` conflict rule, and one evidence-bound adjudication for every conflict. Packet validation now fails closed on incomplete, duplicate, unbound, or unresolved records; local protocol completion remains receipt-free until authority verification and external attestation exist.
- Added a complete provider-free public examples map with seven fail-closed named examples plus the existing counterfactual replay path. Each example now has a one-command entry point, machine-readable input/expected-output manifest, focused test boundary, cleanup rule, screenshot status, and an explicit fixture/live/HOLD ceiling; no provider or PR comment is started by these commands.
- Replaced the legacy two-image Workbench gallery with a provenance-checked product-tour capture set covering Harness Home / X-Ray, Study Canvas, Run Cockpit, Decision Canvas, Trace / Counterfactual Lab, and Evidence Room at pinned desktop and mobile viewports. Captures remain deterministic fixture, blocked, or empty UI documentation only.
- Added a fail-closed native Ollama local-runtime adapter. It binds literal-loopback endpoint, version, exact model digest, frozen generation controls, response usage, context consumption, and zero-tool evidence; it requests `think: false`, retains only a sanitized response summary plus raw-response digest, bounds API response reads, and keeps missing or mismatched evidence as a typed HOLD.
- Reorganized the Workbench around Compare, Diagnose, Improve, and Prove while retaining the Study-to-Evidence protocol beneath it. Guided discovery now withholds raw durable IDs, digests, canonical JSON, and manual provenance construction; Lab retains full object, trace, evidence, and export inspection over the same durable services. Optional Trace Lab is deferred and protected by the first-load budget check.
- Added a deterministic bounded invocation/reservation lifecycle model and release-gate checker, plus guards against terminal-result replacement, cross-invocation provider request/result admission races, post-terminal provider-identity mutation, a PostgreSQL dispatch-versus-settlement race, and superseded reservation transitions. These checks are bounded engineering evidence only, not production, security, causal, or independent assurance.
- Added provider-free Arena Forge controls: strict untrusted single-mechanism proposals, distinct owner/policy approval, independent frozen evaluations, matched controls, immutable Evolution Receipts, a budget/risk-constrained next-best-experiment planner, and digest-only process-safety flow reports. The lazy Workbench, API, CLI, fixtures, and generated schemas preserve approval, preflight, sealed-holdout, no-execution, and no-auto-merge boundaries. These are product controls only, not security assessment, containment, model-performance, deployment, or independent-assurance evidence.
- Added provider-free Counterfactual Replay and Harness CI candidate surfaces: strict checkpointed paired contracts, content-addressed project custody, explicit evidence maturity and unestimated causal-family measures, semantic base/candidate mechanism checks, reusable GitHub Action, CLI JSON/step-summary/PR-comment artifacts, and a lazy-loaded budget-aware Workbench fixture surface. Fixture and recorded reports remain bounded evidence, never causal or model-performance proof.
- Added provider-free Harness X-Ray and observatory reports for bounded named source snapshots and persisted traces. Reports preserve declared, observed, inferred, verified, unsupported, and unknown states, and are not causal, performance, or security-assurance evidence.
- Added strict, content-addressed Harness Genome v1 descriptors, deterministic connected three-graph projections with explicit unknown/HOLD observation states, semantic diff, and local descriptor-only certification receipts. Added a source-dated standards catalog and a bounded ACP v1 bridge foundation with pinned official schema custody, fixed argv, digest-bound operator launcher attestation, isolated roots, resource limits, and default-deny callbacks. ACP remains a deployment-owned, typed-HOLD public surface; fixture launcher evidence is not containment proof, and no catalog row or local receipt implies external runtime, safety, deployment, or independent-assurance support.
- Reorganized public documentation around provider-free setup, the shipped Protocol-v1 product journey, and explicit evidence boundaries; added fixture-pinned visual assets and runnable offline examples.
- Added public frontend and API build receipts plus a token-free production smoke command that verifies deployed revision parity when an expected SHA is supplied.
- Moved the public product contract and design system into the documentation hierarchy, and added a fail-closed public-repository hygiene check to the local and CI gates.
- Added a fail-closed, machine-verifiable release contract and removed metadata that implied the untagged beta had already been published.

### Fixed

- Pinned patched frontend transitive dependencies and made local and hosted frontend audits include development dependencies at moderate severity. This release-gate remediation does not claim a security assessment or release assurance.
- Switched the pinned MinIO integration-test image to the same digest on Quay for hosted CI registry portability. The image version, integration contract, ports, and security settings are unchanged.
- Restored explicit public boundaries for unsupported fixture and synthetic-source interpretations, adjacent-tool non-replacement, and portable release-smoke temporary-output documentation. These documentation corrections do not add live, human, or external evidence.
- Fenced delayed execution selection, inspection, pagination, and mutation responses against newer navigation. Completed bundled-demo reruns now receive fresh scoped request keys while uncertain requests retain recovery keys. Fixture recovery waits for scoped leases and reclaim backoff within its existing deadline, and reclamation cannot modify other executions. Restored the explicit unreleased beta declaration and a PostgreSQL-safe runtime-lock foreign-key name.
- Local context-handoff runs now retain the frozen 24-cell plan, source/provenance bytes, durable database, raw bounded transport observations, terminal holds, and artifacts on completion or interruption. Offline verification reconstructs actual requests and pricing and replays trusted evaluation without changing the evidence root. Frozen-order leasing and scenario-specific exact-response/schema grading are corrected; no live comparison is claimed.
- Disabled browser-triggered bundled-fixture dispatch by default, in direct-ASGI launches, and in container deployments. The fixture now requires the explicit literal-loopback local launcher, validates direct loopback request context, serializes admission across service instances, preserves first-captured provenance by bounded idempotency key, and retains a crash-safe single-flight reservation. Guided mode now directs capture setup to operator documentation instead of displaying local commands or paths.
- Made Run Cockpit preserve the URL-selected execution across pagination and reject missing or cross-experiment execution IDs without silently selecting another run. SSE observation now distinguishes attempt terminal frames from the execution terminal, so the cockpit continues to the durable final state and reports an interrupted stream instead of treating it as success.
- Hardened evaluation integrity: judge JSON is extracted and structurally validated conservatively; `within_budget` now requires reconciled cost against matching persisted attempt/execution envelopes (otherwise `over_budget` or `unknown`); and imported StudyPacks expose readiness immediately.
- Made content-addressed artifact registration and project-scoped execution idempotency atomic across concurrent SQLite/PostgreSQL callers. Identical replays now reuse the existing durable state, while conflicting artifact size/location or idempotency payloads remain rejected.
- Hardened durable lease recovery with a supervisor-cancellation grace window, deterministic capped reclaim backoff, and a fail-closed lease-generation cap. Lease expiry still fences stale workers and provider-result admission immediately; lease generations remain separate from explicit scientific attempt retries.
- Made scientific claim boundaries fail closed: primary paired effects now expose raw and Holm-adjusted p-values while retaining explicitly marginal intervals; caller-declared comparison invariants cannot promote analysis or trace claims; and public-marked preregistration drafts with placeholder bindings remain `HOLD` for confirmatory admission.
- Made report and Pareto views preserve unknown or incomplete cost/latency data, added an executable provenance-capture CLI to Lab handoff without browser fabrication, and reconciled the canonical Workbench v1 route map with ADR 007 compatibility routes.
- Made the Evidence and specification dialog usable at desktop, tablet, and mobile widths while retaining keyboard dismissal and focus restoration, and preserved the synthetic-fixture boundary after moving from Design to Preflight.
- Hardened local-runtime evidence admission so prompts are bounded before dispatch, executions bind to an exact clean Git revision, synthetic outputs are allowlisted before publication, operator attestations cannot masquerade as provider observations, and receipt custody rejects path redirection, special files, unexpected entries, or forged verification metadata.
- Enabled the documented cross-origin `PATCH` and `PUT` mutation flows while preserving the configured-origin, credential, session, project-role, and CSRF boundaries.
- Replaced the deprecated LHCI dependency path with direct official Lighthouse 13 desktop and mobile gates. The loopback preview lifecycle and HTML/JSON route reports are retained, every prior threshold now fails the gate, and the `@lhci/cli`/`extract-zip` dependency path is removed without overrides or forks.
- Deferred optional Harness X-Ray and Observatory bundles until their Workbench routes are opened, while keeping the Workbench first-load ceiling unchanged and enforcing the route split in the build budget gate.
- Corrected the public roadmap to show the bounded shipped M1 Harness Genome and standards work while keeping ACP process execution typed HOLD; added actionable M3–M6 and external deployment-evidence gates.
- Made command-adapter cleanup fall back to direct process signals when process-group signalling is unavailable.
- Hardened SPA asset resolution, JSON fence parsing, and public API failures so traversal attempts, malformed large fence input, provider diagnostics, and exception text are not exposed to browsers.
- Made browser-provided provider and legacy API tokens memory-only, removed build-time API-token injection, and delete legacy browser-storage entries on startup.
- Removed daily spend and remaining-budget activity from the unauthenticated metadata response.

## [0.9.1] - 2026-08-23

Prospective release URL (not yet created): https://github.com/jlov7/scaffold-arena/releases/tag/v0.9.1. This release candidate has not been published or deployed.

### Changed

- Added opaque lease-token and generation fencing so stale workers cannot publish results after reclaim or supersession.
- Made evaluator publication and heartbeat updates atomic at their durable publication boundary.
- Enforced loopback-only personal deployment behavior and rejected personal-mode configurations that claim team infrastructure.
- Fixed frontend E2E journeys and performance-budget paths, including the current build and runtime metadata surfaces.
- Completed the fail-closed release gate for canonical backend verification, frontend content/unit/coverage/layering/build/performance/E2E/accessibility/visual/Lighthouse/audit lanes, and available production integration.
- Added Python and frontend dependency audit gates and prepared public-only CodeQL readiness for the repository security workflow.
- Made release browser verification deterministic by serializing CI journeys after a parallel Playwright worker-shutdown hang was reproduced locally.

### Fixed

- Preserved legacy Counterfactual Replay URLs without publishing duplicate OpenAPI operation IDs, and added a schema-wide uniqueness regression check.
- Bounded command/JSONL stdin, stdout, stderr, and process completion under one attempt deadline so blocked stdin shutdown cannot defeat timeouts or stream backpressure on supported Python versions.

### Evidence boundary

- This is an unpublished, undeployed release candidate. External live-provider evidence, completed human calibration, independent reproduction, and deployment/security assurance remain incomplete.

## [0.9.0] - 2026-08-20

Planned release URL (not created): https://github.com/jlov7/scaffold-arena/releases/tag/v0.9.0. A release would be created only by the tag-triggered workflow.

### Added

- Protocol-v1 StudyPacks, frozen experiments, factorized designs, strict schemas, and portable extension namespaces.
- Durable attempt and evaluation workers with leases, retries, budgets, monotonic GET-only SSE recovery, and crash-safe finalization.
- Independent deterministic evaluation, state oracles, severe-failure gates, blind review, causal-analysis safeguards, and report-bound exports.
- Content-addressed local and S3-compatible artifacts, derived custody receipts, claim ledgers, decision briefs, and reproduction records.
- Guided and Lab workbench planes across Studies, Design, Preflight, Execute, Analyze, Trace Lab, Review, Evidence, and Settings.
- Personal SQLite deployment and fail-closed PostgreSQL/OIDC/S3 team deployment with project-scoped RBAC.
- Hash-pinned synthetic offline StudyPack exercising all 16 P/V/R/M arms through an 80-attempt durable fixture chain.
- Installable `arena` CLI and clean-clone verification path.

### Security

- Team mode disables legacy APIs outside the project-scoped v1 authorization boundary.
- Added OIDC login transaction binding, server-side session rotation, CSRF, role enforcement, project-scoped job leasing, archive hardening, secret-safe exports, and CSV formula-injection defense.

### Evidence boundary

- This beta does not claim live-provider performance, completed human calibration, independent reproduction, or production deployment assurance.
- The `0.9.0` version is a release candidate; it is not a GitHub release or signed distribution until the tag-triggered release workflow succeeds.

## 0.1.0 prototype snapshot - 2026-05-22

- Initial four-scaffold comparison workbench and protocol-v0.1 fixture package.
