# Recoverable retention archival

Scaffold Arena does not delete projects. Its foreign-key graph intentionally
protects immutable evidence and a content-addressed artifact store that can be
shared between projects. Retention is therefore a recoverable archival control,
not a data-erasure claim.

1. Set the project `retention_days` (1–3650).
2. Read `GET /api/v1/projects/{project_id}/retention/preview` as a viewer or
   admin. Preserve the returned `snapshot_digest` and `confirmation_token`.
3. An admin schedules `POST .../plans` with both values and a grace period of
   60–2,592,000 seconds. The route is CSRF-protected in team mode.
4. An admin can cancel a scheduled plan before `due_at`.
5. At or after `due_at`, an admin executes the plan. The service re-hashes the
   project state, persists and verifies a recovery export, registers it as an
   artifact, and appends an independent tombstone bound to that digest.

The only destructive operation is deletion of expired project idempotency
records. The recovery export contains their prior relational rows. There is no
artifact-byte deletion or artifact-registry deletion, so shared content is never
reclaimed. Immutable evidence, team audit events, tombstones, projects, and
membership/identity history are retained. Operational status is
`PASS_ARCHIVAL_ONLY`; it must not be described as project deletion, erasure,
storage reclamation, or independent retention assurance.
