# Scaffold Arena Protocol v0.1

> Historical v0.1 reference. Protocol-v1 schemas and [evidence status](../evidence-status.md) govern the current candidate. This document describes a proposed comparison design, not a current result or claim authorization.

## Purpose

Scaffold Arena Protocol v0.1 defines how this repo evaluates scaffold quality around LLM systems. It is not a model leaderboard. It is a protocol for comparing orchestration strategies while holding the task, model, and evidence requirements fixed.

The protocol claim is narrow:

> Same model. Different scaffold. Measurably different quality, reliability, cost, latency, and failure profile.

## Core Objects

### Scaffold

A scaffold is the orchestration wrapped around a model call. It may include planning, schema repair, retry logic, tool selection, critique, memory, validation, or patch-rerun behavior. A scaffold card must explain its phases, control boundaries, risks of overreach, and expected evidence.

### Task Pack

A task pack is a set of scenarios with schemas, gold references, deterministic metrics, evidence requirements, and claim boundaries. A task pack is benchmark-worthy only if deterministic scoring carries at least 70 percent of the score.

### Run Artifact

A run artifact is a machine-readable record of one scaffold attempt on one scenario. It must include run identity, protocol version, scenario id, model id, scaffold id, output, metrics, evaluation, evidence, and known limitations.

### Eval Card

An eval card defines a task family's scoring model. It lists deterministic metrics, optional judge metrics, total deterministic weight, pass thresholds, failure modes, and what the score can and cannot support.

### Scaffold Card

A scaffold card describes one scaffold strategy. It lists phases, configuration, evidence controls, overreach risks, and expected failure modes. It must not claim universal superiority.

## Evidence Model

Every protocol claim must be grounded in at least one of:

- Scenario schema and gold references.
- Deterministic metric output.
- Provider usage fields and centralized cost calculation.
- Run artifact with output, metrics, and evaluation.
- Trace-audit finding with severity, evidence, recommendation, regression key, and suggested fixture.
- Release gate output.

Fixture samples are allowed as protocol examples, but they must be labeled as samples or fixtures. They cannot be described as live benchmark results.

## Reproducibility Requirements

- Publish the scenario schema, eval card, scaffold card, and run-artifact schema.
- Use temperature 0 or record the exact generation settings.
- Record model id, scaffold id, task family, evaluation profile, token usage, cost, and wall-clock time.
- Keep synthetic sources labeled in task prompts, output views, and reports.
- Validate sample protocol artifacts in the release gate.
- Validate generated benchmark run artifacts against the public run-artifact schema.
- Publish statistical audit outputs for fixture controls before live claims.
- Preserve trace-audit fixtures that exercise failure taxonomy coverage.

## Historical claim rules

The following rules describe the v0.1 design. Current claims remain subject to Protocol-v1 gates and the evidence-status ledger.

- A scaffold scored higher than another scaffold on a named scenario under a named model and evaluation profile.
- A scaffold used more or fewer tokens or dollars based on reported provider usage.
- A failure class was detected in a stored trace by the trace audit.
- A task family uses deterministic-first scoring if the eval card shows deterministic weight at or above 70 percent.

## Disallowed Claims

- This protocol proves one model is better than another unless the benchmark was configured as a model comparison and the limitations are stated.
- Fixture samples are production benchmark results.
- Synthetic source tasks use real publications.
- A scaffold is generally superior across domains without cross-task evidence.
- Cost savings are real unless provider usage fields and price-table inputs are present.
- Unsupported claims, privacy-boundary violations, or scaffold overreach can be ignored because the final score is high.

## Versioning

Protocol v0.1 is a repo-local benchmark contract. Breaking changes to scenario, run artifact, eval card, scaffold card, or taxonomy schemas should update the protocol version and release notes.
