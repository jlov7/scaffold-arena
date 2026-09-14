# Adapter certification

Adapter certification is a fixture-only conformance exercise. It verifies an adapter
implementation against one exact `HarnessSpec` and `AttemptInput`; it is not
evidence that a provider, model, sandbox, or benchmark outcome is valid.

The kit checks capability mismatch rejection, canonical input and prepared-hash
binding, one stable terminal result, ordered attempt-bound trace events, usage
unknowns, artifact hashes, cancellation/event draining, and idempotent cleanup.
It does not make an oracle, a price, a sandbox, or an external-validation claim
from fixture evidence.

`NativeScaffoldAdapter` only runs an explicitly injected current Scaffold Arena
scaffold/runtime. It neither resolves nor starts a task, provider, credential,
or process. A completed native result requires provider version, matching pinned
endpoint digest, input/output/total tokens, context tokens, tool-call evidence,
and a provider-usage digest. Otherwise it returns `incomplete` with a HOLD.

`OpenAICompatibleAdapter` accepts only a constructor-installed literal loopback
`/v1/chat/completions` endpoint. Its endpoint digest is derived from that
normalized URL and must equal `AttemptEnvelope.pinned_endpoint_digest`; a harness
cannot supply an endpoint, request profile, or credentials. It never launches
Ollama or another provider. Missing usage/context/tool or provider/endpoint
observation stays `UNKNOWN` (`None`) and prevents a completed result.

By default the local adapter is `protocol_only` and supports only `none`
isolation. A digest-shaped endpoint field, loopback URL, or green certification
fixture is not OCI/container/remote-sandbox evidence and cannot raise that
claim. An independently verified isolation probe must be explicitly introduced
and revalidated before a separate adapter profile can make such a declaration.

The adapter records request/response trace receipts only after execution settles.
Diagnostics omit credential values; response and usage artifacts are hash-bound.
Cost is not fabricated by an adapter: absent provider cost remains unknown and
central reconciliation remains responsible for configured model pricing.

## Terminal failure classification

Every `failed`, `timed_out`, or `incomplete` `ResultBundle` must declare one
of `transient_adapter`, `transient_provider`, `permanent_adapter`,
`permanent_provider`, or `permanent_protocol`. `completed` and `cancelled`
results must not declare a failure classification. The adapter declares this
from its explicit terminal condition; worker exception text is never used to
infer it.

Use the focused checks only:

```bash
cd backend
uv run ruff check adapters_v1/native adapters_v1/openai_compatible adapters_v1/certification tests/adapters_v1/native tests/adapters_v1/openai_compatible tests/adapters_v1/certification
uv run pytest tests/adapters_v1/test_adapters_v1.py tests/adapters_v1/native tests/adapters_v1/openai_compatible tests/adapters_v1/certification
```

## HOLD boundaries

- Fixture certification does not raise `fixture_only` or `protocol_only` into
  `live_provider` or `externally_validated` eligibility.
- A local endpoint is not an OCI/container/remote sandbox. An unsandboxed,
  state-changing harness must remain claim-ineligible through preflight.
- `arena worker` is the only CLI process that invokes adapters. It requires an
  explicit `scaffold-arena-adapter-runtime-v1` JSON configuration plus durable
  database/artifact/project/owner arguments. The API process only records,
  preflights, and streams durable state; it does not start a worker, provider,
  Ollama, or native scaffold runtime.
- The same command also leases durable evaluation work after its bounded attempt
  pass. Evaluation jobs never invoke adapters; an evaluation-only queue does
  not start a provider.
- The runtime configuration has a closed allowlist: `openai_compatible_local`,
  `ollama_local`, `native_current_scaffold`, `factorized_pvrm`, and
  `bundled_offline_demo_fixture`. It cannot import plugins,
  upload code, launch a process, or carry a request profile. `ollama_local`
  alone reads the fixed local model inventory as an identity attestation; it
  cannot select or download a model.
  Native and factor runtime references are resolved only from objects injected
  by the process owner; absent injection is a HOLD. The local OpenAI-compatible
  entry accepts only a literal loopback `/v1/chat/completions` endpoint and
  remains unsandboxed and protocol-only.
- Adapter lookup in registry preflight, certification, and durable execution is
  by the same installed `(adapter_id, adapter_digest)` instance. A configured
  P/V/R/M router selects only one of the sixteen compiled assignments already
  bound in `AttemptInput`; it does not dynamically select a plugin or alter the
  harness identity.
- `bundled_offline_demo_fixture` accepts no configuration fields. It replays only
  the hash-checked repository `study_packs/offline-demo-v1` JSON fixtures after
  validating the exact harness, scenario, budget, and P/V/R/M assignment binding.
  It neither runs archive code nor trusts an uploaded fixture-result map, and its
  eligibility remains `fixture_only`.

## Native local Ollama admission

`ollama_local` is a narrow alternative to `openai_compatible_local` for an
already-running Ollama API. It accepts only a credential-free literal-loopback
`/api` base URL, for example `http://127.0.0.1:11434/api`; it never launches,
downloads, or discovers a provider process. Before and after every attempt it
reads Ollama's `/api/version` and `/api/tags` responses. The attempt is held
unless both snapshots agree on the endpoint digest, Ollama version, exact model
name, exact model digest, and a model-attested context window at least as large
as the frozen request limit.

The adapter submits one non-streaming `/api/chat` request with `think: false`
and frozen `temperature`, `top_p`, `num_predict`, `seed`, and `num_ctx` options.
It admits only zero-tool attempts. The response must be complete, must name the bound
model, and must provide `prompt_eval_count` and `eval_count`; total token usage
is their deterministic sum, while context consumption is the provider-reported
prompt count. Response bodies are bounded before JSON parsing. The adapter
never retains provider-defined fields outside a strict allowlist of model,
completion, timing, usage, and assistant role/content fields: it stores that
sanitized response summary and the SHA-256 digest of the raw response, plus pre/post runtime
identity, provider usage, and an applied-controls receipt. A missing field,
redirect, model drift, runtime-version drift, identity mismatch, or tool call is
a typed HOLD, never an inferred zero or a permissive fallback.

This is local-runtime evidence only. Ollama's documented local API exposes
model digests, version, and usage counters; it does not provide a cryptographic
attestation of the serving binary or model execution. It therefore cannot prove
quality, causality, transfer, human calibration, external validation, or an M6
confirmatory result. The implementation follows the official [chat API](https://docs.ollama.com/api/chat),
[model inventory API](https://docs.ollama.com/api/tags), [version API](https://docs.ollama.com/api-reference/get-version),
and [usage documentation](https://docs.ollama.com/api/usage).

Minimal local-only worker configuration (the endpoint is a pin, not a provider
startup instruction):

```json
{
  "format": "scaffold-arena-adapter-runtime-v1",
  "adapters": [{
    "kind": "openai_compatible_local",
    "adapter_id": "local-one",
    "adapter_digest": "<sha256>",
    "endpoint": "http://127.0.0.1:11434/v1/chat/completions"
  }]
}
```

`native_current_scaffold` may name one shipped `scaffold_id` (`bare`,
`plan_execute_verify`, `tool_error_recovery`, or `memory_critique`). The
adapter resolves that ID from the current in-process registry only after a
worker has leased an attempt, converts the frozen `ScenarioSpec` into the
legacy task view, and then constructs the provider. A custom native runtime
still requires an injected `runtime_ref`. `factorized_pvrm` requires an
injected `FactorRuntime` plus an inline allowlisted base adapter: this release
does not claim that the legacy scaffolds furnish the semantic P/V/R/M evidence
needed to create one automatically.

The worker injects `CentralPriceResolver`, which reads the versioned
`config.models` catalogue. A provider usage record without a complete standard
catalogue match remains `UNKNOWN`; worker configuration never carries model
prices or supplies a fallback price.
