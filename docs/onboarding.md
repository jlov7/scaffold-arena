# Onboarding Guide

This guide helps new contributors or stakeholders become productive with Scaffold Arena quickly.

## 0. Choose Your Track

- Product/leadership: start with [`explainers/non-technical.md`](explainers/non-technical.md)
- Engineering: start with [`explainers/technical.md`](explainers/technical.md)
- Hands-on operators: start with [`getting-started.md`](getting-started.md)

## 1. First Hour Checklist

1. Read the project story in [`../README.md`](../README.md)
2. Run local setup from [`getting-started.md`](getting-started.md)
3. Complete one end-to-end run in [`walkthrough.md`](walkthrough.md)
4. Review architecture flow in [`architecture.md`](architecture.md)
5. Review quality gates in [`reviews/frontend-release-checklist.md`](reviews/frontend-release-checklist.md)

## 1.1 In-App Guided Path (No Guesswork)

The app is intentionally split into lanes so users do not absorb the entire system at once:

1. `/arena` -> **Onboarding lane**: pick role + guided mode.
2. `/arena` -> **Configure lane**: select task/model and run setup.
3. `/arena` -> **Live run lane**: monitor scaffold execution.
4. `/results` -> **Summary lane**: read winner/cost/time first.
5. `/results` -> **Diagnostics lane**: open diff/autopsy/proof only when needed.

If blocked anywhere in the flow:

1. Use the blocker card’s primary action.
2. Open **Help Center** from header `Help`, keyboard `H`/`F1`, or failure banners.
3. Use deterministic playbook actions (`Open settings now`, `Retry now`, `Open guided tour now`).

## 1.2 Persona Quick Starts

- **Evaluator:** Onboarding -> Configure -> Results Summary.
- **Operator:** Configure with guardrails -> Live run -> Diagnostics.
- **Analyst:** Configure -> Live run -> Diagnostics (diff/autopsy first).
- **Executive:** Configure -> Results Summary -> Export report.

## 2. Development Workflow

### Backend
- Start server: `uv run uvicorn main:app --reload --port 8000`
- Run tests: `uv run pytest -q`

### Frontend
- Start app: `pnpm dev`
- Validation gates:
  - `pnpm lint`
  - `pnpm test`
  - `pnpm build`
  - `pnpm test:e2e`
  - `pnpm test:a11y`

## 3. Core Concepts To Know

- Scaffold: orchestration strategy wrapping the model.
- Task: benchmark scenario with gold-standard references.
- Arena run: one task/model executed across multiple scaffolds.
- Proof comparison: 3-case experiment to show orchestration value.
- Autopsy: concrete failure analysis and patch suggestion.

## 4. Where To Ask Questions

- Product behavior and usage: [`user-guide.md`](user-guide.md)
- API and contracts: [`api-reference.md`](api-reference.md)
- Scoring details: [`evaluation.md`](evaluation.md)
- Reliability/rollback: [`ops/frontend-smoke-and-rollback.md`](ops/frontend-smoke-and-rollback.md)

## 4.1 Fast Troubleshooting Cheatsheet

- **Offline:** reconnect, then retry.
- **Token/auth blocker:** open settings and configure API token.
- **Retrying stream:** wait briefly; if it stalls, use Retry in banner.
- **Run failures (429/5xx/network):** follow Help Center playbook action first, then rerun.

## 5. Definition Of “Done”

Use these as non-negotiable checks before calling work complete:
- Tests and lint pass.
- No regressions in core arena/proof/autopsy/report workflows.
- Docs updated when behavior changes.
- Accessibility and performance gates still pass.
