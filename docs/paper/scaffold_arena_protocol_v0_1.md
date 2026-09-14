# Scaffold Arena Protocol v0.1

> Historical proposal and duplicate v0.1 reference. It is not a published paper or the authority for the current candidate. Use the Protocol-v1 schemas and [evidence status](../evidence-status.md) for current boundaries.

## Abstract

Scaffold Arena Protocol v0.1 is an evidence-first benchmark protocol for evaluating the orchestration around large language models. The protocol holds model and task fixed while varying the scaffold: planning, schema repair, retry behavior, tool selection, critique, memory, privacy boundaries, and evidence capture. The central claim is narrow: same model, different scaffold, measurable differences in quality, reliability, cost, latency, and failure profile.

## Motivation

Model-only evaluation misses a large part of production behavior. A model wrapped in a bare prompt and the same model wrapped in a verification, recovery, and evidence scaffold can fail differently even when the underlying weights are unchanged. Scaffold Arena turns that difference into a protocol object rather than a dashboard impression.

## Protocol Objects

- Scenario: task input, output schema, gold reference, deterministic metrics, evidence requirements, and claim boundary.
- Eval card: scoring weights, deterministic share, pass thresholds, and failure modes.
- Scaffold card: scaffold phases, evidence controls, overreach risks, and limitations.
- Run artifact: model id, scaffold id, output, metrics, evaluation, evidence, and limitations.
- Failure taxonomy: deterministic trace-audit vocabulary with severity, evidence, recommendation, regression key, and suggested fixture.

## Task Families

The initial protocol pack covers structured extraction, risk analysis, research synthesis, tool-use recovery, privacy-boundary/data minimization, and strategy-to-system compilation. Each family keeps deterministic scoring at or above 70 percent.

## Evaluation Design

Deterministic metrics anchor the score. Optional judge metrics can add qualitative signal but cannot override deterministic failures. Costs must come from provider usage fields and the centralized price table. Synthetic sources are labeled and cannot be cited as real publications.

## Evidence And Reproducibility

Public evidence requires schema-validated artifacts, trace-audit output, release-gate output, and claim-boundary notes. Fixture artifacts are allowed for protocol validation but must not be described as live benchmark results.

## Negative Controls

The protocol includes fixture calibration cases for each task family. Each case names positive controls, negative controls, and expected separation. This guards against metrics that reward plausible-looking but unsafe or unsupported outputs.

## Human Annotation Readiness

The protocol includes a human annotation schema and rubric for external review. Annotation readiness is not the same as validated human evidence; public human-validation claims require independent annotations and agreement reporting.

## Limitations

This release is a protocol and workbench artifact. It does not claim universal scaffold superiority, general model quality, production safety, or external human validation. Live provider-run benchmark claims should be published only with run artifacts, trace audits, and the exact release gate output used to validate them.
