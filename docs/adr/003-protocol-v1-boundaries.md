# ADR 003: Preserve protocol-v1 as an evidence-bounded contract

- Status: Accepted
- Date: 2026-08-14
- Decision owner: Scaffold Arena maintainers

## Context

Scaffold Arena compares scaffolds around a model, rather than treating the
repository as a model leaderboard. Fixture, synthetic, local, live-provider,
human, and independent evidence have materially different claim ceilings.
Protocol schemas are already published and consumed by implementation and
release checks.

## Decision

Protocol v1 remains a versioned public contract. Scenario, run-artifact,
eval-card, scaffold-card, failure-taxonomy, annotation, and external-validation
schemas are immutable within v1 except for compatible clarifications. A
breaking schema, scoring, task-family, or claim-boundary change requires a new
protocol version, migration notes, and regenerated evidence.

Every task pack keeps deterministic evaluation weight at or above 70 percent.
Synthetic sources remain visibly labeled in prompts, UI, reports, and docs.
Fixtures demonstrate format and control behaviour only; they cannot be
described as live benchmark results. Provider usage and the central model price
registry are the only sources for cost claims.

## Consequences

- New task packs must supply versioned contracts, deterministic scoring, and
  explicit claim boundaries before they enter the delivery ledger as
  implemented.
- Live, human, and external results are separate evidence classes; no local
  release gate upgrades them.
- Protocol changes are slower by design, but comparisons remain interpretable
  and replayable.

## Alternatives rejected

- Silent schema evolution: it breaks replay and obscures why results changed.
- Treating samples as benchmark evidence: it collapses the evidence boundary.
