# Provider-free Counterfactual Replay fixture

`fixture-replay.json` binds one synthetic, checkpointed paired context-compaction intervention. It has two repetitions, a distinct holdout declaration, and unknown provider usage by design. It is not a benchmark, model-performance result, causal estimate, or live replay.

Run the single canonical Harness CI check from the repository root:

```bash
uv run --project backend arena harness-ci \
  --replay examples/counterfactual-replay/fixture-replay.json \
  --base examples/counterfactual-replay/fixture-base.json \
  --candidate examples/counterfactual-replay/fixture-candidate.json \
  --policy examples/counterfactual-replay/fixture-policy.json \
  --output /tmp/scaffold-arena-counterfactual-replay-report.json
```

The expected result is exit `2` with `HOLD`, because fixture provider usage is
unknown and is never converted to zero. The report also retains
`provider_execution_started=false`, `execution_started=false`, and
`network_requested=false`; no live replay or PR comment is produced. This
example is synthetic checkpointed paired-replay and bounded policy mechanics,
not a benchmark, causal estimate, model result, or live replay. See [the full
v1 boundary](../../docs/analysis/counterfactual-replay-harness-ci-v1.md).

The CLI refuses an existing output path. Remove only the named temporary
report:

```bash
rm -f /tmp/scaffold-arena-counterfactual-replay-report.json
```

Inputs, expected fields, cleanup, and the screenshot boundary are pinned in
the [example manifest](manifest.json). The focused smoke is
`backend/tests/examples_v1/test_public_examples.py::test_counterfactual_replay_example_preserves_hold`.
No dedicated screenshot is claimed; use the [product-tour evidence
map](../../docs/product-tour.md) for the fixture-backed Trace / Counterfactual
Lab surface.
