# Provider-free runnable examples

These examples are the public command map for Scaffold Arena's local,
provider-free protocol boundaries. They use checked-in synthetic fixtures,
mocked browser routes, bounded state models, or mocked adapter transports. No
example starts a provider, reads credentials, posts a PR comment, or turns a
fixture `PASS`/`HOLD` into live, model-performance, causal, security,
deployment, human-calibration, or independent-reproduction evidence.

Every required example has one canonical command, an input manifest, an
expected result, a focused test boundary, cleanup instructions, and a
truthful screenshot status. Open the per-example README for the full command
and claim ceiling; the `manifest.json` beside it is the machine-readable
custody record.

## Required examples

### [Compare two harnesses](compare-two-harnesses/)

- Run: `uv run --project backend python examples/compare-two-harnesses/run.py --output /tmp/scaffold-arena-compare-two-harnesses.json`
- Expected: exit `2`, `HOLD`, second checked harness not supplied, source digests retained, no comparison emitted, provider/network false.
- Ceiling: one recorded fixture harness is admissible; no two-harness/model/performance/causal result.
- Test: [`test_compare_two_harnesses_fails_closed`](../backend/tests/examples_v1/test_public_examples.py)
- Cleanup: `rm -f /tmp/scaffold-arena-compare-two-harnesses.json`
- Screenshot: `HOLD` until a dedicated unavailable-comparison state is rendered; see the [product-tour evidence map](../docs/product-tour.md).

### [Context compaction ablation](context-compaction-ablation/)

- Run: `uv run --project backend arena harness-ci --replay examples/counterfactual-replay/fixture-replay.json --base examples/counterfactual-replay/fixture-base.json --candidate examples/counterfactual-replay/fixture-candidate.json --policy examples/counterfactual-replay/fixture-policy.json --output /tmp/scaffold-arena-context-compaction-report.json`
- Expected: exit `2`, `HOLD`, unknown usage retained, provider/network false, no PR comment.
- Ceiling: paired recorded replay/policy mechanics only; not a context-compaction benchmark, live replay, model result, or causal estimate.
- Test: [`test_context_compaction_example_preserves_unknown_usage`](../backend/tests/examples_v1/test_public_examples.py)
- Cleanup: `rm -f /tmp/scaffold-arena-context-compaction-report.json`
- Screenshot: `HOLD`; use the [product-tour evidence map](../docs/product-tour.md), not an invented ablation chart.

### [Memory policy study](memory-policy-study/)

- Run: `uv run --project backend arena demo --path /tmp/scaffold-arena-memory-policy-study`
- Expected: exit `0`, verified fixture `PASS`, 80 truth-table rows, `provider_execution_started=false`, memory factor declaration retained.
- Ceiling: bundled recorded fixture/protocol validation only; no memory-policy, model, empirical, causal, or live result.
- Test: [`test_memory_policy_example_keeps_fixture_ceiling`](../backend/tests/examples_v1/test_public_examples.py), plus the offline demo and fixture-chain tests.
- Cleanup: `rm -rf /tmp/scaffold-arena-memory-policy-study`
- Screenshot: `HOLD` for a dedicated memory-effect image; any Study Canvas capture must show the synthetic label and limitations.

### [Recovery fault injection](recovery-fault-injection/)

- Run: `uv run --project backend python scripts/check-lifecycle-model.py --depth 8 --generations 2`
- Expected: exit `0`, bounded model `status=pass`; no provider, network, worker kill, or production fault.
- Ceiling: bounded engineering state-model checks only; not production recovery, fault injection, availability, durability, security, or independent assurance.
- Test: [`test_recovery_example_runs_bounded_model`](../backend/tests/examples_v1/test_public_examples.py), plus lifecycle model tests.
- Cleanup: none expected.
- Screenshot: `HOLD`; a green state-model command is not a recovery result.

### [Permission boundary study](permission-boundary-study/)

- Run: `cd frontend && npx -y pnpm@10 exec playwright test tests/e2e/workbench-v1.spec.ts --grep "team chooser" --output=/tmp/scaffold-arena-permission-boundary-results`
- Expected: focused mocked team chooser passes; URL follows explicitly selected synthetic authorized memberships; no secret-like page/report values.
- Ceiling: fixture/client/API authorization contract only; not tenant isolation, deployment security, penetration testing, or independent assurance.
- Test: the team chooser E2E, backend team-authorization/auth tests, accessibility route check, and the manifest boundary.
- Cleanup: `rm -rf /tmp/scaffold-arena-permission-boundary-results`
- Screenshot: `HOLD` for a dedicated team chooser capture; do not present mock memberships as production isolation.

### [Local model harness comparison](local-model-harness-comparison/)

- Run: `uv run --project backend pytest backend/tests/adapters_v1/openai_compatible/test_adapter.py backend/tests/adapters_v1/certification/test_kit.py -q`
- Expected: mocked protocol/certification tests pass; no Ollama/LM Studio process, model output, or comparison is produced.
- Ceiling: protocol-only adapter conformance and endpoint pinning; not local-runtime availability, model quality, cost, latency, sandbox, or harness comparison.
- Test: the same focused adapter and certification tests.
- Cleanup: none; tests use mocked transports.
- Screenshot: `HOLD` for a blocked local-runtime readiness state; never add a model score to an image.

### [Harness PR regression](harness-pr-regression/)

- Run: `uv run --project backend arena harness-ci --replay examples/counterfactual-replay/fixture-replay.json --base examples/counterfactual-replay/fixture-base.json --candidate examples/counterfactual-replay/fixture-candidate.json --policy examples/counterfactual-replay/fixture-policy.json --output /tmp/scaffold-arena-harness-pr-regression-report.json --summary /tmp/scaffold-arena-harness-pr-regression-summary.md --comment-output /tmp/scaffold-arena-harness-pr-regression-comment.md`
- Expected: exit `2`, synthetic policy `HOLD`, unknown usage, three artifacts written, no provider/network request, no GitHub comment posted.
- Ceiling: provider-free policy/report generation over named synthetic files; not an actual code regression, live CI assurance, PR approval, or release gate.
- Test: [`test_harness_pr_regression_preserves_hold_artifacts`](../backend/tests/examples_v1/test_public_examples.py), Harness CI action/CLI/service tests.
- Cleanup: remove only the three named `/tmp/scaffold-arena-harness-pr-regression-*` files.
- Screenshot: `HOLD` with comment-not-posted language if a future Trace / Counterfactual Lab capture is added.

### [Counterfactual replay](counterfactual-replay/)

- Run: `uv run --project backend arena harness-ci --replay examples/counterfactual-replay/fixture-replay.json --base examples/counterfactual-replay/fixture-base.json --candidate examples/counterfactual-replay/fixture-candidate.json --policy examples/counterfactual-replay/fixture-policy.json --output /tmp/scaffold-arena-counterfactual-replay-report.json`
- Expected: exit `2`, replay/policy `HOLD`, unknown usage/cost, provider/network false, no live replay or posted comment.
- Ceiling: synthetic checkpointed paired replay and bounded policy mechanics only; not a benchmark, causal estimate, model result, or live replay.
- Test: [`test_counterfactual_replay_example_preserves_hold`](../backend/tests/examples_v1/test_public_examples.py), existing replay/Harness CI service and CLI tests.
- Cleanup: `rm -f /tmp/scaffold-arena-counterfactual-replay-report.json`
- Screenshot: `HOLD`; use the [product-tour evidence map](../docs/product-tour.md) for any fixture-backed Trace / Counterfactual Lab image.

## Additional examples

- [Arena Forge](arena-forge/) is an extra provider-free proposal/planner/process-safety example. It does not substitute for any required example above.
- [`run-offline-demo.sh`](run-offline-demo.sh) and [`verify-offline-fixture.sh`](verify-offline-fixture.sh) remain compatibility entry points for the full offline fixture chain. The memory-policy example is the canonical named walkthrough.

The governing boundaries are [evidence status](../docs/evidence-status.md),
[adapter certification](../docs/adapters/certification.md), and the
[counterfactual/Harness CI analysis](../docs/analysis/counterfactual-replay-harness-ci-v1.md).
