# Security Policy

## Supported Versions

Scaffold Arena is an active R&D project. Security fixes are applied to the latest `main` branch. A version is supported as a public distribution only after the tag-gated release workflow publishes signed, attested artifacts for it. The current `0.9.1` state is an unpublished, undeployed release candidate; external research evidence remains incomplete.

## Reporting a Vulnerability

Please do **not** open public GitHub issues for potential vulnerabilities.

Report security concerns privately with:

- a clear description of the issue;
- reproduction steps;
- affected versions, commits, packages, images, or artifact digests;
- impact assessment;
- suggested mitigation, when available;
- whether public disclosure has already occurred.

Contact channel:

- Use the repository **Security** tab and select **Report a vulnerability** when that control is available.
- If private vulnerability reporting is unavailable, open a public issue that asks only for a private security contact. Do not include vulnerability details, reproduction steps, payloads, credentials, or other sensitive material in that issue.

Before any public launch, the target repository must enable and verify a private vulnerability-reporting route. The current availability of that route is not asserted by this policy.

Do not include provider credentials, session cookies, private StudyPacks, restricted artifacts, customer data, or exploitable secrets in an unencrypted message.

## Response Expectations

Target response times:

- acknowledgement: within 3 business days;
- initial triage: within 7 business days;
- remediation timeline: communicated after triage.

These are targets rather than service-level guarantees.

## Scope

In scope:

- backend authentication, project isolation, input validation, durable workers, budgets, and execution controls;
- adapters, subprocesses, HTTP/RPC boundaries, sandboxing, cancellation, and secret handling;
- StudyPack/archive import, artifact storage, exports, retention, and redaction;
- frontend token handling, injection surfaces, authorization boundaries, and sensitive browser state;
- dependencies, build workflows, GitHub Actions, package and image publication, SBOMs, signatures, and attestations;
- release-tag, checksum, provenance, or container-registry compromise.

Out of scope unless they expose a Scaffold Arena defect:

- social-engineering requests;
- third-party provider outages;
- vulnerabilities in unsupported local modifications;
- claims that an artifact signature proves model-output correctness or research validity.

## Release and Supply-Chain Incidents

For a suspected compromised release, tag, workflow, package, image, or maintainer account:

1. stop further publication by disabling the release path or environment;
2. revoke affected repository, package, deployment, and account access;
3. preserve tag objects, workflow logs, attestations, Sigstore bundles, package bytes, OCI digests, and access records;
4. mark the affected release as withdrawn without silently replacing its assets;
5. publish a GitHub security advisory when disclosure is appropriate;
6. issue a new version through the complete release workflow;
7. document the superseding version and affected digests.

Published transparency records are historical evidence and should not be deleted merely to hide a compromised release. See `docs/ops/release-verification.md` for verification and withdrawal procedures.

## Safe Harbor

Good-faith security research coordinated through an available private reporting route will be treated as authorized when it avoids privacy violations, service disruption, persistence, lateral movement, and unnecessary access to third-party data.
