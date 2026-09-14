# User guide

Scaffold Arena separates experimental design, execution, evaluation, analysis, and evidence so that changing an agent harness does not also change the measuring instrument.

## Choose a presentation

- **Guided** explains decisions in plain language and recommends safe defaults.
- **Lab** exposes manifests, factor matrices, budgets, graders, traces, and export controls.

Both presentations operate on the same durable protocol objects.

## Run the offline demonstration

1. Open **Compare**, then choose the bundled synthetic offline StudyPack in **Study Canvas**.
2. Open **Design** to inspect its matched scenarios, P/V/R/M factors, sixteen treatment arms, deterministic graders, and claim boundaries.
3. Freeze the experiment. A frozen specification is immutable; any change creates a successor.
4. Run **Preflight**. Execution remains blocked unless capability, manipulation, budget, isolation, and evidence checks pass.
5. Open **Execute** to create or recover an execution and follow persisted events.
6. Use **Analyze** and **Trace Lab** to inspect effects, exclusions, severe failures, aligned traces, and state changes.
7. Use **Evidence** to derive and verify a custody receipt or export the StudyPack.

The bundled results are labelled fixtures. They validate the workflow, not model or harness performance.

## Import a StudyPack

StudyPacks are declarative ZIP archives with a content manifest. Import rejects traversal paths, undeclared content, invalid schemas, and executable code. Executable adapters or graders must be installed separately as trusted Python packages.

After import, inspect:

- scenario data classification and solvability evidence;
- factor mutations, shams, and capability requirements;
- deterministic grader weight and severe-failure rules;
- hypotheses, primary outcomes, interactions, and adequacy gates;
- provider, runtime, budget, and claim-ceiling settings.

## Register a harness

Harnesses connect through certified adapters. The adapter declares its capabilities; unsupported requirements stop at preflight rather than being approximated. Local command, HTTP/RPC, OpenAI-compatible, native, Pi, Prime Agent, and DeepSeek adapter boundaries are documented in [adapter certification](adapters/certification.md).

Unsandboxed or protocol-only adapters may be useful for local exploration but cannot silently become claim-bearing evidence.

## Interpret results

Start with hard gates and denominators:

1. severe failures and exclusions;
2. mission success and consistency;
3. paired effects and uncertainty;
4. cost, latency, and tool use;
5. Pareto-optimal configurations;
6. the claim ledger and unresolved limitations.

Missing usage is `UNKNOWN`, never zero. An agent's statement that an action succeeded does not override the state oracle. A first trace divergence is diagnostic. Even a preregistered intervention and replicated counterfactual do not lift current v1 analysis beyond descriptive or diagnostic reporting until the derived cross-arm comparison-invariant gate is satisfied.

## Human review

Qualitative measures remain excluded from claims until they are calibrated against blind human annotations. Review payloads conceal treatment identity, model identity, and other prohibited fields. Disagreement is preserved and adjudicated rather than averaged away.

## Team deployment

Team mode requires PostgreSQL, S3-compatible artifact storage, OIDC, secure server sessions, and project roles. It fails closed when configuration or storage readiness is incomplete. Follow the [team deployment runbook](ops/team-deployment.md).

## Evidence boundary

The current public repository contains synthetic fixture evidence only. It contains no live-provider comparative study, completed human calibration, or independent reproduction. See [evidence status](evidence-status.md) before making any claim.
