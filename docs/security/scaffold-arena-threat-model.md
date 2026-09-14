# Scaffold Arena Threat Model

This tracked document is the public threat-model authority for Scaffold Arena 0.9.1. It defines the security invariants that implementation and review must preserve. The release candidate is not published or deployed; external security and research evidence remain incomplete.

- Primary assets: project isolation, sessions/RBAC, benchmark evidence and artifacts, provider credentials, and worker availability/cost.
- Critical boundaries: browser/OIDC callbacks, project-scoped APIs and database leases, study-pack/archive import, adapter HTTP/commands, object storage, exports/redaction, and operator deployment configuration.
- Non-negotiable invariant: every object read, mutation, lease, event stream, artifact action, export, and retention action must enforce the same authorized project at its atomic persistence/storage boundary.
- Highest-risk classes: IDOR/cross-project worker claims, login CSRF/session races, SSRF/command execution, archive traversal or decompression exhaustion, artifact metadata trust/shared deletion, secret-bearing exports/logs, duplicate external side effects, ambiguous provider usage, and unbounded resource use.

## Trust boundaries

- Personal mode binds to local storage and has no authentication claim.
- Team mode requires PostgreSQL, S3-compatible artifact storage, OIDC server sessions, CSRF protection, and project-scoped RBAC.
- Team mode disables the legacy `/api/*` surface; only `/api/v1/*` is admitted through the team authorization boundary.
- Uploaded StudyPacks are declarative. Executable adapters and graders must be installed as trusted packages and explicitly allowlisted.
- Artifact hashes establish custody and byte integrity, not outcome correctness or reviewer independence.

## Provider invocation and request identity

Database generation fences decide which worker result may become durable evidence. They do not prevent an older provider call, subprocess, or tool action from having already consumed tokens, incurred cost, or changed external state. Provider-side exactly-once behavior therefore remains dependent on the installed adapter and provider honoring idempotency, cancellation, and request identity.

Every new invocation derives a non-secret provider-request namespace:

- a pinned invocation hashes the provider identity together with the immutable endpoint digest;
- an unpinned invocation uses a conservative provider-only namespace;
- migrated legacy records receive the same deterministic provider-only namespace because their endpoint identity was not captured.

Duplicate request detection compares `(provider_request_namespace, provider_request_id)`, with two fail-closed compatibility rules:

1. pinned endpoint namespaces also collide with legacy provider-only records for the same provider, because those records cannot establish which endpoint produced the request;
2. unpinned or migrated invocations retain provider-wide collision behavior across all endpoint namespaces.

This prevents two independently pinned endpoints from being falsely classified as the same external request merely because they reuse an endpoint-local request ID. A model change on the same pinned endpoint does not create a new namespace and therefore cannot evade duplicate detection.

On PostgreSQL, request observation first takes a transaction advisory lock derived from a canonical SHA-256 value over the non-secret provider and provider request ID. It then performs the namespace-compatible lookup above. The lock can conservatively serialize equal IDs across distinct pinned endpoints, but it does not change the endpoint-specific decision rule. SQLite uses its immediate transaction for the same serialization boundary. The signed lock key and errors contain no raw provider request ID.

Terminal result admission applies the same pattern to the result digest: it serializes the cross-invocation lookup before any row writes. The first durable owner is the only row that stores the digest and terminal outcome. A later conflicting callback is marked duplicate/ambiguous, retains no second terminal result, and cannot treat reconciled usage as settled evidence. This protects the local admission boundary; it does not prove provider-side exactly-once effects.

The namespace contains no raw URL, account identifier, authorization header, credential, or secret. It also does **not** prove that a provider request ID is globally unique. Some providers may scope identifiers to an account, region, deployment, process, or time window that is not represented by the endpoint digest. Where an adapter can supply a stable non-secret billing-profile or tenant digest, that should be captured as separate observed evidence before narrowing duplicate scope further. Missing account-scope evidence remains an explicit limitation, never an exactly-once claim.

## Verification

Security regressions cover project-scoped job leasing, invocation generation fencing, stable provider idempotency identity, endpoint-scoped and legacy-compatible duplicate detection, cross-invocation request/result admission serialization, reservation lifecycle reconciliation, archive traversal and decompression limits, secret-safe export, CSV formula injection, team-mode legacy-route denial, membership-directory authorization, session binding, CSRF, and append-only audit/retention records. See `backend/tests/auth_v1`, `backend/tests/api_v1`, `backend/tests/artifacts_v1`, `backend/tests/execution_v1`, and `backend/tests/persistence_v1`.

Deployment-specific OIDC, proxy, PostgreSQL, object-store, provider-account, and external idempotency controls must still be verified in the target environment; repository tests cannot attest to external infrastructure or provider policy.
