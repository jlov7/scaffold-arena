# Release verification and recovery

Scaffold Arena treats a software version as released only when all of the following exist for the same immutable revision:

1. authoritative `release/release-metadata.json` in `release-candidate` or `released` state;
2. an annotated `v<version>` Git tag;
3. a successful tag-triggered `Release` workflow;
4. Python wheel and source distribution;
5. frontend and repository source archives;
6. an SPDX JSON software bill of materials;
7. SHA-256 checksums and a keyless Sigstore bundle for the checksum manifest;
8. GitHub build-provenance and SBOM attestations;
9. a digest-addressed, keylessly signed OCI image in GitHub Container Registry;
10. a GitHub release created only after every prior gate succeeds.

Repository artifacts, signatures, SBOMs, and attestations establish software origin, custody, and integrity within their stated boundaries. They do not establish model-output correctness, evaluator independence, experimental validity, deployment security, or universal scaffold superiority.

A source binding for a historical evidence bundle in a curated public snapshot preserves only that bundle's integrity and custody. It does not establish that the bundle was produced by the snapshot's current code, create new live evidence, or validate a scaffold effect.

## Historical evidence and a future clean-history snapshot

The ordinary historical-evidence verifier requires the recorded code revision to
be an ancestor of `HEAD`. A future public snapshot that intentionally excludes
older private history may use a single canonical binding in its root commit
message instead. That binding is checked against the root tree, its complete
Git object inventory, and the raw bundle-manifest bytes for each retained
historical bundle.

The alternate path is narrow and fail-closed. With a valid binding, verification
reports `historical_source_revision_unverifiable_in_snapshot`; it confirms
historical bundle integrity and custody only. It does not reconstruct the old
source revision, establish current-code ancestry, create live evidence, or
validate a scaffold effect. Without the binding, normal ancestry verification
continues to apply. This is a future-export procedure, not evidence that a
clean-history public snapshot exists.

## Current release-candidate state

`0.9.1` is currently a release candidate. The current candidate is not published or deployed. It is prepared for the tag-triggered workflow, but that preparation does not establish a release. An earlier deployment-parity check for merge `002fe74fbab99bb5adf611b857b05cfd17dc3f53` is historical evidence only; it does not establish deployment of the current candidate. `CITATION.cff` and the changelog describe release metadata, not publication evidence. External research and security evidence also remain incomplete.

The standard verifier is dependency-free:

```bash
python scripts/verify-release-metadata.py --root .
```

A successful result is machine-readable JSON with `"verdict": "PASS"`. The verifier checks backend, frontend, API, citation, README, protocol, changelog, and release-metadata agreement.

## Preparing a release

A release-preparation pull request must update these declarations together:

- `release/release-metadata.json`
  - `status`: `release-candidate`
  - `tag`: `v<version>`
  - `released_at`: intended ISO date
- `CITATION.cff`
  - matching `version`
  - matching `date-released`
- `CHANGELOG.md`
  - dated version heading
  - GitHub release link for the exact tag
- backend, frontend, and FastAPI version declarations
- release notes and any compatibility or migration documentation

Run the complete gate before merge:

```bash
./scripts/verify-all.sh
./scripts/verify-release-gates.sh
python scripts/verify-release-metadata.py --root .
```

`verify-release-gates.sh` includes an isolated real-backend smoke of the provider-free browser fixture at 1440 × 900 and 390 × 844. Each viewport receives a fresh SQLite database, Protocol-v1 artifact directory, capture directory, and owned loopback backend and frontend processes. The smoke retains its PNG, CSV, and per-screenshot provenance in a fresh directory beneath a writable `TMPDIR`, falling back to `/tmp` when needed, and stops only the processes it started, leaving unrelated listeners untouched. Those files demonstrate the named local fixture journey; they do not establish benchmark, provider, usability, or model-performance evidence.

After the preparation pull request is merged, create an annotated tag at the exact merge commit. A cryptographically signed annotated tag is preferred when the maintainer has a configured signing identity:

```bash
git checkout main
git pull --ff-only
git tag -s v0.9.1 -m "Scaffold Arena 0.9.1"
git push origin v0.9.1
```

An unsigned annotated tag made with `git tag -a` satisfies the workflow's structural check but provides less identity assurance. Artifact and OCI signatures are still produced keylessly by the release workflow.

The tag-triggered workflow verifies:

- tag name equals authoritative metadata;
- tag object is annotated rather than lightweight;
- tag resolves to the workflow commit;
- all repository verification gates pass;
- all release-bearing version declarations agree.

A manual `workflow_dispatch` exercises build and validation paths but is structurally unable to sign, push, attest, or create a GitHub release because every publishing step is gated on a tag push event.

## Verify downloaded release assets

Download all assets for one release into an empty directory. Check the checksum set before using any package:

```bash
sha256sum --check SHA256SUMS
```

Verify the checksum manifest's keyless Sigstore bundle. Replace the version in the identity expression as needed:

```bash
cosign verify-blob \
  --bundle SHA256SUMS.sigstore.json \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity-regexp \
    '^https://github.com/jlov7/scaffold-arena/.github/workflows/release.yml@refs/tags/v0[.]9[.]1$' \
  SHA256SUMS
```

The expected certificate identity is the tag-bound release workflow, not a maintainer workstation.

Verify GitHub artifact provenance for each downloaded artifact:

```bash
gh attestation verify \
  scaffold_arena_backend-0.9.1-py3-none-any.whl \
  --repo jlov7/scaffold-arena

gh attestation verify \
  scaffold-arena-source-0.9.1.tar.gz \
  --repo jlov7/scaffold-arena
```

Inspect the SPDX JSON SBOM before admission into a controlled environment:

```bash
jq '.spdxVersion, .creationInfo, (.packages | length)' \
  scaffold-arena-0.9.1.spdx.json
```

An SBOM describes observed components; it is not a vulnerability scan or license approval by itself.

## Verify the OCI image

Use the immutable digest shown in the release notes or attestation record:

```bash
IMAGE='ghcr.io/jlov7/scaffold-arena@sha256:<digest>'

cosign verify \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity-regexp \
    '^https://github.com/jlov7/scaffold-arena/.github/workflows/release.yml@refs/tags/v0[.]9[.]1$' \
  "$IMAGE"

gh attestation verify "oci://$IMAGE" --repo jlov7/scaffold-arena
```

Never admit a mutable image tag such as `latest` as release evidence. Resolve and record the digest.

## Clean-environment reproduction

Artifact verification should be followed by installation smoke tests in an empty environment:

```bash
python -m venv /tmp/scaffold-arena-release-verify
/tmp/scaffold-arena-release-verify/bin/pip install \
  scaffold_arena_backend-0.9.1-py3-none-any.whl
/tmp/scaffold-arena-release-verify/bin/arena init \
  --yes \
  --path /tmp/scaffold-arena-release-workspace
/tmp/scaffold-arena-release-verify/bin/arena doctor \
  --workspace /tmp/scaffold-arena-release-workspace
```

For container admission, run the digest-pinned image with no provider credentials and verify health/readiness before configuring execution workers.

## Release failure behavior

The release workflow is fail-closed:

- a tag/metadata mismatch stops before building;
- a lightweight tag stops before building;
- repository verification failure stops before packaging;
- SBOM, checksum, signing, attestation, image-push, or image-signing failure prevents GitHub release creation;
- an existing GitHub release is never overwritten;
- manual dispatch never publishes.

Workflow artifacts from a failed run are diagnostic build output only. They are not public release evidence.

## Withdrawal and compromised-release response

Do not rewrite or replace published release assets under the same version.

For a defective but non-security release:

1. mark the GitHub release as withdrawn or prominently add a withdrawal notice;
2. update `release/release-metadata.json` to `withdrawn` in a new pull request;
3. document the reason and affected artifacts in the changelog;
4. stop recommending the affected OCI digest;
5. publish a new, incremented version through the full workflow.

For a suspected compromise:

1. follow `SECURITY.md` and avoid disclosing exploitable details prematurely;
2. disable the release environment or workflow if further publication must stop;
3. revoke compromised repository, package, deployment, or maintainer access;
4. preserve logs, attestations, tag objects, digests, and released bytes for investigation;
5. publish a security advisory and a superseding release when appropriate;
6. never delete evidence solely to make the compromised version disappear.

Sigstore transparency records and GitHub attestations are append-only evidence. A superseding statement can invalidate trust in a release; it cannot erase the historical signature.

## Repository settings that files cannot prove

The repository should separately require and periodically verify:

- protected `main`;
- required CI checks;
- CODEOWNER review;
- dismissal of stale approvals;
- no force pushes or branch deletion;
- tag protection for `v*`;
- release-environment approval, where available;
- immutable GitHub releases, where available.

`.github/CODEOWNERS`, workflow YAML, and this guide express intended policy. GitHub repository settings remain external operational evidence.
