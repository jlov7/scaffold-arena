# IA Route Map (v2)

This map defines the canonical workspace model for Scaffold Arena.

## Global IA

1. `Arena`: Configure benchmark and execute runs.
2. `Results`: Review winner quality, cost, diffs, and proof artifacts.
3. `History`: Reload prior runs and resume analysis from historical context.
4. `Leaderboard`: Inspect aggregate performance and consistency trends.
5. `Settings`: Configure trust, tokens, and advanced operational controls.
6. `Help`: Contextual support via Help Center and guided tour entry points.

## Route Responsibilities

| Route | Primary user outcome | Secondary outcomes | Must not include |
| --- | --- | --- | --- |
| `/arena` | Start a valid run quickly | Guided checklist, blocker recovery, primary CTA flow | Dense post-run analytical surfaces |
| `/results` | Decide winner with evidence | Compare, autopsy walkthrough, export/share actions | Initial setup controls |
| `/history` | Restore past context reliably | Jump back into Results/Arena | Live run controls |
| `/leaderboard` | Understand long-run scaffold behavior | Spot consistency and win-rate trends | Per-run setup and execution controls |
| `/settings` | Configure runtime trust and preferences | Telemetry visibility, advanced controls | Score/diff analysis |

## Global Navigation Contract

- Top nav must always expose `Arena`, `Results`, `History`, `Leaderboard`, and `Settings`.
- Header must always expose `Help`, `Take the tour`, and theme toggle.
- Breadcrumb format is fixed: `Home / <Workspace>`.
- Each workspace must present:
  - A route intro (title + one-line purpose).
  - Current stage indicator.
  - Deterministic "Next action" cue.

## Confusion Telemetry

Navigation now emits:

- `route_changed`: every workspace change.
- `nav_confusion_signal`: back-forth pogo pattern detected within a short window.

These events are used to identify IA friction hotspots for iterative design refinement.
