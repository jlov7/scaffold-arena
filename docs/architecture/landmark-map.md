# Semantic Landmark Map

This document defines the semantic landmark contract per workspace route.

## Shared Landmarks (all routes)

- `a.skip-link`: jump to `#main-content`.
- `header[role="banner"]`: global product identity and top controls.
- `nav[aria-label="Primary"]`: route/workspace switching.
- `main#main-content[role="main"]`: route body content.
- `footer[role="contentinfo"]`: version and attribution.

## Route-Level Landmark Expectations

| Route | Landmark expectations |
| --- | --- |
| `/arena` | `main` includes benchmark setup controls, guided journey context, blocker guidance, and primary action rail. |
| `/results` | `main` includes state callout, role summary, score dashboard, diff view, and comparison/autopsy surfaces. |
| `/history` | `main` includes a history region with deterministic "load run" actions. |
| `/leaderboard` | `main` includes aggregate leaderboard/stat regions only. |
| `/settings` | `main` includes preferences, key management, and telemetry visibility surfaces. |

## Dialog Landmark Contract

All dialogs must satisfy:

- `role="dialog"`.
- `aria-modal="true"`.
- Focus trap on `Tab` / `Shift+Tab`.
- Escape key close.
- Focus return to invoking control.

Current dialogs conforming to this contract:

- Help Center modal.
- Guided Tour modal.
- Shortcut overlay.
- Autopsy modal.
- Report modal.
