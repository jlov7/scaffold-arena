# Bounded invocation and reservation lifecycle model

The executable model in [`backend/execution_v1/formal_model.py`](../../backend/execution_v1/formal_model.py) is a small, deterministic safety specification for the durable provider-invocation boundary. It is deliberately independent of SQLAlchemy, adapter implementations, clocks, and external providers, so a counterexample is attributable to the lifecycle rules rather than a fixture or transport.

Run it with:

```bash
uv run --project backend python scripts/check-lifecycle-model.py
```

`./scripts/verify-all.sh` runs the same checker for every release candidate.

## Model boundary

The bounded search explores two invocation generations, two distinct external-result digests, and every permitted transition through depth eight. Its state consists of:

- generation admission (`current`, `stale`, or duplicate request identity);
- dispatch observation and cancellation progression;
- reservation state (`reserved`, `committed`, `released`, `expired`, `unknown_usage`, or `disputed`);
- one external result owner; and
- one provider request-identity owner.

It explores begin, lease expiry, reserve, dispatch, request-identity observation, result admission, budget commit, unknown/disputed settlement, and cancellation transitions. The checker reports the explored state and transition count so the finite bound is inspectable rather than implied.

## Checked safety invariants

The model and focused implementation tests check that:

1. a stale generation cannot finalize current truth;
2. post-dispatch unknown usage is never released as zero;
3. settled reservations never regress;
4. terminal cancellation states never regress;
5. a duplicate provider request identity cannot become an independent execution;
6. one external result is admitted at most once; and
7. a budget is not committed twice.

The runtime correspondence is intentionally narrow and inspectable:

- dispatch, release, expiry, and stranded settlement take the bound invocation lock first, so PostgreSQL cannot interleave a zero-cost settlement with dispatch;
- `InvocationRepository.mark_dispatch_started` refuses any already-settled bound reservation;
- expiry after possible dispatch records `unknown_usage`, never an expired zero-cost outcome;
- `InvocationRepository.observe_provider_request` rejects post-terminal identity mutation and, on PostgreSQL, takes a transaction advisory lock derived from the non-secret provider/request identity before its compatibility lookup;
- the request lock may conservatively serialize equal provider/request IDs across pinned endpoints, but the existing namespace query still decides whether they conflict, so endpoint semantics do not change;
- `InvocationRepository.admit_terminal` takes an analogous digest-derived advisory lock before checking every other invocation; only the first durable owner stores the result digest and terminal outcome, while a later callback becomes ambiguous/duplicate with reconciled usage downgraded to `unknown`;
- SQLite uses its existing immediate write transaction for the same cross-row serialization; and
- `BudgetReservationService._transition_in_connection` detects a superseded optimistic transition.

No migration accompanies this change because it adds transition guards and lock ordering over the existing invocation and reservation schema; it does not alter persisted shapes.

## Deterministic adversarial coverage

The model is paired with concrete, deterministic test lanes rather than a random or long-running chaos environment.

| Fault or property | Reproducible coverage |
| --- | --- |
| Generation takeover, lease expiry, delayed/stale response, duplicate provider identity, terminal result, reservation, and cancellation monotonicity | `backend/tests/execution_v1/test_lifecycle_formal_model.py`, `test_invocation_fencing.py`, `test_provider_request_namespace.py`, `test_reservation_lifecycle.py` |
| PostgreSQL cross-invocation request identity and result-digest races | `backend/tests/persistence_v1/test_postgres_parity.py::test_postgres_cross_invocation_identity_admission_is_serialized` via `./scripts/test-postgres-v1.sh` |
| Killed/expired worker lease and partial cancellation recovery | `backend/tests/execution_v1/test_execution_v1.py` and `test_invocation_fencing.py` |
| Event backpressure, consumer closure, and retained-event recovery after a partition-like close | `backend/tests/adapters_v1/test_event_channel_backpressure.py` |
| Malformed/corrupt event records and bounded transport failures | `backend/tests/adapters_v1/test_bounded_transports.py` |
| Object-store inconsistency and corrupt/missing receipt handling | `backend/tests/artifacts_v1/test_s3_compatible_store.py` and `backend/tests/services_v1/test_forge_planner_process_safety.py` |
| Clock skew, reordered events, and explicit diagnostic partial traces | `backend/tests/analysis_v1/test_adequacy_trace.py` and `backend/tests/services_v1/test_trace_lab_service.py` |
| Forge cohort separation, replay locality, and idempotent replay | `backend/tests/services_v1/test_forge_planner_process_safety.py` and `backend/tests/services_v1/test_counterfactual_replay_harness_ci.py` |
| Interrupted migration resume and schema parity | `backend/tests/persistence_v1/test_legacy_and_migrations.py` |

These are bounded engineering checks. They are not a proof over unbounded schedules, a production incident simulation, a security assessment, causal evidence, or independent assurance.
