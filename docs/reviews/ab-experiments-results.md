# A/B Experiments Results

Date: 2026-02-19

## Experiment 1: Tour Entry Flow
- Experiment: `tour_entry`
- Variants:
  - `auto_open`
  - `cta_only`
- Validation:
  - `frontend/tests/e2e/experiments.spec.ts`
  - `tour_entry auto_open variant opens guided tour on first load`
  - `tour_entry cta_only variant does not auto-open guided tour`
- Result: Both variants pass and produce distinct behaviors as designed.

## Experiment 2: Post-Run Action Order
- Experiment: `post_run_rail_order`
- Variants:
  - `compare_first`
  - `export_first`
- Validation:
  - `frontend/src/components/journey/PrimaryCtaRail.test.tsx`
  - verifies button ordering changes based on variant assignment
- Result: Both variants pass and ordering behavior is deterministic.

## Conclusion
- Two experiments are implemented, exposed, and validated with automated tests.
- CI now enforces regression protection for experiment behavior via frontend test and coverage gates.
