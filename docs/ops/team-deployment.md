# Team deployment runbook

This is a reference deployment profile, not production deployment evidence. It
requires ADR 006's separate controls for managed secrets, bucket policy,
backup/recovery, monitoring, and external reproduction.

## Configuration gate

Set `PROTOCOL_V1_DEPLOYMENT_PROFILE=team` only with PostgreSQL, complete OIDC
configuration, secure cookies, and `PROTOCOL_V1_ARTIFACT_BACKEND=s3_compatible`.
The S3 endpoint, bucket, region, prefix, and finite maximum artifact size are
explicit. Runtime uses ordinary provider environment/role credential resolution;
it does not read credentials from source configuration or expose them in status.

`PROTOCOL_V1_TEAM_ALLOW_LOCAL_ARTIFACTS_DEVELOPMENT=true` is a narrowly named
development override. It returns a `/ready` `HOLD`, and cannot support a team
deployment claim.

## Compose and rollout

`deploy/compose.team.yml` is a static reference. Inject every `${...:?}` value
from the deployment secret manager; do not commit an `.env` file. Pre-provision
the PostgreSQL database, object bucket, TLS endpoint, least-privilege role,
encryption, lifecycle policy, OIDC redirect URI, and reviewed declarative
adapter-runtime JSON file before rollout. The compose starts exactly one worker
with fixed argv (`uv run arena worker`); it receives its database, S3 namespace,
project scope, owner, and adapter-config path from validated settings. The
adapter JSON is mounted read-only and supports only explicitly allowlisted
adapter kinds. It cannot name a command, module, plugin, or provider bootstrap
operation.

1. Generate SBOM and local provenance using `scripts/deployment/`.
2. Apply database migrations through the normal backend lifespan in a controlled
   environment, then query `/ready`. The worker never performs migrations and
   the API never starts a worker.
3. Verify `/health` is only liveness, `/ready` has passed its fixed
   content-addressed S3 read/write sentinel, and `/metrics` emits only bounded
   method/scope/status counters. This does not verify bucket policy or encryption.
4. Confirm the worker healthcheck passes: it opens PostgreSQL, constructs the
   configured S3-compatible store, and performs the same fixed
   content-addressed S3 read/write sentinel before it can lease a job. It loads
   the trusted adapter registry without invoking a provider. The worker then
   runs one bounded attempt lease and one bounded evaluator lease per pass,
   using the central provider-price resolver.
5. Promote only after an external smoke test, bucket-policy evidence, backup
   verification, and rollout owner sign-off are recorded.

Rollback restores the prior immutable image and configuration reference. It
does not reverse database migrations or overwrite evidence automatically.

## Backup and restore

`backup-postgres.sh` and `restore-postgres.sh` default to dry run. Restore also
requires both `--execute` and `--acknowledge-destructive`, an input SHA-256
sidecar, and a secret-managed database URL. A real restore rehearsal has not
been performed by these artifacts.

## Repository production-profile verification

Before target-environment rollout, run the disposable PostgreSQL and
S3-compatible integration suite:

```bash
./scripts/test-production-integrations.sh
```

GitHub Actions runs the same command. It verifies migrations, PostgreSQL lease
concurrency, conditional content-addressed object writes, integrity failures, the
team readiness sentinel, and worker composition against real services. See
[production-profile integration verification](production-integration-verification.md).
It remains repository integration evidence, not target-environment bucket-policy,
OIDC, backup, or deployment evidence.

## Environment-specific evidence still required

- `HOLD_EXTERNAL_SIGNATURE`: local SBOM/provenance generation is unsigned.
- `HOLD_RESTORE_REHEARSAL`: no real restore rehearsal evidence exists.
- `HOLD_BUCKET_POLICY_EVIDENCE`: no production bucket policy/TLS/encryption
  evidence exists.
- `HOLD_WORKER_RUNTIME` is removed for the shipped settings-owned worker
  runtime. This is a deployment mechanism, not evidence that a provider,
  worker, or evaluation has run successfully in a target environment.
- `HOLD_LIVE_PROVIDER_ARTIFACTS`: no target-environment provider trace, usage,
  cost, or worker-result evidence is bundled here.
