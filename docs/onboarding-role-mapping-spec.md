# Onboarding Design Spec: Role Mapping

This spec defines how onboarding adapts to each role so users get an immediate path without guesswork.

## Role Profiles

| Role | Primary goal | Default mode | Success signal |
| --- | --- | --- | --- |
| Evaluator | Find the highest-value scaffold for a benchmark | Guided | Completed run + reviewed winner evidence |
| Operator | Resolve failures and keep runs reliable | Guided | Blocker resolved + rerun succeeds |
| Analyst | Understand tradeoffs and evidence depth | Guided | Compared outputs and exported evidence |
| Executive | Reach decision quickly with minimal detail overhead | Advanced | Winner identified + concise report exported |

## Role-Specific Onboarding Checklist

### Evaluator
1. Choose task that matches benchmark objective.
2. Choose model and run arena.
3. Review score, cost, and time together.
4. Run proof comparison before final decision.

### Operator
1. Choose task and run.
2. If blocked, open Help Center and follow playbook action.
3. Confirm blocker is resolved and rerun.
4. Record mitigation in report/export notes.

### Analyst
1. Choose task/model and run.
2. Review scoreboard and panel-level evidence.
3. Compare outputs and autopsy weak scaffolds.
4. Export report with key deltas.

### Executive
1. Select benchmark and run once.
2. Read role summary card and winner rationale.
3. Export decision artifact.

## Interaction Rules

- The role selector is persistent per browser.
- Help Center sections and quick actions adapt by role.
- Results summary depth changes by role:
  - Executive: concise summary + decision CTA.
  - Analyst/Operator/Evaluator: richer evidence and next actions.

## Telemetry Mapping

- `persona_selected` validates role entry.
- `activation_completed` validates role activation success.
- Funnel and recovery slices are segmented by profile in dashboard surfaces.
