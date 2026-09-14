# Production-profile integration verification

The ordinary repository gate is deliberately service-independent. It proves the
committed protocol, persistence, frontend, packaging, and container contracts,
but it does not silently convert unavailable PostgreSQL or object storage into a
pass.

A separate production-profile suite exercises the real team-deployment storage
boundaries:

```bash
./scripts/test-production-integrations.sh
```

## What the suite starts

The script creates an isolated, disposable Docker Compose project containing:

- PostgreSQL, using the same major version and SQLAlchemy/psycopg path supported
  by team mode;
- a loopback-only S3-compatible object service;
- unique database, bucket, prefix, and worker project identifiers for the test
  process.

Both images are referenced by immutable digests. Credentials are fixed local
fixtures, bound only to loopback ports, and removed with the disposable volumes
when the script exits.

## What is verified

The suite fails unless all of the following pass:

1. Alembic upgrades a real PostgreSQL database to `head`.
2. Autogeneration reports no difference between the migrated database and live
   SQLAlchemy metadata.
3. PostgreSQL preserves frozen-object guards, project isolation, event cursors,
   row-lock job leasing, expiry, heartbeat, cancellation, retry, and concurrent
   project-scoped claims.
4. The S3-compatible store performs conditional content-addressed writes,
   rereads and verifies bytes and service-owned SHA-256 metadata, and preserves
   media type.
5. Concurrent writes of identical bytes converge on one digest without accepting
   conflicting content.
6. Missing objects, metadata mismatch, content mismatch, partial/oversized
   objects, and configured byte-limit violations fail closed.
7. Team API composition applies migrations and blocks readiness until the fixed
   object-storage sentinel can be written and reread.
8. The worker process opens the same PostgreSQL database and object namespace,
   verifies the sentinel, loads only the allowlisted fixture adapter, and becomes
   lease-capable only after both durable services are ready.

GitHub Actions runs the same script. There is no CI-only replacement for the
local production-profile command.

## Supported Python verification

The main backend suite and packaging checks run on Python 3.12. Focused protocol,
adapter, migration, fixture, and CLI compatibility checks also run from the
locked dependency graph on Python 3.11 and 3.13. A compatibility job demonstrates
that the shipped contracts execute on those interpreters; it is not evidence
that every optional third-party provider SDK supports every future version.

## Claim boundary

This suite is integration evidence for the repository's PostgreSQL and
S3-compatible code paths. It is not production deployment evidence. It does not
attest to a target organisation's bucket policy, TLS termination, IAM role,
encryption keys, backup/restore process, OIDC provider, network policy, provider
credentials, or independent reproduction. Those controls remain deployment and
evidence prerequisites in the team runbook.
