# Factorized P/V/R/M runtime bridge

`factors_v1.compile_recipe()` only creates a declarative arm. To execute an
arm, wrap an already trusted `HarnessAdapter` with
`factors_v1.FactorizedHarnessAdapter` and supply a harness-owned
`FactorRuntime` implementation.

```python
recipe = compile_recipe({"planning": True, "verification": True, "recovery": False, "memory": True})
adapter = FactorizedHarnessAdapter(adapter=trusted_adapter, recipe=recipe, runtime=trusted_factor_runtime)
prepared = await adapter.prepare_attempt(harness, attempt_input)
result = await adapter.execute_attempt(prepared)
```

The original trusted adapter identity remains authoritative: the decorator
does not invent a new adapter identity, provider, model, sampling setup, task,
Arena evaluator, or budget. `AttemptInput` is canonicalized at the bridge and
checked unchanged after every runtime/adapter boundary. Its factor assignment
must exactly match the immutable compiled recipe.

The integrating runtime must provide observed assignment, compute/context
budgets, and source-hash evidence for all four mechanisms, including shams.
Off levels are compute/context-matched shams, never skipped work. The bridge
emits one explicit pass/fail manipulation-fidelity trace event per mechanism;
this is `treatment_delivery_only` evidence, not a treatment-effect or causal
claim.

For active mechanisms, the bridge validates:

- Planning: a single episode-bound plan history with legal, evidenced state
  transitions and terminal steps.
- Verification: agent-side pre-finalization evidence only, at most one repair,
  and no substitution for the Arena evaluator.
- Recovery: every reported retry is re-authorized from its declared transient
  failure, checkpoint provenance, sequence ledger, and idempotency key.
- Memory: a sourced, bounded `EpisodeMemory` confined to the current episode;
  its existing deterministic compaction path is retained.

Capability checks occur before `prepare_attempt` reaches the wrapped adapter.
Missing capabilities, changed canonical input, unmatched sham budget, or
missing/invalid semantic evidence fail closed. Finalization failures return an
`incomplete` result with a `HOLD` detail; callers must not report treatment
delivery or causal outcomes without the observed fidelity artifacts.

`stream_events()` is safe for the normal worker order where trace draining
starts before execution: it emits the recipe binding, preserves wrapped events,
then waits for the adapter's terminal result before emitting finalized
per-factor fidelity and exactly one factor-terminal event.

## Integration boundary

Generic recorded, HTTP, CLI, and native adapters do not themselves furnish
plan-state, pre-finalization, checkpoint, or memory semantics. They therefore
remain **HOLD** for a factorized treatment until their owning harness supplies
and tests a trusted `FactorRuntime`. This bridge intentionally does not
attempt to infer those semantics from provider output or from successful recipe
compilation.
