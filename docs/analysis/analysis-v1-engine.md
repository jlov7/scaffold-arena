# Analysis v1 report engine

`analysis_v1.engine.build_analysis_report()` is a pure boundary between
persisted attempt data and a JSON-serialisable Analysis v1 report. It does not
read storage, call providers, execute traces, or fit a model.

The strict frozen `AnalysisInput` rejects duplicate attempt IDs,
cross-experiment records, non-finite values, unregistered factor assignments,
forged costs, and incomplete preregistered paired effects. Every report is
stably ordered and has a SHA-256 `canonical_hash` over its content excluding
that field.

Durable admission supplies each record's `pair_id`, variant, cluster, and
one-based repetition from explicit execution metadata only. The controller
persists an `analysis_pair_id` bound to the frozen experiment, scenario pair,
harness, endpoint/model, and repetition; it is shared across factor cells and
clean/stress peers but never across repetitions. Legacy executions without
that binding HOLD. Factor levels retain their protocol types (`string`,
`integer`, or `boolean`), so `false` is never rewritten as the string
`"False"`. Missing trace-completeness evidence is false, and only the latest
usage-ledger row may establish reconciled cost.

## Episode denominator and retry custody

An **Episode** is the preregistered randomized scenario × harness × factor ×
model × repetition unit. An **attempt** is one physical execution inside that
episode. A transient infrastructure or provider retry is not a new repetition
and never adds a causal, pass@1, pass@k, pass^k, or effect denominator row.

Analysis emits exactly one record per episode. A multi-attempt episode is
admissible only when its attempts form a contiguous ordinal chain, every retry
request names its immediate predecessor with `retry_of_attempt_id`, and every
pre-final attempt has a persisted `transient`, `transient_adapter`, or
`transient_provider` classification. Branches, gaps, non-transient retries,
or ambiguous evaluator evidence HOLD. The final attempt supplies the evaluator
outcome; pre-final infrastructure failures are not task failures.
Some worker-stage transient failures have no terminal envelope. Their queued
envelope, persisted terminal status, classification, and retry link remain
mandatory; the missing terminal envelope makes that episode's cost and latency
unknown rather than being fabricated or zero-filled.

Every record and chart series carries its immutable `constituent_attempt_ids`
so a figure remains auditable to all physical attempts while its denominator
remains episodes. Episode cost is reconciled only if every constituent cost is
reconciled; otherwise it is unknown. Episode latency is the sum of constituent
terminal durations only when all terminal timestamps are valid. Trace
completeness and manipulation fidelity are conjunctions across constituents.
The continuous metrics `infrastructure_retry_count` and
`recovered_transient_failure` describe retry behavior without converting a
recovered infrastructure fault into a task severe failure.

Analysis also binds the queued request envelope in `request_metadata.envelope`
to the worker-produced terminal envelope in `result_metadata.terminal_envelope`.
The queued envelope must remain `queued`; its attempt and episode identities,
ordinal, provider/model/endpoint pin, harness, factors, budget, provenance,
request hash, and queue timestamp must exactly match the terminal envelope.
For completed attempts, the terminal response hash must exactly equal both the
persisted output artifact digest and `result_metadata.response_hash`; terminal
endpoint observations must match persisted provider usage when usage is
present. Missing or legacy terminal bindings HOLD. Evaluated terminal failures
remain failed observations (with explicit evaluator failure labels), rather
than being silently discarded; failures without a durable evaluator record or
their exact available artifact bindings HOLD.

Each profile exposes chart-ready `pass_at_1`, `pass_at_k`, and `pass_power_k`
series with numerator, denominator, exclusions, and source attempt IDs. Costs
are `reconciled` only when every included profile attempt binds a provider
usage reference and a price reference; otherwise cost is `unknown` and the
profile is excluded from Pareto/minimum-sufficient selection.

Main effects are paired risk differences or paired continuous differences with
seeded task-cluster bootstrap intervals. Every report labels those intervals
`marginal`; they are not multiplicity-adjusted intervals. Main-effect two-sided
raw p-values are derived only from the persisted paired cluster differences and
are Holm-corrected across the registered primary family in stable effect-ID
order. Secondary pairwise interactions are four-cell
difference-in-differences. Their two-sided raw p-values use the same
cluster-preserving sign-flip procedure—exact through sixteen task clusters and
deterministically sampled thereafter—and are Benjamini-Hochberg corrected in
stable interaction-ID order. Requests cannot supply p-values. An interaction
without its declared effective pair and cluster count is emitted as `HOLD`
without an estimate. The clean-versus-stressed ordinary-task tax is separately
reported as paired stress-minus-clean success difference.

Manipulation, trace completeness, evaluator independence, held-out coverage,
and preregistration gates contribute to adequacy. The retained
`comparison_invariants_pass` configuration boolean is a declaration, not a
derived persisted cross-arm evidence check. Because v1 does not yet have that
derived check, it cannot lift an analysis above `DESCRIPTIVE_ONLY`, including
when a caller sets it to `true`. Externally supplied mixed-effects results stay
descriptive and cannot bypass that HOLD. The engine never fits or invents a
mixed-effects result. Trace first divergence remains explicitly
diagnostic-only, never causal.
