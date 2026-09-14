# Scaffold Arena product contract

## Purpose

Scaffold Arena is an open-source prospective measurement workbench for testing whether harness mechanisms change agent quality, reliability, safety, cost, latency, and failure profile. The current candidate provides protocol and fixture paths, not a measured causal result.

The governing comparison holds the model, task, tools, evidence, environment, and budget fixed while varying the scaffold mechanism.

## Boundary

Scaffold Arena is:

- a neutral experimental instrument;
- a harness-component workbench;
- a durable execution, evaluation, and trace-analysis system;
- a reproducible evidence packager;
- a local-first personal tool and self-hosted single-organisation platform.

It is not a model leaderboard, general agent runtime, replacement enterprise harness, self-improving production agent, SaaS multi-tenant control plane, or authority for confidential deployment decisions.

## Users

- Guided builders who need a meaningful offline result without editing JSON.
- Harness engineers who register and certify adapters without changing Arena core.
- Researchers who freeze hypotheses, designs, budgets, and analysis settings.
- Evaluation engineers who author deterministic graders, state oracles, faults, controls, and review rubrics.
- Trace analysts who align attempts and link diagnoses to raw evidence.
- Decision makers who need severe failures, uncertainty, cost, latency, and Pareto choices together.
- External reproducers who verify and rerun portable StudyPacks.
- Organisation administrators who operate OIDC, roles, storage, budgets, and audit activity.

## Primary journey

1. Import or select a versioned StudyPack.
2. Inspect scenarios, factors, controls, hypotheses, graders, and claim boundaries.
3. Freeze an immutable ExperimentSpec.
4. Pass capability, manipulation, budget, isolation, and adequacy preflight.
5. Execute replicated attempts through durable workers.
6. Apply independent deterministic evaluation and any calibrated review.
7. Analyze effects, interactions, consistency, severe failures, cost, latency, and Pareto frontiers.
8. Inspect aligned traces and state differences.
9. Export evidence, claim ledgers, and decision briefs with explicit limitations.

## Principles

- Evidence before claims.
- Severe failures cannot be averaged away.
- Missing usage is unknown, never zero.
- Agent narration cannot override system state.
- Unsupported capabilities fail before execution.
- Fixture, live, calibrated, cross-model, and independent evidence remain separately attributable.
- Guided and Lab presentations share one execution path.
- No provider starts implicitly during installation, startup, validation, or preflight.

## Current evidence

The 0.9.1 beta release candidate includes protocol-v1 validation and a synthetic 16-arm, 80-attempt offline fixture study. It is not published or deployed and does not include a published live-provider comparison, completed human calibration, or independent reproduction. See [evidence status](../evidence-status.md).
