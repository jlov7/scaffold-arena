# Statistical Audit v0.1

Date: 2026-05-23

This report audits deterministic fixture controls. It does not contain live provider benchmark results.

## Summary

- Run artifacts: 54
- Task families: extraction, privacy, research, risk, strategy, tool_use
- Bootstrap seed: 20260523
- Bootstrap samples per family: 2000
- Minimum required separation: 20 points
- All families pass: yes

## Fixture Separation

| Task family | Positive n | Negative n | Positive mean | Negative mean | Separation | Bootstrap 95% CI | Probability superiority | Pass |
| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | --- |
| extraction | 3 | 6 | 92.5 | 47.15 | 45.35 | 22.72 to 67.98 | 1.0 | yes |
| privacy | 3 | 6 | 100.0 | 55.6 | 44.4 | 44.4 to 44.4 | 1.0 | yes |
| research | 3 | 6 | 100.0 | 53.4 | 46.6 | 36.13 to 57.07 | 1.0 | yes |
| risk | 3 | 6 | 97.4 | 11.8 | 85.6 | 85.6 to 85.6 | 1.0 | yes |
| strategy | 3 | 6 | 100.0 | 50.25 | 49.75 | 45.85 to 53.65 | 1.0 | yes |
| tool_use | 3 | 6 | 100.0 | 53.9 | 46.1 | 39.43 to 52.77 | 1.0 | yes |

## Claim Boundary

A pass here means the scoring machinery separates seeded fixture controls. It does not prove that any scaffold beats another scaffold in live model use. The strict frontier rubric remains capped until live provider runs, live ablations, human calibration, and independent reproduction exist.
