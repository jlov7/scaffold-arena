---
license: mit
language:
  - en
tags:
  - llm-evaluation
  - agents
  - orchestration
  - benchmark
  - reproducibility
pretty_name: Scaffold Arena 0.9 fixture package
task_categories:
  - text-generation
size_categories:
  - n<1K
---

# Scaffold Arena 0.9 fixture package

This is the retained, Hugging Face-compatible fixture package for Scaffold Arena 0.9. It contains legacy protocol-v0.1 scenarios and generated controls used to validate package and evaluation machinery.

Core claim:

> Same model. Different scaffold. Measurably different quality, reliability, cost, latency, and failure profile.

## What This Contains

- Protocol definition.
- JSON Schemas for scenarios, run artifacts, eval cards, scaffold cards, annotation records, and failure taxonomy.
- Six task families: extraction, risk, research, tool-use recovery, privacy boundary, and strategy-to-system.
- Fixture artifacts for schema validation.
- Trace-audit fixture demonstrating failure taxonomy coverage.
- Baseline-separation and negative-control specification.
- Statistical audit over generated fixture controls.
- External-validation ledger with zero completed external evidence recorded.

## What This Does Not Contain

- Live provider benchmark results.
- Real publications in the synthetic research task.
- Human annotation results.
- A universal scaffold leaderboard.
- Independent reproduction or public critique evidence.

## Intended Use

Use this as a protocol package or dataset-card draft for comparing scaffolds under fixed task/model conditions. Any public performance claim should include the exact model id, scaffold id, task family, evaluation profile, run artifact, trace audit, and release-gate output.

## Claim Boundary

Fixture artifacts validate protocol shape and failure coverage. They do not prove model performance. Synthetic scenarios are for reproducible scaffold evaluation and should not be interpreted as real customer, legal, medical, or research evidence.

## Citation

See `CITATION.cff` in the repository root.
