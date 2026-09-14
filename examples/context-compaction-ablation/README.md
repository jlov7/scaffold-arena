# Context compaction ablation — recorded paired replay

This example exercises the existing provider-free checkpointed replay and
Harness CI policy path with the named context-compaction intervention. The
inputs are recorded JSON fixtures; no context window, model, provider, or
worker is started. Unknown provider usage remains unknown and is never changed
to zero.

## Run

From the repository root:

```bash
uv run --project backend arena harness-ci --replay examples/counterfactual-replay/fixture-replay.json --base examples/counterfactual-replay/fixture-base.json --candidate examples/counterfactual-replay/fixture-candidate.json --policy examples/counterfactual-replay/fixture-policy.json --output /tmp/scaffold-arena-context-compaction-report.json
```

Expected result: exit `2`; the JSON report has `verdict=HOLD`,
`usage_state=unknown`, `provider_execution_started=false`,
`execution_started=false`, and `network_requested=false`. This is paired
replay and policy mechanics only—not a context-compaction benchmark, model
performance result, live replay, or causal estimate. The CLI does not post a
PR comment unless a caller separately supplies an output path for one (this
entry point does not).

Inputs, expected fields, and the exact cleanup target are pinned in the
[example manifest](manifest.json). The focused checks are the existing
counterfactual/Harness CI CLI and service tests plus
`backend/tests/examples_v1/test_public_examples.py::test_context_compaction_example_preserves_unknown_usage`.

Remove only the temporary report after inspection:

```bash
rm -f /tmp/scaffold-arena-context-compaction-report.json
```

There is no dedicated screenshot for this example in the current capture set;
see the [product-tour evidence map](../../docs/product-tour.md) for the
fixture-backed Trace / Counterfactual Lab boundary.
