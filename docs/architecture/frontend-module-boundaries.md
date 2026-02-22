# Frontend Module Boundaries

## Purpose
Define maintainable boundaries for the Scaffold Arena frontend so feature work can progress without `App.tsx` becoming a bottleneck.

## Layering Rules
1. `app/` shell and navigation only.
2. `features/` owns domain orchestration and view composition.
3. `components/` contains reusable presentational building blocks.
4. `api/` handles transport only, no UI state decisions.
5. `telemetry/`, `errors/`, `utils/` provide cross-cutting services.

## Current Map
- `src/App.tsx`: top-level shell composition, route switching, and shared run context.
- `src/app/viewState.ts`: canonical app views and path mapping.
- `src/app/layoutTemplates.ts`: page-template and priority-surface class contracts.
- `src/api/client.ts`: typed API entry points.
- `src/hooks/useArenaRun.ts`: run stream orchestration.
- `src/hooks/useSSE.ts`: SSE connection and reconnect strategy.
- `src/components/*`: task selector, arena panels, score dashboard, history, leaderboard, modals.
- `src/components/layout/WorkspaceSection.tsx`: reusable setup/run/review layout wrapper.
- `src/features/app/persistence.ts`: persisted onboarding/checklist/compact-mode reads.
- `src/features/journey/nextAction.ts`: typed next-action key resolution and persona copy.
- `src/features/commands/appCommands.ts`: typed command handler execution for staged actions.
- `src/features/results/roleSummary.ts`: role-adaptive result summary synthesis.
- `src/features/workspaces/{HistoryWorkspace,LeaderboardWorkspace}.tsx`: route container modules.
- `src/errors/classify.ts`: error taxonomy and recovery messaging.
- `src/telemetry/{events,tracker}.ts`: event schema and consent-gated tracking.

## Target Decomposition
- Continue moving route-specific render blocks from `App.tsx` into `features/workspaces/*`.
- Continue moving comparison/autopsy/report orchestration into dedicated feature folders.
- Keep `App.tsx` focused on shell composition, route selection, and shared providers.

## Dependency Constraints
- `features/*` may depend on `components`, `hooks`, `api`, `telemetry`, `errors`, `utils`.
- `components/*` must not import from `features/*`.
- `api/*` must not import UI modules.
- `telemetry/*` and `errors/*` must remain framework-light and testable.

## Testing Strategy per Layer
- `app/`: navigation and route tests.
- `features/`: journey and state transition tests.
- `components/`: rendering, interaction, accessibility tests.
- `api/`, `errors/`, `telemetry/`: unit tests.
