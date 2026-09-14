# Harness PR regression — provider-free Harness CI artifacts

This example runs Harness CI over the four checked-in synthetic replay,
base, candidate, and policy inputs. It creates a JSON report, step summary,
and retained PR-comment body under `/tmp`; it never posts a GitHub comment and
never starts a provider or network request. A retained comment body is an
artifact, not a posted PR regression signal.

## Run

From the repository root:

```bash
uv run --project backend arena harness-ci --replay examples/counterfactual-replay/fixture-replay.json --base examples/counterfactual-replay/fixture-base.json --candidate examples/counterfactual-replay/fixture-candidate.json --policy examples/counterfactual-replay/fixture-policy.json --output /tmp/scaffold-arena-harness-pr-regression-report.json --summary /tmp/scaffold-arena-harness-pr-regression-summary.md --comment-output /tmp/scaffold-arena-harness-pr-regression-comment.md
```

Expected result: exit `2`, report `verdict=HOLD`, `usage_state=unknown`,
`provider_execution_started=false`, `execution_started=false`,
`network_requested=false`, and all three temporary artifacts written. The
policy/report result is synthetic provider-free mechanics only—not an actual
harness code regression, live CI assurance, PR approval, or release gate.

Inputs, expected fields, and output custody are pinned in the [example
manifest](manifest.json). The focused checks are
`scripts/tests/test_harness_ci_action.py`,
`backend/tests/cli_v1/test_counterfactual_harness_ci_cli.py`, the service
tests, and `backend/tests/examples_v1/test_public_examples.py::test_harness_pr_regression_preserves_hold_artifacts`.
The CLI refuses to overwrite existing artifacts. Remove only the three named
files after inspection:

```bash
rm -f /tmp/scaffold-arena-harness-pr-regression-report.json /tmp/scaffold-arena-harness-pr-regression-summary.md /tmp/scaffold-arena-harness-pr-regression-comment.md
```

There is no dedicated PR screenshot. See the [product-tour evidence
map](../../docs/product-tour.md) for the Trace / Counterfactual Lab boundary;
the image must say `HOLD`, unknown usage, and comment-not-posted if a future
capture is added.
