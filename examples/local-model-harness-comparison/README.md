# Local model harness comparison — protocol-only certification

This example runs the focused OpenAI-compatible adapter and certification kit
tests with mocked transports. It verifies endpoint pinning, cancellation,
secret-safe traces, complete-versus-missing usage, and certification boundary
cases without starting Ollama, LM Studio, or any other local model. No model
output, harness comparison, cost, latency, sandbox, or availability result is
produced. Because no provider is invoked, this example records no provider
usage, cost, API calls, or latency; it cannot substitute synthetic accounting
for provider-observed evidence.

## Run

From the repository root:

```bash
uv run --project backend pytest backend/tests/adapters_v1/openai_compatible/test_adapter.py backend/tests/adapters_v1/certification/test_kit.py -q
```

Expected result: the focused protocol/certification tests pass using mocked
transports. This example contains no authorized Ollama or LM Studio execution
and produces no model output, so any comparison from this example is `HOLD`.
Separate bounded local-runtime evidence is described in the
[local-runtime exploratory record](../../docs/evidence/local-runtime-exploratory-v1.md);
it does not turn this mocked example into a comparison. A future live command
would need explicit loopback authorization, a pinned model/runtime identity,
and fresh receipts; it is intentionally not part of this example.

If that retained historical record is included in a future clean-history public
snapshot, it may be checked through the publication-binding path described in
[evidence status](../../docs/evidence-status.md). That preserves historical
bundle integrity only; it does not make the old source revision reproducible
from the snapshot or turn this example into live evidence.

Inputs and the exact test boundary are pinned in the [example manifest](manifest.json).
The focused tests include missing-usage-is-incomplete, endpoint pinning,
cancellation/no-call, secret-safe diagnostics, and certification cases. No
cleanup is required because the tests use mocked transports and must not alter
global credentials or launch a process.

There is no dedicated local-runtime screenshot. The [product-tour evidence
map](../../docs/product-tour.md) may link a blocked readiness state, but no
model score or local-provider result should appear in an image.
