# Assistive-technology smoke protocol

Use this human checklist for the Protocol-v1 Workbench after major UX changes and before a release candidate is presented as accessible beyond automated coverage. It is a proposed review protocol, not completed evidence.

## Scope

- Workbench routes: `/`, `/workbench/studies`, `/workbench/design`, `/workbench/preflight`, `/workbench/execute`, `/workbench/analyze`, `/workbench/evidence`, and one deferred diagnostic route.
- Core workflows: select a StudyPack, create or recover a design, inspect a HOLD, run the bundled fixture where available, inspect analysis, and open evidence.
- Platforms: macOS with VoiceOver and Safari; Windows with NVDA and Chrome.

## Checks

1. Navigate landmarks and headings, including the skip link and Workbench-area navigation.
2. Confirm the mobile evidence drawer opens, traps focus, closes with Escape, and returns focus to its trigger.
3. Complete the selected workflow with keyboard only, including a visible HOLD and its recovery action.
4. Confirm controls, status messages, tables, and Guided/Lab mode changes have understandable names and context.
5. Confirm no required action depends on a pointer and no durable identifier is required in Guided mode.

## Evidence to retain

Record the tested revision, platform, assistive technology and browser versions, route/workflow results, findings, and repairs. Keep automated results separate from this human review. Neither a completed smoke nor the automated gate alone is a WCAG certification, cross-browser guarantee, or independent assurance.
