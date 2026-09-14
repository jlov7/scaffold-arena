# Scaffold Arena in plain language

AI results depend on more than the model. The surrounding system decides what context the model sees, which tools it can use, how it recovers from failure, what it remembers, and how its answer is checked.

Scaffold Arena is an open-source workbench for testing those choices under controlled conditions.

## The question it answers

> If the model, task, tools, evidence, environment, and budget stay fixed, what changes when the harness changes?

A study can compare planning, verification, recovery, memory, routing, delegation, or other mechanisms without turning the result into a model leaderboard.

## What a study produces

- the exact frozen design;
- repeated attempts and durable traces;
- deterministic outcome checks and severe-failure gates;
- uncertainty, consistency, cost, and latency analysis;
- a record of exclusions and limitations;
- verifiable artifact receipts and portable exports.

The decision view shows which configurations remain useful after risk, cost, and reliability constraints are applied. It does not hide a severe failure inside an average score.

## What the bundled demonstration proves

The included offline StudyPack exercises the full workflow with synthetic fixtures: import, freeze, preflight, execution, evaluation, analysis, and evidence derivation. It proves that the instrument works against those declared fixtures.

It does **not** prove that one harness is better, that a result transfers to an enterprise, or that a deployment is secure. Those conclusions require live runs, human calibration where applicable, and independent reproduction.

## Where to start

- [Getting started](../getting-started.md)
- [User guide](../user-guide.md)
- [Evidence status](../evidence-status.md)
