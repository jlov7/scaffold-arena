# ADR 007: Workbench v1 frontend boundaries

Status: Accepted  
Date: 2026-08-14

## Context

Scaffold Arena has a protocol-v0.1 compatibility interface and a protocol-v1 backend. The v1 workbench exposes the study lifecycle without silently changing legacy routes, duplicating domain truth in the browser, or presenting design fixtures as executed evidence.

## Decision

### Route ownership

- `/` opens Workbench v1 on the Compare decision surface.
- Workbench v1 owns `/workbench/{surface}` where `surface` is `studies`, `design`, `preflight`, `execute`, `analyze`, `trace-lab`, `review`, `evidence`, or `settings`.
- Existing v0.1 routes remain available at `/arena`, `/results`, `/history`, `/leaderboard`, and `/settings` for the compatibility window.
- Unknown `/workbench/*` paths resolve to Workbench Compare with an explicit route-recovery notice. Other unknown paths preserve the v0.1 fallback.

This avoids a routing dependency and preserves the existing FastAPI + React + TypeScript architecture.

### State ownership

- Backend protocol-v1 services remain authoritative for packs, experiments, executions, attempts, evaluations, analyses, reviews, receipts, and decision briefs.
- The URL owns the active surface and selected object identifiers. Shareable identifiers use search parameters; secrets, full manifests, annotations, and generated outputs never do.
- React owns only transient view state: Guided/Lab presentation, open drawers, selected table rows, form drafts, pending requests, and local accessibility preferences.
- A form draft is not an experiment. It becomes authoritative only after a successful create response.
- A frozen experiment is rendered from its persisted response and is never locally edited.

### Data access

- All v1 traffic passes through the typed `frontend/src/api/v1` boundary.
- GET-only SSE is the sole live execution stream. Reconnect uses the persisted cursor and deduplicates by logical event sequence.
- No Workbench component calls `fetch` or `EventSource` directly.
- Malformed, partial, unavailable, or unknown data remains explicit. Missing usage or price data is `UNKNOWN`, never zero.

### Surface composition

- `WorkbenchV1App` composes one shared shell, one navigation model, one evidence inspector, and one surface controller at a time.
- Guided and Lab are two presentations over the same loaded object and operation. They cannot diverge into separate execution paths.
- Each surface is a feature module with its own state hook, view, tests, and truthful state matrix.
- Shared design-system components contain no API or feature imports.
- Visualizations consume analysis view models, expose semantic tables, and link every mark to included attempts and exclusions.

### Offline demonstration

- The bundled pack is imported through the real StudyPack endpoint.
- The hash-pinned bundled adapter may execute only the repository-owned synthetic truth table bound to the exact StudyPack, scenario, harness, budget, and factor assignment.
- Concepts and test fixtures may demonstrate interface states only when visibly labelled `Synthetic fixture — not benchmark evidence.` They never populate the durable evidence store as observed runs.

### Compatibility and release

- The v0.1 UI and API remain independently testable during the compatibility window.
- Workbench v1 becomes the default root only when its Compare-to-Study Canvas journey, error boundary, and route recovery tests pass.
- A surface is not linked from navigation until its required operations and all declared failure states work end-to-end.
- Release maturity follows persisted evidence. UI completeness cannot lift live, human-calibration, or external-reproduction caps.

## Consequences

- Workbench v1 can evolve without exposing unfinished controls.
- The default root changes, while explicit legacy paths remain stable.
- Settings exists in both generations: `/settings` remains v0.1 and `/workbench/settings` is v1.
- Additional list/detail endpoints may be required for durable browser recovery. Such gaps must be implemented in the service/API layer rather than reconstructed from local browser state.
