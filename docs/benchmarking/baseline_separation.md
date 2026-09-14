# Baseline Separation And Negative Controls

Frontier-grade benchmark work needs negative controls. A benchmark that only rewards good-looking outputs can fail silently: every scaffold looks plausible, and no one knows whether the metrics separate good behavior from bad behavior.

`docs/benchmarking/baseline_separation.json` defines fixture calibration cases for each task family. These are not live provider results. They are protocol checks that state what the deterministic metrics must be sensitive to.

## Required Separation

Each task family has:

- A positive control that should score high.
- At least two negative controls that should score materially lower.
- An expected separation of at least 20 points.
- A claim boundary explaining what the calibration does and does not prove.

## Why This Matters

This is the main defense against benchmark theater. If a task family cannot separate a valid output from a known-bad output, it is not ready for public performance claims.
