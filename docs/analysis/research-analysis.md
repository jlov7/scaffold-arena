# Optional research analysis

Install `uv sync --extra research` to enable the preregistered binary
hierarchical estimator and Parquet export. The estimator is explicitly
`BinomialBayesMixedGLM.fit_vb`: it uses a task-cluster random intercept, fixed
registered factors and stressor, and only preregistered interactions. Its
intervals are variational-Bayes posterior credible intervals, not frequentist
confidence intervals.

The fit never consumes caller-supplied coefficients, p-values, or fitter
receipts. It runs only when every adequacy, manipulation, trace,
evaluator-independence, held-out, and effective-sample gate passes. v1 has no
derived persisted cross-arm comparison-invariant check, so ordinary engine
reports remain `HOLD_ADEQUACY` even when callers assert the legacy boolean.
Missing dependencies, separation, singularity, and nonconvergence also produce
typed HOLD statuses. The core report and deterministic CSV export remain available without
the extra; Parquet returns `research_extra_unavailable`.

Regenerate a report-bound export without changing evidence:

```bash
arena results export <report-digest> --format csv --output analysis.csv \
  --database arena.db --artifacts artifacts --project personal
```

`POST /api/v1/exports` accepts exactly
`{"kind":"analysis","report_digest":"...","format":"csv"}` or
the same object with `"format":"parquet"`. Response headers carry the immutable report digest,
manifest hash, and export digest.
