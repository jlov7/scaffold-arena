# Non-Technical Explainer

## What Scaffold Arena Is

Scaffold Arena is a decision platform for AI execution quality. It helps teams answer a practical question:

> Should we spend on bigger models, or improve the orchestration around current models?

The product runs the same workload through multiple scaffold strategies, scores outcomes, and shows quality/cost trade-offs with evidence.

## Why Leaders Care

### Business value
- Better outcomes at lower cost.
- Faster confidence for AI deployment decisions.
- Clear evidence for stakeholder buy-in.

### Risk reduction
- Transparent scoring methodology.
- Repeatable experiments.
- Concrete failure analysis and corrective actions.

### Team enablement
- Shared language across product, engineering, and operations.
- Exportable reports for decisions, reviews, and audits.

## What You See In A Demo

1. Start in Onboarding lane and pick the role path.
2. Move to Configure lane, pick one task and one model.
3. Run four scaffolds side-by-side in Live run lane.
4. Review ranked score, cost, and speed in Results Summary lane.
5. Open Diagnostics lane for proof comparison and autopsy evidence.
6. Export a report.

## How To Read Results

- **Score**: overall quality against task expectations.
- **Cost**: actual token cost from provider usage fields.
- **Time**: wall-clock run duration.
- **QPD**: quality-per-dollar (higher is better value).

## Typical Outcome Pattern

In most runs, a stronger scaffold on a cheaper model beats a bare run on a more expensive model. This creates a compelling optimization path: improve orchestration first, then evaluate model upgrades where needed.

## Adoption Plan

### Phase 1
- Run current task set weekly.
- Baseline score/cost/time trends.

### Phase 2
- Apply autopsy-driven patches.
- Measure deltas and lock improved scaffolds.

### Phase 3
- Operationalize reporting for release/exec reviews.
- Expand tasks and model comparisons.

## Next Reading

- Product walkthrough: [`../walkthrough.md`](../walkthrough.md)
- Scorecard and evidence: [`../reviews/frontend-panel-scorecard.md`](../reviews/frontend-panel-scorecard.md)
- Usability results: [`../reviews/usability-test-results.md`](../reviews/usability-test-results.md)
