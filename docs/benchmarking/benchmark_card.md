# Benchmark Card: Scaffold Arena Protocol v0.1

## Scope

This benchmark compares scaffold/orchestration strategies while holding task, model, and scoring contract fixed. It is intended to show whether scaffolds change measurable outcomes on specific task families.

## Task Families

- Structured extraction.
- Risk analysis.
- Research synthesis with citation integrity.
- Tool-use recovery or API/tool selection.
- Privacy-boundary and data minimization.
- Strategy-to-system compilation.

## Required Evidence

- Scenario schema and gold reference.
- Eval card with deterministic weight at or above 70 percent.
- Run artifact with model id, scaffold id, usage, cost, score, and evidence records.
- Run artifact validation against `specs/run-artifact.schema.json`.
- Statistical audit with repeated fixture controls and confidence intervals.
- Trace audit output for saved runs.
- Release gate output.

## Supported Claims

- A scaffold scored higher, cost more, cost less, or failed differently on a named scenario under a named model.
- A deterministic metric found a specific schema, citation, privacy, cost, or evidence failure.

## Unsupported Claims

- A scaffold is universally better.
- A model is generally better because it won a scaffold comparison.
- Fixture artifacts are live benchmark results.
- Synthetic-source tasks cite real publications.
- An external-validation ledger with zero records is external validation evidence.
