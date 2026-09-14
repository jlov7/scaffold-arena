# Deployment coherence

Scaffold Arena exposes a narrow, non-secret deployment identity so an operator or the Workbench can determine whether the frontend and backend were built from the same complete Git revision.

## Public metadata surfaces

The backend serves:

```http
GET /build-meta
Cache-Control: no-store
```

The response contains only:

```json
{
  "schema_version": "build-meta.v1",
  "app_version": "0.9.1",
  "protocol_version": "1.0",
  "git_sha": "<40-or-64-character-git-sha-or-dev>",
  "build_environment": "production",
  "build_time": "2026-08-20T12:00:00.000Z"
}
```

The frontend emits the same schema as `build-meta.json` during its Vite build and embeds its resolved Git SHA in the Workbench. The Runtime revision inspector compares the complete frontend SHA with the backend response.

## States

| State | Meaning | Operator action |
| --- | --- | --- |
| **Revision verified** | Both components expose the same complete Git SHA. | Continue, while preserving the ordinary scientific and security evidence limits. |
| **Revision mismatch** | Both components expose complete but different Git SHAs. | Treat the deployment as mixed; redeploy or roll back before interpreting results as one release. |
| **Revision unverified** | At least one component reports `dev`, a missing value, or an incomplete identity. | Correct build-time environment injection and redeploy. |
| **Revision unavailable** | The backend metadata endpoint could not be reached or validated. | Check routing, CSP, backend availability, and proxy configuration. |

## Build identity sources

The backend accepts the first complete SHA from this ordered allowlist:

```text
VITE_GIT_SHA
VERCEL_GIT_COMMIT_SHA
RAILWAY_GIT_COMMIT_SHA
GITHUB_SHA
SOURCE_VERSION
```

The frontend uses the corresponding deployment environment and falls back to `git rev-parse HEAD` only during a local build. Partial SHAs are rejected as deployment identity and become `dev`.

Production deployments should supply:

- a complete Git SHA;
- an explicit build environment;
- a deterministic `SOURCE_DATE_EPOCH` or build timestamp where the platform supports it;
- a clean source checkout or an independently verified build context.

## Verification

For a deployed frontend and backend:

```bash
curl --fail --silent --show-error \
  https://<backend-host>/build-meta | jq .

curl --fail --silent --show-error \
  https://<frontend-host>/build-meta.json | jq .
```

Require the two `git_sha` values to be equal and complete. The production smoke tooling may enforce an expected SHA supplied by the release or deployment operator.

## Claim boundary

Matching build metadata proves only that the two deployed components report the same build identity under this contract. It does **not** prove:

- that the deployment configuration is correct;
- that an image or artifact was independently built;
- that a repository checkout was clean unless the build process separately established it;
- that provider credentials, storage policies, network boundaries, or OIDC configuration are secure;
- that experimental results are valid;
- that a result is independently reproduced;
- that signed artifacts or release provenance exist.

Build identity is an operational coherence signal. It is not scientific truth or a security attestation.
