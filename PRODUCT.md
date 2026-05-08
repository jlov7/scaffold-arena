# Scaffold Arena Product Context

## Register

product

## Product Purpose

Scaffold Arena is a scaffold engineering workbench for evaluating how orchestration around large language models changes output quality, reliability, and cost. The core workflow is Compare, Diagnose, Patch, Rerun, Export Audit Report.

## Audience

- Enterprise AI evaluators who need a credible proof that scaffold design changes outcomes.
- Research-lab operators who need repeatable experiments, traceable evidence, and a clear path from failure diagnosis to patch rerun.
- Analysts and technical leads who need to explain winner quality, cost, latency, and failure evidence to stakeholders.
- Open-source contributors who need a serious local product surface that is easy to inspect and extend.

## Product Principles

- Evidence first: every important claim should be connected to scores, output differences, timeline events, usage, cost, or autopsy evidence.
- Fast orientation: the first screen should make the current experiment, system health, and next action obvious without reading documentation.
- Serious research-lab tone: calm, precise, dense when useful, visually distinctive without marketing theatrics.
- Operator trust: key storage, preflight status, budget, connection state, and failure recovery should be visible and legible.
- No synthetic ambiguity: synthetic sources must remain clearly labeled wherever task or report context appears.

## Primary Workflows

1. Configure an experiment with a task, model, scaffold set, and run options.
2. Run the arena through GET-only SSE streaming after `POST /api/runs`.
3. Review the winner using deterministic scores, cost, latency, and output evidence.
4. Run the three-case proof comparison: cheap+winning, expensive+bare, expensive+winning.
5. Run autopsy, apply a machine-applicable patch, rerun, and compare the delta.
6. Export a report or run bundle for audit and review.

## Tone

Precise, spare, and operational. Prefer concrete labels over marketing language. Avoid hype, jokes, decorative badges, and generic AI-product claims.

## Anti-References

- Generic dark SaaS dashboards made of repeated bordered cards.
- Purple/blue AI gradients, decorative glow fields, or glassmorphism as atmosphere.
- Hero/landing-page layouts that delay access to the actual tool.
- Monospace everywhere. Use monospace for data, code, IDs, and traces only.
