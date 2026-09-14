# Benchmark Results v0.1

This report is generated from deterministic fixture controls. It validates the benchmark runner, artifact format, repeated-trial aggregation, confidence-interval plumbing, and baseline separation mechanics. It is not a live provider benchmark.

Fixture identity `fixture-no-provider-deterministic-v1` means no provider was invoked. Provider input tokens, output tokens, cost, and API calls are therefore known to be none and recorded as zero. `wall_time_ms` is `null` because fixture latency was not measured. Scores are deterministic control outcomes, not model-performance evidence.

Timestamps are fixed fixture values for reproducibility, not observed execution times.

## Summary

- Mode: `fixture`
- Model id: `fixture-no-provider-deterministic-v1`
- Runs: 54
- Repeats per control: 3
- Score mean: 63.01
- Score stdev: 31.14
- 95% CI: 54.7 to 71.31

## Baseline Separation

| Task family | Positive mean | Negative mean | Separation | Pass |
| --- | ---: | ---: | ---: | --- |
| extraction | 92.5 | 47.15 | 45.35 | yes |
| privacy | 100.0 | 55.6 | 44.4 | yes |
| research | 100.0 | 53.4 | 46.6 | yes |
| risk | 97.4 | 11.8 | 85.6 | yes |
| strategy | 100.0 | 50.25 | 49.75 | yes |
| tool_use | 100.0 | 53.9 | 46.1 | yes |

## Claim Boundary

- These are fixture controls, not live provider/model results.
- The strict frontier rubric remains capped until live provider runs, scaffold ablations, human calibration, and independent reproduction exist.
- A fixture separation pass means the scoring machinery can distinguish known-good and known-bad artifacts for these controls.
