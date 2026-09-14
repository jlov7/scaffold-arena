# The Harness Stack

A production AI harness is not one prompt or one graph. It is the complete system that decides what a model can see, remember, call, repeat, delegate, verify, spend, and ultimately claim.

Scaffold Arena uses nine planes to make that system inspectable without collapsing distinct engineering concerns into one buzzword.

| Plane | Governing question | Typical mechanisms |
| --- | --- | --- |
| **Model** | What base capability and sampling behavior are available? | model and endpoint identity, tokenizer, context limit, temperature, top-p, seed, quantization |
| **Context** | What information reaches the model for this decision? | retrieval, ordering, filtering, prompt assembly, compression, truncation, source attribution |
| **Memory** | What state persists and may influence later decisions? | episodic, semantic, and procedural memory; write, update, conflict, decay, retrieval, and forgetting policies |
| **Control / loop** | How does work progress, recover, and stop? | planning, verification, retries, reflection, recovery, progress checks, escalation, termination |
| **Topology / graph** | How are components, agents, state, and authority connected? | routing, delegation, handoffs, checkpoints, branches, fan-out, fan-in, shared state |
| **Tool and environment** | What can the system observe or change? | tool schemas, filesystem and browser access, sandboxes, permissions, network policy, external side effects |
| **Assurance** | How is behavior checked and constrained? | deterministic validators, state oracles, independent evaluators, policy gates, severe-failure rules |
| **Economics** | What resources does the system consume? | tokens, provider cost, latency, tool calls, retries, storage, human review, operational budgets |
| **Evidence** | What conclusions are justified? | provenance, traces, artifacts, receipts, uncertainty, calibration, reproduction, claim ceilings |

## How the current engineering terms fit together

**Context engineering** governs the transient working set delivered to the model. It includes retrieval and prompt assembly, but also ordering, compression, provenance, sensitivity, and the loss introduced by truncation.

**Memory engineering** governs persistent state. A memory feature is not established merely because a store exists: its write policy, update semantics, conflict handling, retrieval, decay, forgetting, privacy boundary, and downstream use all matter.

**Loop engineering** governs repeated control. It determines when a system plans, acts, verifies, retries, changes strategy, escalates, or stops. Useful loop analysis therefore distinguishes productive recovery from oscillation, repeated-state work, verification without correction, and unbounded retries.

**Graph engineering** governs topology. It describes which components exist, how control and data move between them, where state is held, and how authority or failure propagates. A graph runtime is one implementation; the engineering problem is the topology and its observed behavior.

**Harness engineering** composes all nine planes into an operational system.

**Evaluation engineering** determines whether a named mechanism changed outcomes under a controlled design and what the evidence can support.

## Three linked views

Harness Genome projects one content-addressed description into three deliberately different graphs:

1. **Mechanism graph — what was built or declared.** Components, relations, protocols, intervention surfaces, configuration identities, and known unknowns.
2. **Execution graph — what was observed.** Model calls, tool calls, context transformations, memory activity, checkpoints, transitions, verification, retries, and outcomes that are explicitly bound by runtime evidence.
3. **Evidence graph — what may be concluded.** Source custody, artifacts, grader outputs, statistical estimates, review records, reproductions, claims, exclusions, and authority ceilings.

The graphs must not be joined by inference alone. A declared memory component does not prove a memory write occurred; an observed tool call does not prove it was necessary; a trace divergence does not establish causality; and a receipt establishes integrity only within its stated boundary.

## Intervention fidelity

A mechanism can fail to affect a run at several distinct stages:

```text
declared
→ assigned
→ available
→ triggered
→ applied
→ activated
→ observed
→ downstream pathway detected
```

Scaffold Arena preserves those distinctions so a study does not report “memory helped” when memory was merely configured, or “verification failed” when the verifier was never given an opportunity to run.

## Using the stack in Scaffold Arena

- **Harness X-Ray** proposes a candidate mechanism inventory from a bounded captured source. Declared, observed, inferred, verified, unsupported, and unknown remain separate.
- **Harness Genome** provides the strict, content-addressed descriptor and semantic-diff boundary.
- **Observatory** reports bounded context, memory, loop, graph, fidelity, and process-safety observations from persisted evidence.
- **Counterfactual Replay** represents paired checkpoint evidence while keeping one replay below a causal claim.
- **Harness CI** applies an explicit regression policy to existing evidence without starting a provider by default.
- **Arena Forge** records untrusted improvement proposals and independent admission evidence; it cannot grade or promote itself.

See [Harness Genome v1](../harness-genome-v1.md), [Harness X-Ray and observatory](../analysis/xray-observatory-v1.md), [Arena Forge](../arena-forge-planner-process-safety-v1.md), and [evidence status](../evidence-status.md).

## Boundary

The Harness Stack is an explanatory and experimental model. It is not a claim that every framework exposes every plane, that catalog metadata proves runtime support, or that Scaffold Arena replaces an agent runtime. Unsupported or unobserved planes remain `unknown` or `HOLD` until named evidence closes the gap.
