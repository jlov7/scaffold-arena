# Artifact storage boundary

`S3CompatibleArtifactStore` is an optional team-deployment adapter behind the
existing `ArtifactStore` contract.

## Required configuration at construction

- A nonempty S3-compatible bucket, endpoint URL, region name, and relative prefix.
- A prefix made only of safe path segments.
- HTTPS for every endpoint except literal local test/development endpoints:
  `127.0.0.1`, `localhost`, or `[::1]`.
- Optional path-style addressing for compatible local/object-store deployments.
- A finite maximum artifact size.

The constructor accepts either an injected client or factory for tests, or the
existing `team` optional dependency for an S3-compatible client. Credentials
remain provider/runtime configuration; do not put credentials, access keys, or
signed URLs in repository configuration, compose files, artifact URIs, or logs.

## Integrity and custody

Objects use only an immutable content-addressed key:

```text
<prefix>/sha256/<first-two-hex>/<sha256>
```

Writes are conditional (`If-None-Match: *`) and are reread and SHA-256 verified
before acceptance. A collision, partial upload, declared-length inconsistency,
or body hash mismatch fails closed. Reads are bounded by the configured size
limit and stream in fixed chunks. The adapter neither lists objects nor applies
public ACLs.

The object carries only service-owned integrity metadata (`sha256`) and media
type. Classification, provenance, retention, and other content metadata remain
in the database artifact record. `uri_for` returns a credential-free `s3://`
identifier; it is not a signed download URL.

## Deployment status

This adapter alone is not team deployment evidence. Runtime selection, secret
injection, bucket policy, encryption, backup/recovery, monitoring, and external
reproduction remain separate deployment controls under ADR 006.
