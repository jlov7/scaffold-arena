# Scaffold Arena documentation

Scaffold Arena is a 0.9.1 undeployed beta release candidate. Start with the path that matches your goal, then use the reference sections when you need detail. The repository validates an offline synthetic fixture, one bounded Ollama local-live custody probe, and one truthful LM Studio admission HOLD; it does not yet claim comparative model or harness performance, human calibration, independent reproduction, or deployment assurance.

## Choose a path

| If you want to… | Start here | Then continue with |
| --- | --- | --- |
| Run the product locally without a provider | [Getting started](getting-started.md) | [Provider-free examples](../examples/README.md) and [product tour](product-tour.md) |
| Understand how context, memory, loops, graphs, tools, assurance, economics, and evidence fit together | [The Harness Stack](concepts/harness-stack.md) | [Harness Genome v1](harness-genome-v1.md) and [Harness X-Ray and observatory](analysis/xray-observatory-v1.md) |
| Understand what the beta can support | [Evidence status](evidence-status.md) | [Product contract](concepts/product-contract.md) and [FAQ](faq.md) |
| Design a controlled scaffold comparison | [User guide](user-guide.md) | [Protocol-v1 schemas](../specs/v1/README.md) and [benchmark card](benchmarking/benchmark_card.md) |
| Make a bounded product decision in the Workbench | [Decision-first Workbench](guides/decision-first-workbench.md) | [Evidence status](evidence-status.md) and [trace diagnostics](analysis/trace-lab.md) |
| Author a StudyPack | [StudyPack authoring guide](guides/study-pack-authoring.md) | [Protocol-v1 schemas](../specs/v1/README.md) and [adapter certification](adapters/certification.md) |
| Integrate, deploy, or operate the system | [API reference](api-reference.md) | [Team deployment](ops/team-deployment.md), [deployment coherence](ops/deployment-coherence.md), and [release verification](ops/release-verification.md) |
| Audit the architecture or evidence boundary | [System architecture](architecture.md) | [Evidence and claim maturity](adr/005-evidence-and-claim-maturity.md) and [threat model](security/scaffold-arena-threat-model.md) |

## Product and orientation

- [Product overview](../README.md)
- [Product tour](product-tour.md)
- [The Harness Stack](concepts/harness-stack.md)
- [Product contract](concepts/product-contract.md)
- [Design system](design-system.md)
- [Getting started](getting-started.md)
- [User guide](user-guide.md)
- [Decision-first Workbench](guides/decision-first-workbench.md)
- [StudyPack authoring guide](guides/study-pack-authoring.md)
- [Glossary](glossary.md)
- [Harness Genome v1](harness-genome-v1.md)
- [Harness Mechanism Atlas v1](harness-mechanism-atlas-v1.md)
- [Harness X-Ray and observatory v1](analysis/xray-observatory-v1.md)
- [Arena Forge, planning, and process safety v1](arena-forge-planner-process-safety-v1.md)
- [Roadmap](roadmap.md)
- [FAQ](faq.md)

## Tutorials and runnable examples

The [provider-free examples index](../examples/README.md) is the authoritative
command map. It links the one-command run, expected result, focused test,
cleanup, screenshot status, and claim ceiling for every required example:

- [Compare two harnesses](../examples/compare-two-harnesses/)
- [Context compaction ablation](../examples/context-compaction-ablation/)
- [Memory policy study](../examples/memory-policy-study/)
- [Recovery fault injection](../examples/recovery-fault-injection/)
- [Permission boundary study](../examples/permission-boundary-study/)
- [Local model harness comparison](../examples/local-model-harness-comparison/)
- [Harness PR regression](../examples/harness-pr-regression/)
- [Counterfactual replay](../examples/counterfactual-replay/)

For matching fixture-backed product states, use the [product-tour evidence
map](product-tour.md). Those captures and all runnable examples remain bounded
by [evidence status](evidence-status.md); a deterministic fixture result is not
live-provider, human-calibrated, causal, security-assurance, or independently
reproduced evidence.

## Protocol and research

- [Local-runtime exploratory evidence v1](evidence/local-runtime-exploratory-v1.md)
- [Protocol-v1 schemas](../specs/v1/README.md)
- [Harness Mechanism Atlas v1](harness-mechanism-atlas-v1.md)
- [Protocol-v1 boundary](adr/003-protocol-v1-boundaries.md)
- [Legacy protocol v0.1](protocol/scaffold-arena-protocol.md)
- [Benchmark card](benchmarking/benchmark_card.md)
- [Legacy v0.1 fixture reproducibility](benchmarking/reproducibility.md)
- [Prior-art comparison](benchmarking/comparison_to_existing_tools.md)
- [Human annotation rubric](benchmarking/annotation_rubric.md)
- [Failure taxonomy](benchmarking/failure_taxonomy.md)

## Architecture

- [System architecture](architecture.md)
- [Explicit execution-kernel composition](architecture/explicit-execution-kernel.md)
- [Bounded invocation and reservation lifecycle model](architecture/invocation-reservation-lifecycle-model.md)
- [Durable API, worker, and events](adr/004-durable-api-worker-and-event-architecture.md)
- [Evidence and claim maturity](adr/005-evidence-and-claim-maturity.md)
- [Local and team deployment boundary](adr/006-local-and-team-deployment-boundary.md)
- [Workbench frontend boundaries](adr/007-workbench-v1-frontend-boundaries.md)
- [Frontend module boundaries](architecture/frontend-module-boundaries.md)

## Build, verify, and operate

- [API reference](api-reference.md)
- [Adapter certification](adapters/certification.md)
- [Durable evaluator](evaluation/durable-evaluator.md)
- [Durable blind review](evaluation/durable-review.md)
- [Analysis engine and exports](analysis/analysis-v1-engine.md)
- [Frozen prospective analysis plan](analysis/frozen-analysis-plan.md)
- [Trace Lab semantic alignment](analysis/trace-lab.md)
- [Harness X-Ray and observatory v1](analysis/xray-observatory-v1.md)
- [Arena Forge, planning, and process safety v1](arena-forge-planner-process-safety-v1.md)
- [Evidence API](evidence/api-v1.md)
- [Team deployment](ops/team-deployment.md)
- [Deployment coherence](ops/deployment-coherence.md)
- [Production integration verification](ops/production-integration-verification.md)
- [Release and supply-chain verification](ops/release-verification.md)
- [Artifact storage](ops/artifact-storage.md)
- [Retention and archival](ops/retention-archival.md)
- [Scale validation](ops/scale-validation.md)
- [Troubleshooting](ops/troubleshooting-decision-tree.md)

## Security and accessibility

- [Threat model](security/scaffold-arena-threat-model.md)
- [Team authentication](security/team-auth.md)
- [Security policy](../SECURITY.md)
- [Accessibility audit](reviews/accessibility-audit-v1.md)
- [Assistive-technology smoke protocol](reviews/assistive-technology-smoke-protocol.md)
- [UX visual audit](reviews/ux-visual-audit-v1.md)
- [M5 decision and lifecycle review](reviews/m5-decision-formal-integration-review.md)

## Media

- [Current product screenshots](assets/README.md)

Generated fixture reports and legacy migration references remain explicitly labelled as such. No documentation artifact should be interpreted above the authority described in [evidence status](evidence-status.md).
