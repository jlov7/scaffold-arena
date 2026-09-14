# Counterfactual Replay and Harness CI v1

Counterfactual Replay is a provider-free custody and policy surface for comparing already-recorded base and candidate branches. Its claim ceiling is strict: a fixture is a fixture, a recorded paired replay is not causal proof, and a Harness CI `PASS` is not deployment, model-performance, or independent-assurance approval.

## Replay contract

One `CounterfactualReplayRequest` binds the shared pre-divergence inputs once:

- checkpoint and initial-state digests;
- pre-divergence trace, environment, dependency, model, and runtime digests;
- task-pack, evaluator, evaluator configuration, and evaluation configuration digests;
- distinct base and candidate Genome digests; and
- a blinded evaluator declaration.

Branches cannot supply their own environment, runtime, task pack, or evaluator. The only declared difference is one `mechanism_id`, with distinct before/after mechanism digests, a semantic diff containing exactly that mechanism, and an applied-control receipt. The contract rejects hidden multiple-mechanism changes, evaluator reuse of a branch Genome, evaluator unblinding, holdout overlap, a replay item outside the predeclared development cohort, overrun repetitions, causal-claim requests, and `unknown` usage or latency rendered as zero.

Allocation, primary endpoint, deterministic score weight (minimum 0.70), stopping rule, exclusions, and repetitions are bound before report construction. `live` is declaration-only: it requires a credentials attestation, positive budget, and policy digest, but this implementation does not receive credential material and never starts a provider.

## Evidence states and estimates

The report always emits this ladder, without collapsing the states:

| State | Meaning |
| --- | --- |
| `temporal_correlation` | Ordered observation only. |
| `diagnostic_divergence` | A recorded difference; diagnostic, not identified cause. |
| `paired_replay` | Both outcomes reference the common bound pre-divergence state. |
| `replicated_intervention` | Predeclared paired repetitions were recorded. |
| `confirmatory_eligibility` | Replication plus a separately declared holdout make a future confirmatory protocol eligible; this is not a confirmatory result. |

Quality, latency, and cost effects are candidate-minus-base paired means. With at least two records the report shows a normal-approximation 95% interval over the recorded paired differences. A single pair has no repeat-based interval. Incomplete provider usage makes cost `unknown`, never `$0`; incomplete timing makes latency `unknown`, never `0 ms`.

The causal-family measures below are deliberately present and unestimated unless their own assumptions are separately bound. v1 emits `null` values with `ineligible` states rather than deriving them from a paired fixture:

- intention-to-treat;
- opportunity;
- activation;
- fidelity failure; and
- treatment-on-the-treated.

## API and custody

All endpoints are project-scoped and return only report fields and digests. Raw source diffs, prompts, credentials, and trace contents are not persisted in the Counterfactual Replay or Harness CI tables.

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `POST` | `/api/v1/counterfactual-replays` | Validate and persist a content-addressed replay report. |
| `GET` | `/api/v1/counterfactual-replays/{report_digest}` | Recover a project-visible replay report. |
| `POST` | `/api/v1/harness-ci/checks` | Evaluate one replay report against a strict base/candidate policy. |
| `GET` | `/api/v1/harness-ci/checks/{report_digest}` | Recover a project-visible Harness CI report. |

Compatibility aliases are available at `/api/v1/counterfactual/replays` and `/api/v1/harness-ci-reports`. Exact content repeats are idempotent per project and request digest. Cross-project recovery is non-disclosing.

## Harness CI

Harness CI classifies the in-memory base-versus-candidate delta into known mechanism families (`context_compaction`, `retry_stopping`, and `permission_handling`) and reports recommended study packs. It returns JSON, a GitHub-step-summary body, and a PR-comment body artifact. It does not post a comment.

Policy checks cover exact one-mechanism alignment, new severe failures, quality regression, cost and latency ceilings, required cohorts, unknown usage, evidence maturity, repeat-based uncertainty, minimum fidelity, and process safety. Any failure makes `FAIL`; a missing/unknown prerequisite makes `HOLD`; only all passing checks return `PASS`.

The reusable composite action is [`.github/actions/harness-ci/action.yml`](../../.github/actions/harness-ci/action.yml). It accepts only replay/base/candidate/policy paths, invokes the provider-free CLI, appends the step summary through `GITHUB_STEP_SUMMARY`, and uploads JSON plus the PR-comment body. It accepts no provider credentials or live-run switch.

```yaml
- uses: ./.github/actions/harness-ci
  with:
    replay-contract: examples/counterfactual-replay/fixture-replay.json
    base: examples/counterfactual-replay/fixture-base.json
    candidate: examples/counterfactual-replay/fixture-candidate.json
    policy: examples/counterfactual-replay/fixture-policy.json
```

## Provider-free fixture reproduction

From the repository root:

```bash
uv run --project backend arena counterfactual-replay \
  --input examples/counterfactual-replay/fixture-replay.json

uv run --project backend arena harness-ci \
  --replay examples/counterfactual-replay/fixture-replay.json \
  --base examples/counterfactual-replay/fixture-base.json \
  --candidate examples/counterfactual-replay/fixture-candidate.json \
  --policy examples/counterfactual-replay/fixture-policy.json \
  --output harness-ci-report.json \
  --comment-output harness-ci-pr-comment.md
```

Both fixture commands intentionally return `HOLD` (exit code `2`) because provider usage and cost are unknown. That is the expected fixture outcome, not a failure to make the unknown look like success. The Workbench route `/workbench/counterfactual` is lazy-loaded, reports `$0.00` provider consumption for its fixture, and has no live credential entry point.
