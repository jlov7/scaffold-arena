# Team authentication boundary

Team mode is enabled only with `protocol_v1_deployment_profile=team`. Startup
fails closed unless a PostgreSQL URL, HTTPS OIDC issuer, client ID, allowlisted
HTTPS callback, 32+ character session secret, and secure `__Host-` cookie
configuration are present. SQLite is personal-mode only.

The login flow is OIDC Authorization Code with S256 PKCE, one-use state,
nonce-bound ID-token validation, and issuer discovery. It is a public client:
no client secret is accepted or persisted. ID tokens, provider tokens, and
claims never enter cookies or database records.

An opaque, HttpOnly, Secure, SameSite session cookie maps to a server-side
HMAC digest, expiry, revocation/rotation linkage, and CSRF token. A separate,
short-lived HttpOnly login-transaction cookie is HMAC-bound to the durable OIDC
state record, preventing callback login-CSRF/session swapping. Mutating team
v1 requests require `X-Arena-CSRF` obtained from authenticated session data.

Each team workbench request has an explicit `X-Arena-Project-ID`; identities
are keyed by OIDC `(issuer, subject)` and may hold exactly one role per project:
viewer, reviewer, operator, or admin. Missing membership is denied. Audit
events contain only request ID, actor, project, route, method, role, and status;
they exclude request bodies, cookies, query values, tokens, and secrets.

Retention is an admin-only, two-phase archival workflow. A viewer may read a
project-scoped deterministic preview; an admin must schedule it with the exact
preview digest and confirmation token, wait the 60-second-or-longer grace
period, and may cancel it before it is due. Execution re-hashes the project
state, writes and reads back a content-addressed recovery export, records an
append-only project-independent tombstone bound to that export, and only then
expires idempotency records older than the configured retention period.

This is **PASS_ARCHIVAL_ONLY**, not project deletion assurance. Projects,
immutable evidence, team audit history, tombstones, the artifact registry, and
all content-addressed artifact bytes are excluded. In particular, no artifact
byte is reclaimed: shared-reference safety is preserved by retaining all bytes.
Any changed graph state, unavailable/mismatched artifact store, stale/tampered
confirmation, concurrent plan change, or not-due plan fails closed without a
purge.
