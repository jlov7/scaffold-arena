# Legacy protocol v0.1 fixture reproducibility

This document records the reproducibility contract for the retained protocol-v0.1 fixture package. The current protocol-v1 product is documented in the [main documentation index](../README.md).

## Required For Public Evidence

- Scenario id and task family.
- Protocol version and artifact schema version.
- Model id and provider settings.
- Scaffold id and scaffold card.
- Evaluation profile and eval card.
- Output schema and gold reference.
- Token usage, cost, wall-clock time, and API call count.
- Deterministic metric breakdown.
- Evidence records for claims.
- Limitations and synthetic-source labels where applicable.

## Local Commands

```bash
./scripts/verify-all.sh
uv run --project backend python scripts/trace-audit.py --input backend/tests/fixtures/trace_audit/sample_runs.json
uv run --project backend python scripts/validate-protocol-artifacts.py
uv run --project backend python scripts/validate-frontier-package.py
uv run --project backend python scripts/run-benchmark-pack.py --mode fixture
uv run --project backend python scripts/check-prior-art-positioning.py --check
uv run --project backend python scripts/check-benchmark-evidence.py
uv run --project backend python scripts/check-benchmark-leakage.py --check
uv run --project backend python scripts/validate-research-integrity.py
uv run --project backend python scripts/check-external-validation.py --check
uv run --project backend python scripts/check-human-calibration.py --check
uv run --project backend python scripts/check-live-evidence.py --check
uv run --project backend python scripts/check-release-bundle.py --check
uv run --project backend python scripts/generate-release-manifest.py --check
```

## Reviewer Reproduction Contract

`outputs/huggingface_package_manifest.json` records the no-key reviewer contract:

- run `./scripts/verify-all.sh`;
- expect backend, package-build, prior-art positioning, benchmark-evidence, benchmark-leakage, human-calibration packet, external-validation audit, live-preflight, live-evidence, release-bundle, Hugging Face package, claim-boundary, frontend, and manifest checks;
- treat the result as package-integrity evidence, not model-performance evidence.

The same manifest records the key-required live follow-up command. That command must produce `outputs/live_benchmark_runs/*.json` and `outputs/live_benchmark_summary.json`, and `scripts/check-live-evidence.py --check` must pass, before any live benchmark claim is allowed.

## Benchmark Leakage Audit

`outputs/benchmark_leakage_audit.json` checks the scenario pack, built-in task prompts, fixture outputs, and scenario-role alignment for obvious benchmark leakage. It rejects scenario prompts that expose gold-reference metadata, expected roles, control labels, hidden score fields, or exact gold-reference tokens; it also rejects fixture outputs that contain evaluation metadata. Its passing state improves fixture-contract hygiene. It is not a guarantee against all benchmark contamination, not live benchmark evidence, not human calibration evidence, and not external validation evidence.

## Live Evidence Audit

`outputs/live_evidence_audit.json` is a blocker ledger while no live runs exist. Its current passing state means there are zero malformed live artifacts in the release package; it is not live benchmark evidence. If live artifacts are added later, the audit requires the planned `72` artifacts, live mode labels, complete task/scaffold/repeat coverage, positive provider token usage, cost values derived from `backend/config/models.py`, a matching live summary, and limitations that keep human calibration and external validation separate.

## Human Calibration Audit

`outputs/human_calibration_audit.json` is a blocker ledger while no completed annotations exist. Its current passing state means the Protocol-v1 annotation packet is ready and no malformed annotation evidence is present; it is not human calibration evidence. If completed annotations are added later, `scripts/check-human-calibration.py --check` validates assigned three-or-more independent pseudonymous reviews per target, normalized `[0,1]` scores, `blind_to_scaffold=true`, a strict `> 0.20` per-dimension conflict rule, exactly one bound adjudication for every conflict, and consistency with `outputs/external_validation.json`. A local protocol-completion digest cannot mint a receipt; verified authority and external attestation remain required.

## External Validation Audit

`outputs/external_validation_audit.json` is a blocker ledger while no independent reproduction, public critique, or human annotation batch records exist. Its current passing state means the external-validation ledger is empty and internally consistent; it is not external validation evidence. If external evidence is added later, `scripts/check-external-validation.py --check` validates the ledger schema, status transitions, public critique URLs, reproduction artifact references, annotation-batch artifact references, and the boundary that external evidence does not by itself prove live benchmark performance or human calibration.

## Release Bundle Audit

`outputs/release_bundle_audit.json` validates the local publication bundle before archive or tag creation. It checks manifest coverage for release-facing package files, claim-boundary docs, generated release reports, and gate scripts; rejects duplicate, missing, absolute, escaping, build/cache, or private-local-path artifacts; and treats `docs/release/frontier_release_manifest.json` as the bundle root rather than a self-hashed artifact. Its passing state is release-bundle hygiene evidence only. It is not a published archive, not a clean-clone proof, not live benchmark evidence, and not external validation or human calibration evidence.

## Clean-checkout verification

`./scripts/verify-clean-clone.sh` clones the committed revision into an isolated temporary directory and runs the authoritative gate. This is source and build reproducibility evidence for that revision; it is not provider, deployment, human-calibration, or independent-reproduction evidence.

## Interpretation

A passing release gate proves the repo is internally consistent and protocol artifacts validate. It does not prove live model performance unless run artifacts were generated by actual provider runs and labeled accordingly.

## Provenance

The frontier release manifest is `docs/release/frontier_release_manifest.json`. It records SHA-256 hashes for release-facing protocol, schema, fixture, audit, gate-script, and packaging artifacts. `scripts/check-release-bundle.py --check` verifies that the manifest covers the release-facing package surface and that the bundle does not include private local paths or disallowed build/cache material. If any listed artifact changes without regenerating the manifest, the release gate fails.

## External Validation Ledger

`outputs/external_validation.json` records independent reproduction, public critique, and human annotation batches. `outputs/external_validation_audit.json` records whether those ledger entries are valid enough to count. A v1 human batch requires at least three annotators, resolved conflicts, agreement, adjudication, immutable review-completion, and authority-attestation artifact references. The current empty state is intentional: the files prevent ambiguity, but it does not lift any external-validation cap until concrete external evidence is recorded.
