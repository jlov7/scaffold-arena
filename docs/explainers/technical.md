# Technical explainer

Scaffold Arena is a causal-measurement workbench built around strict separation of the system under test from the system that evaluates it.

## Architecture

- **Protocol registry** validates versioned StudyPacks, scenarios, factors, graders, harnesses, and experiments.
- **Experiment controller** expands frozen designs into randomized episodes and replicated attempts.
- **Durable workers** lease attempts from SQLite or PostgreSQL, enforce budgets, invoke adapters, and append evidence-bound events.
- **Independent evaluator** applies deterministic graders, state oracles, calibrated qualitative measures, and human annotations without mutating harness state.
- **Analysis service** computes paired effects, uncertainty, consistency, interactions, severe-failure gates, and Pareto frontiers.
- **Evidence service** binds artifacts, code, environment, pricing, evaluators, and experiment hashes into verifiable receipts.

FastAPI exposes REST resources and GET-only SSE. The React/TypeScript workbench is a client of those durable resources; it does not own execution state.

## Execution boundary

An adapter receives an immutable `AttemptInput` containing the frozen scenario and attempt envelope. It declares capabilities before execution, streams ordered events, returns explicit usage authority, and supplies content-addressed artifacts. Capability mismatch stops during preflight.

Attempt jobs and evaluator jobs are separately leased. Reconnectable SSE tails persisted execution sequence numbers, so API restarts do not invent or lose logical events.

## Evaluation boundary

Deterministic graders contribute at least 70 percent of every task-family score. Severe permission, state, provenance, or contract failures are hard gates. Missing provider usage yields `UNKNOWN` cost. Agent-side verification is a treatment factor, not the independent evaluator.

Qualitative judge output remains excluded until calibrated against blind human annotations. Trace divergence is diagnostic unless the frozen design supports a causal counterfactual claim.

## Persistence and deployment

Personal mode uses SQLite WAL, a local artifact store, one worker, and loopback access. Team mode uses PostgreSQL leasing, S3-compatible artifacts, OIDC server sessions, project-scoped roles, and separate API and worker processes.

Large payloads live in the content-addressed artifact store; database rows retain metadata, bindings, and hashes. Receipts prove custody and integrity, not correctness or independence.

## Extension points

- Add tasks and factors through declarative StudyPacks.
- Add executable graders through explicitly installed trusted packages.
- Add harnesses through the adapter certification contract.
- Add domain ontologies through namespaced JSON extensions rather than Arena-core concepts.

## References

- [System architecture](../architecture.md)
- [Protocol-v1 boundary](../adr/003-protocol-v1-boundaries.md)
- [Durable API, worker, and events](../adr/004-durable-api-worker-and-event-architecture.md)
- [Adapter certification](../adapters/certification.md)
- [Durable evaluator](../evaluation/durable-evaluator.md)
- [Evidence status](../evidence-status.md)
