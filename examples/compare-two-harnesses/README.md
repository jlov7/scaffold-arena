# Compare two harnesses — fail-closed fixture check

This example checks whether the bundled `offline-demo-v1` StudyPack binds two
distinct harness identities before a comparison is attempted. It currently
binds exactly one recorded harness (`offline-recorded`), so the command stops
with `HOLD`. It never duplicates that identity, invokes an adapter, starts a
provider, requests a network resource, or invents comparison values.

## Run

From the repository root:

```bash
uv run --project backend python examples/compare-two-harnesses/run.py --output /tmp/scaffold-arena-compare-two-harnesses.json
```

Expected result: exit `2`, JSON `verdict` `HOLD`,
`code=second_checked_harness_not_supplied`, `provider_execution_started=false`,
`network_requested=false`, and SHA-256 digests for the StudyPack and runtime
truth table. A future `PASS` may only mean that two independently declared
recorded fixture harnesses are admissible; this checker still does not emit a
model, quality, cost, latency, or causal comparison.

Inputs are pinned by [the example manifest](manifest.json),
[`study-pack.json`](../../study_packs/offline-demo-v1/study-pack.json), and
[`runtime-truth-table.json`](../../study_packs/offline-demo-v1/fixtures/runtime-truth-table.json).

## Test and cleanup

The focused smoke test is
`backend/tests/examples_v1/test_public_examples.py::test_compare_two_harnesses_fails_closed`.
The runner refuses an existing output path. Remove only the explicitly named
temporary file when finished:

```bash
rm -f /tmp/scaffold-arena-compare-two-harnesses.json
```

There is no dedicated screenshot: the required comparison state is not
rendered by the current product-tour capture set. Keep this example linked to
the [product-tour evidence map](../../docs/product-tour.md) without presenting
an unavailable comparison chart as evidence.
