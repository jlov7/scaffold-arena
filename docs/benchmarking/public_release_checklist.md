# Candidate package checklist

This checklist records local package and fixture readiness. It is not a public-release approval, and checked items do not establish publication, deployment, live benchmark evidence, human calibration, or independent reproduction. The current candidate remains undeployed; see [evidence status](../evidence-status.md).

- [x] `./scripts/verify-all.sh` has a recorded exact-tree pass.
- [x] Protocol, scenario, run-artifact, eval-card, scaffold-card, and failure-taxonomy schemas are present and validate in the repository gate.
- [x] The annotation schema and sample annotation validate.
- [x] Built-in fixture task families, deterministic-weight policy, baseline separation, and negative controls are present.
- [x] Generated fixture artifacts and the fixture statistical audit validate.
- [x] External-validation status, dataset-card draft, citation metadata, provenance inputs, and trace-audit fixture are present with stated boundaries.
- [x] Sample artifacts and synthetic sources are labelled.
- [x] README and evidence status state the supported and unsupported claims.

## Required before a public release

- [ ] Verify the exact target repository, its history, hosted logs and artifacts, and its private vulnerability-reporting route.
- [ ] Run all release gates for the exact candidate and retain the resulting receipts.
- [ ] Complete the tag-gated publication workflow and verify its published artifacts, signatures, attestations, and release record.
- [ ] Recheck the evidence status; do not promote fixture or local validation into live-provider, human-calibrated, or independently reproduced evidence.
