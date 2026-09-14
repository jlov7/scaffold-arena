# Harness X-Ray and observatory v1

Harness X-Ray is a static, provider-free inspection of either an explicit local path or a named captured artifact. It accepts repository, ACP metadata, CLI metadata, OpenTelemetry bundle, SDK-integration, and recorded-run captures. It never executes, installs, replays, crawls, or fetches a target.

```sh
arena xray ./path/to/harness
```

The local command is read-only and deliberately non-durable: it reads one regular file of at most 1 MiB, or a bounded directory manifest of at most 1,024 non-symlink entries. If it finds a supported descriptor it reads only that bounded descriptor. It returns a content digest but does not add an artifact, change the inspected path, or start a provider. A durable report instead names an already captured artifact with the database, artifact-store, and project arguments; durable reports have a content-addressed report artifact.

In the Workbench, Guided mode lists only durable captured-source snapshots already scoped to the active project. It presents their human-readable name and revision, keeps raw artifact digests out of the guided path, and submits the selected immutable capture with `source_kind: auto`. An empty registry remains a typed setup state: X-Ray does not crawl or execute a repository to make the list look populated. Lab mode continues to accept an exact existing artifact digest for forensic and automation workflows.

## Candidate mechanism boundary

X-Ray produces a candidate Harness Genome and mechanism graph. `declared`, `observed`, `inferred`, `verified`, `unsupported`, and `unknown` remain distinct. Every non-unknown result links to the captured source artifact; untrusted labels, URIs, source text, trace payloads, secrets, and private reasoning are not copied into the report. Inference is not verification, parser absence is not unsupported behavior, and a fixture is not a live run.

The report explicitly includes mechanisms, unobservable controls, confounds, security-critical paths, a first study, expected attempts, a cost interval, limitations, and an evidence ceiling. Static inputs normally leave attempts and cost `unknown`; the report never manufactures provider usage or price evidence.

## Observatory boundary

Context Ledger fields are source, scope, sensitivity, tokens, retrieval score, transformation lineage, ordering, compression survival, delivery, citation/use, and cost. Its metrics are useful-context density, irrelevant-token ratio, stale-context rate, instruction survival, source coverage, compression loss, contradiction exposure, retrieval precision/recall, context-window utilization, and context cost per success.

Memory Ledger fields are origin, representation, scope, TTL/retention, updates, conflicts, retrievals, downstream decisions, deletion/forgetting, privacy, and cost. Its metrics are write precision, retrieval precision/recall, stale memory, contradiction resolution, write amplification, negative transfer, cross-task interference, privacy leakage, forgetting correctness, marginal contribution, and cost per useful retrieval.

Loop microscope checks repeated-state loops, oscillation, redundant tools, verification without correction, retries with unchanged inputs, context growth without progress, premature stopping, missing stopping conditions, deadlock/livelock, unbounded delegation, and recovery that worsens state. Graph microscope checks critical path, fan-in/fan-out, coordination overhead, duplicated messages, state bottlenecks, failure propagation, authority concentration, unused nodes, cycles, unreachable transitions, and expensive low-value branches.

All unavailable values remain `unknown`, with a denominator and exclusions where a metric has one; they are never rendered as zero. Fidelity is ordered exactly: `declared` → `assigned` → `available` → `triggered` → `applied` → `activated` → `observed` → `downstream pathway detected`. The last stage requires its named persisted event; it is not inferred from a declaration, assignment, activation, or outcome.

ITT, opportunity, activation, fidelity-failure, and treatment-on-the-treated values are reported only when their required assignment, denominator, activation, outcome, exclusion, and no-confounding assumptions are present. This v1 diagnostic does not establish those assumptions, so it records them as not estimated rather than guessing.

Fixture and captured-input evidence proves only the named bounded report. It is not runtime truth, causality, performance, live-provider, or security-assurance evidence.
