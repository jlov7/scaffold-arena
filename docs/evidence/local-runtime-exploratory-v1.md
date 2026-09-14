# Local-runtime exploratory evidence v1

Two synthetic-only local-runtime probes were executed on exact hardened code revision `a7c32c2de4e1dd06de4db7bfeae1761f495790d5`. Both used native loopback adapters and exact allowlisted output. Ollama completed the private durable Protocol-v1 attempt, separate deterministic evaluation, analysis, derived receipt creation, and fresh receipt verification. LM Studio executed the attempt but stopped before evidence admission because its native API did not supply an independently verifiable runtime version.

| Runtime | Bound model identity | Outcome | Receipt / analysis |
| --- | --- | --- | --- |
| Ollama `0.32.15` | `qwen3.5:4b`, digest `2a654d98e6fba55d452b7043684e9b57a947e393bbffa62485a7aac05ee4eefd` | Completed: 32 input, 6 output, 38 total, 0 tools, `$0.00`, energy unknown | Receipt `01877e52573129c91dd37c2178e2a2718475e25693932a186ecc499eaecb881b`; `HOLD / DESCRIPTIVE_ONLY` |
| LM Studio CLI revision `71bd99c` | `qwen3.8-27b`, operator-attested model-file SHA-256 `701d8fa9ed214ab21bfc130cd2a7df19ca89bbef7713e2dfb19f3c63696aa917` | `attempt_terminal_hold`; sanitized output was not published | No derived receipt: native v1 exposes no verifiable provider runtime version |

The admitted Ollama run recorded paid cost as `$0.00`; energy remains `unknown`, not zero. LM Studio's CLI revision and model-file digest are operator attestations and are never represented as provider observations. Its typed HOLD is the intended fail-closed result, not a failed scientific result.

Bundle:

- [`outputs/local_runtime_evidence/ollama-qwen35-4b-a7c32c2`](../../outputs/local_runtime_evidence/ollama-qwen35-4b-a7c32c2/summary.json)

These observations establish one bounded Ollama transport-to-receipt path and one bounded LM Studio fail-closed admission path. They do not estimate model quality, compare harnesses, validate transfer, establish causality, satisfy the unpublished flagship/transfer preregistrations, substitute for human calibration, or constitute independent reproduction.
