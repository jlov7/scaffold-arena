# Frontend module boundaries

This note describes the current Protocol-v1 frontend. The entry point in `frontend/src/main.tsx` routes `/` and `/workbench/*` to the lazy-loaded Workbench and keeps the legacy application in a separate chunk for compatibility routes.

## Current structure

- `workbench-v1/WorkbenchV1App.tsx` owns route state and durable selection context.
- `workbench-v1/shell/` provides navigation, the Guided/Lab switch, the mobile evidence drawer, and the main stage.
- `workbench-v1/surfaces/` contains the Study, Design, Preflight, Execute, Analyze, Review, Trace Lab, Evidence, X-Ray, Observatory, Counterfactual, Forge, and Settings surfaces.
- `api/v1/` provides typed transport for Protocol-v1 services; UI state remains in the Workbench journeys and surfaces.
- `telemetry/` defines consent-gated, in-memory client events; it is not a remote analytics service.
- `App.tsx`, `features/`, and `components/` retain the separate legacy compatibility experience.

## Dependency rules

- Surfaces use the shared Workbench shell, journeys, and typed API client.
- Typed API modules do not make UI decisions.
- Telemetry and error utilities stay small and independently testable.
- Optional diagnostic surfaces remain route-loaded so they do not enter the Workbench first-load closure.

The source and its tests are the authority for a module boundary. This note does not claim usability, performance, or deployment results.
