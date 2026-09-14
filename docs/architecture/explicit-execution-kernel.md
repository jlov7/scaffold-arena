# Explicit execution-kernel composition

Scaffold Arena's protocol-v1 execution stack has three public composition boundaries:

- `execution_v1.controller.ExperimentController` — the control-complete execution graph builder;
- `execution_v1.worker.DurableWorker` — the validation, invocation-fencing, adapter and evidence worker;
- `execution_v1.budget.BudgetReservationService` — lifecycle-aware conservative reservation accounting.

Package-level imports expose the same exact classes:

```python
from execution_v1 import ExperimentController, DurableWorker, BudgetReservationService
```

These identities are stable regardless of whether a consumer imports the package, a canonical submodule, or an implementation layer first.

## Internal kernels

The original, independently tested implementations are retained byte-for-byte as internal kernels:

```text
_controller_kernel.py
_worker_kernel.py
_budget_kernel.py
```

They provide the smallest proven mechanisms:

- deterministic frozen-experiment expansion and durable dispatch;
- lease-supervised adapter execution and evidence persistence;
- conservative usage-ledger reservation and reconciliation.

They are implementation bases, not public extension points. Applications and integrations should import the canonical modules or package exports.

## Explicit composition layers

The additive behavior introduced by the frontier runtime stack remains separated by responsibility:

```text
_controller_kernel.ExperimentController
  → controlled_controller.ExperimentController

_worker_kernel.DurableWorker
  → fenced_worker.DurableWorker
  → validated_worker.DurableWorker

_budget_kernel.BudgetReservationService
  → reservations.BudgetReservationService
  → reservation_policy.BudgetReservationService
```

Canonical `controller.py`, `worker.py`, and `budget.py` are thin composition modules. During their own initialization they expose the internal kernel to the explicit subclass module that consumes it, then bind their public name to the final implementation. They do not assign into another module or depend on package-level import side effects.

## Reservation policy

Reservation accounting distinguishes settled and unresolved states.

Settled and immutable:

```text
committed
released
expired
```

Unresolved and eligible for later evidence reconciliation:

```text
reserved
unknown_usage
disputed
```

`unknown_usage` and `disputed` cannot be released or expired as though external cost were zero. Late provider evidence may reconcile them. This policy is implemented by explicit subclass methods in `reservation_policy.py`; no imported module constants are rewritten at runtime.

## Compatibility guarantees

The refactor preserves:

- protocol version `1.0`;
- public package and canonical-module imports;
- frozen experiment, invocation, reservation and worker evidence shapes;
- migrations and persistence schemas;
- malformed-job fallback to the original worker kernel;
- generation fencing and stale-result admission rules;
- conservative unknown and disputed usage semantics;
- bounded command and HTTP transport behavior.

Subprocess regression tests exercise package-first, controller-first, worker-first, budget-first, fenced-worker-first and reservation-policy-first import orders. Each order must resolve the same public class identities and explicit method-resolution chain.

## Why this boundary matters

Import-time monkey-patching makes correctness depend on invisible initialization order. It complicates static analysis, type checking, security review, plugin integration, debugging and long-lived interpreter behavior. Explicit composition makes the authoritative implementation inspectable and gives future execution layers a stable base without weakening the evidence boundary.
