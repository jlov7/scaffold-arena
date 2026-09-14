# Memory policy study — synthetic fixture walk-through

This example runs the complete bundled `offline-demo-v1` demonstration. The
StudyPack declares memory as one of its P/V/R/M factors, but the recorded pack
does not isolate or identify a new memory-policy effect. The command therefore
demonstrates fixture custody and deterministic protocol behavior only.

## Run

From the repository root:

```bash
uv run --project backend arena demo --path /tmp/scaffold-arena-memory-policy-study
```

Expected result: exit `0`, JSON `verdict=PASS`,
`mode=verified_fixture_replay`, `evidence_class=fixture`,
`study_pack=offline-demo-v1@1.0.0`, `verified_truth_table_rows=80`, and
`provider_execution_started=false`. The copied StudyPack and truth-table
digests must remain bound in the generated provenance. This is not a memory
policy result, model result, empirical effect, causal estimate, generalization
claim, or live-provider run.

Inputs and the exact expected fields are pinned in the [example manifest](manifest.json).
The focused checks are `backend/tests/cli_v1/test_demo_cli.py`,
`backend/tests/integration_v1/test_offline_demo_fixture_chain.py`, and
`backend/tests/examples_v1/test_public_examples.py::test_memory_policy_example_keeps_fixture_ceiling`.
The demo refuses a non-empty target and never overwrites it. Remove only the
temporary directory after inspection:

```bash
rm -rf /tmp/scaffold-arena-memory-policy-study
```

There is no dedicated memory-effect screenshot. Use the [product-tour
evidence map](../../docs/product-tour.md) and keep any Study Canvas image
labelled synthetic fixture; it must not show a memory-effect chart.
