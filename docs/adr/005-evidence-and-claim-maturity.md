# ADR 005: Govern claims by evidence maturity, not feature polish

- Status: Accepted
- Date: 2026-08-14
- Decision owner: Scaffold Arena maintainers

## Context

The repository includes convincing local fixtures, protocol checks, and UI
surfaces, while live provider runs, completed human calibration, and
independent reproduction remain absent. A single "done" label would overstate
what the evidence supports.

## Decision

The public evidence classes and current state are defined in
`docs/evidence-status.md`. Evidence paths prove custody of an artifact, not
that every claim in that artifact is true.

Public statements must use the narrowest matching tier. Repository and local
validation can support implementation and local-test claims. Only recorded
live-provider artifacts support live-run claims; only completed calibration
supports human-calibration claims; only independently produced reproduction
materials support external-validation claims. `RELEASED` is a publication
state, not a synonym for validated.

## Consequences

- The beta label remains until the stated live, human, and external evidence
  milestones are resolved with admissible artifacts.
- Claim review points to exact artifacts and an explicit ceiling.
- New evidence upgrades require a frozen artifact and independently checkable
  provenance, not prose alone.

## Alternatives rejected

- One undifferentiated completion status: it permits accidental overclaiming.
- Treating release automation as independent validation: it only proves the
  automation ran against its declared inputs.
