# Glossary

This glossary describes the repository's terms, not a general taxonomy for all agent systems.

| Term | Meaning in Scaffold Arena |
| --- | --- |
| **Harness** | The executable system around a model: orchestration, tools, state, budgets, recovery, and lifecycle controls. |
| **Scaffold** | A named mechanism or configuration varied inside a harness comparison, such as planning, verification, memory, or recovery. |
| **StudyPack** | A declarative, versioned study definition containing scenarios, harness references, experiments, and declared evidence limits. It cannot execute uploaded code. |
| **Frozen experiment** | An immutable experiment specification whose identity binds its study, factors, controls, budgets, and sampling settings before execution. |
| **Treatment arm** | One concrete factor assignment produced by the experimental design. |
| **Preflight** | The admission check that verifies declared capabilities, controls, budgets, and evidence eligibility before work is dispatched. |
| **HOLD** | A typed non-admission result. It means a required condition is absent or unsupported; it is not a degraded PASS. |
| **Attempt** | One durable unit of work under a frozen execution plan. Attempts can be leased, retried, cancelled, and evaluated independently. |
| **Deterministic-first evaluation** | A task-family score in which deterministic checks contribute at least 70%. Narration does not overrule a state oracle. |
| **Trace divergence** | The first meaningful difference between aligned execution traces. It is diagnostic until an intervention and replicated counterfactual support a causal claim. |
| **Receipt** | Content-addressed custody metadata for bytes, bindings, or observed controls. A receipt establishes integrity, not outcome truth or independent validation. |
| **Claim ceiling** | The strongest statement an artifact may support, given its provenance and validation state. Fixture, live, human-calibrated, and independently reproduced evidence have different ceilings. |

For the full contract, read the [protocol schemas](../specs/v1/README.md) and [evidence status](evidence-status.md).
