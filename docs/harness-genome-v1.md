# Harness Genome v1

Harness Genome v1 is Scaffold Arena's strict, content-addressed descriptor for a declared harness stack. It records configuration and evidence links; it does not execute a provider, grant permissions, or certify an external framework.

The single deterministic projection has three views:

- Mechanism graph: declared components, relations, protocols, and intervention surface.
- Execution graph: only observed runtime references explicitly bound by the descriptor.
- Evidence graph: source custody, digests, receipts, authority ceilings, and exclusions.

Every cross-graph edge is explicit and provenance-bound. Missing evidence is reported as unknown or held; the browser must not infer joins from raw records.

`arena genome validate --path descriptor.json`, `arena genome diff --before a.json --after b.json`, and `arena genome project --path descriptor.json` are provider-free JSON commands. The API exposes project-scoped registration, inspection, graph projection, semantic diff, catalog inspection, and local descriptor certification under `/api/v1`.

## Standards and claim boundary

The bundled catalog is source-dated reference data. It distinguishes Agent Client Protocol (ACP v1) from the historical Agent Communication Protocol migration alias to A2A. MCP, A2A, OpenTelemetry, agent SDKs, and CLIs remain catalog or import metadata unless a named local receipt says otherwise.

The ACP v1 schema bundle is vendored from the official source commit `5e89c71497fe07dd4ae633c181a17224f4a8956d` and bound by its recorded SHA-256 custody digest. M1 ships no executable ACP process runner or runtime receipt. `GET /api/v1/acp/registry`, `POST /api/v1/acp/certify`, `POST /api/v1/acp/runs`, `POST /api/v1/acp/runs/{bridge_id}/cancel`, and `GET /api/v1/acp/runs/{bridge_id}/events` are named lifecycle seams that return typed non-executing HOLD. They never admit a caller registry, identity, argv, launcher, prompt, workspace, policy, or attestation. A future deployment must supply a service-owned captured registry, pinned distribution bytes, full fixed argv, and a verifiable operator sandbox launcher before an execution surface can be considered; that surface is unshipped. Fixture launcher evidence is not a containment proof. The runtime and UI activation/inspection surfaces are M2 work; this M1 Graph IR exposes only declared material plus truthful unknown/HOLD states.

Operator-supplied binary archives are admitted only through the explicit offline installer. It snapshots bytes before parsing, verifies the supplied SHA-256, rejects traversal, Unicode/case collisions, links, devices, FIFOs, sparse files, reserved Windows names, compression bombs, and unsupported formats, then extracts atomically to a content-addressed cache. Admission and extraction never install a package, modify an ambient environment, or execute the artifact.

## Local certification

Genome certification checks schema and canonicalization only and returns `PASS`, `HOLD`, or `FAIL` with the fixed ceiling `local_descriptor_fixture_only`. A pass does not elevate a descriptor's declared authority or make an integration claim-bearing.
