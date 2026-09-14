# Scaffold Arena protocol-v1

`protocol.schema.json` is the stable JSON Schema entry point for protocol version `1.0`.
The per-contract `*.schema.json` files are generated directly from the strict
Pydantic models in the active `backend/*_v1` contract packages and are the complete schemas
for each protocol artifact. This includes static X-Ray request/report contracts and
persisted-event Observatory request/report contracts; those diagnostics are not execution
or runtime schemas. Study packs are declarative JSON only; loaders reject
symlinks and executable source files and never import pack content.

`fractional` is deliberately limited to a regular two-level half-fraction with
the defining relation `I=AB...`; for four binary factors this is the balanced
Resolution IV `I=ABCD` half-fraction. Categorical and ordinal fractional
matrices must be supplied as an explicit `custom` design. This is a design
description, not a general optimality claim.

Attempt budgets distinguish generated-token limits (`max_tokens`) from input
context consumption (`max_context_tokens`, measured in provider-reported
tokens). `AggregateBudgetSpec` separately caps execution-wide cost, tokens,
tool calls, wall time, and attempts; no cost limit is defaulted to zero.

## Executable frozen controls

`ExperimentSpec` remains the frozen research declaration. Before dispatch,
Arena compiles its sampling values, deterministic per-unit seed, harness timeout,
and attempt limits into the adapter SDK's strict `AttemptExecutionControls`
contract. The control set is carried in the existing immutable, reverse-DNS
scenario extension namespace `org.scaffold-arena.execution-controls`; therefore
protocol artifact schemas and protocol version `1.0` remain unchanged.

The runtime overlay is included in the canonical `AttemptInput` scenario and
binding digests. Changing temperature, top-p, maximum output, seed, timeout,
tool-call limit, context limit, or attempt limit changes the executable request
identity. Trusted StudyPack checks and state oracles remove only this named
runtime overlay before verifying the original frozen scenario digest; arbitrary
extensions remain part of the scenario identity.

Adapters distinguish requested controls from observed application. The local
OpenAI-compatible adapter applies temperature, top-p, maximum output tokens, and
seed to the provider request; lifecycle limits remain bound to the worker and
adapter boundary. It returns a content-addressed `AppliedControls` receipt as a
durable artifact. A receipt establishes what the adapter observed or enforced;
it does not establish provider truth, model determinism, research validity, or
outcome correctness.

Legacy `AttemptInput.bind(scenario, attempt)` calls remain valid and expose an
explicit `compatibility_default` control view derived from the immutable attempt
budget. New durable executions always use `frozen_experiment` controls. Missing
or unsupported provider controls must be reported explicitly by integrations;
they must never be silently represented as applied.

Protocol `1.0` does not coerce legacy `0.1` artifacts. The existing top-level
`specs/*.schema.json` files remain the separate legacy contract surface.
