# Recovery fault injection — bounded lifecycle model

This example runs the deterministic bounded invocation/reservation lifecycle
model. It checks generation fencing, stale-result admission, cancellation,
duplicate request identity, unknown usage, reservation monotonicity, and budget
commit invariants without killing a worker, delaying a real provider, making a
network request, or mutating production state.

## Run

From the repository root:

```bash
uv run --project backend python scripts/check-lifecycle-model.py --depth 8 --generations 2
```

Expected result: exit `0`, JSON `status=pass`, bounded-model metadata, and the
required invariant names. This is bounded engineering state-model evidence
only—not a production recovery, fault-injection, availability, durability,
security, or independent-assurance result. A green model command does not mean
that a real worker fault was injected.

The focused checks are
`scripts/tests/test_lifecycle_model.py`,
`backend/tests/execution_v1/test_lifecycle_formal_model.py`, and
`backend/tests/examples_v1/test_public_examples.py::test_recovery_example_runs_bounded_model`.
No persistent output is created and no cleanup is required. If a local test
harness creates a cache, remove only that isolated cache; do not clean the
repository.

There is no dedicated recovery screenshot: the product-tour Run Cockpit and
Counterfactual Lab states remain the honest blocked/fixture surfaces. See the
[product-tour evidence map](../../docs/product-tour.md).
