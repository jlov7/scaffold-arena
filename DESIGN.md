# Scaffold Arena Design System

## Theme

Scaffold Arena should feel like an enterprise research-lab console: warm near-black workspace, off-white readable typography, signal-green action states, and restrained semantic color. The product is the first screen. There is no marketing hero.

## Palette

Use OKLCH tokens in CSS. Do not use pure black or pure white.

- Canvas: warm graphite near-black for the app background.
- Surface 1: slightly raised charcoal for rails and command surfaces.
- Surface 2: warmer graphite for primary panels.
- Surface 3: high-contrast inset surfaces for code, logs, and dense tables.
- Text primary: warm off-white.
- Text secondary: cool parchment gray.
- Text muted: low-emphasis steel gray.
- Hairline: low-contrast warm gray.
- Hairline strong: visible active/selected borders.
- Accent signal: green for primary run/action/ready states.
- Accent info: blue for guidance and selection.
- Accent warning: amber for budget/preflight caution.
- Accent danger: rose for failed/destructive states.

## Typography

- UI font: Geist Sans via `@fontsource-variable/geist`.
- Mono font: Geist Mono with JetBrains Mono fallback, used for numbers, IDs, code, logs, and compact metadata.
- Do not set the whole app in monospace.
- Product headings use sentence case, medium weight, and fixed rem sizes.
- Labels use short uppercase only where they identify system regions, not as decorative filler.
- Body copy should stay under 75ch when it is explanatory prose.

## Layout

- Desktop shell: left workspace rail, top command/status bar, center stage, right evidence inspector.
- Mobile shell: command bar, scrollable stage, bottom workspace navigation, inspector drawer.
- Keep the center stage focused on the current workflow. Move supporting evidence, timeline, preflight, and next action into the inspector.
- Prefer tables, rails, segmented controls, and rows over repeated card grids.
- Use cards/panels only for durable task regions, modals, drawers, and repeated records.

## Components

- Buttons: compact, tactile, high-contrast labels, icon support, visible active/focus states.
- Icon buttons: use lucide icons at a consistent stroke width.
- Segmented controls: for mode/lane switching.
- Panels: flat or gently raised, 8px radius max for most product surfaces.
- Data tables: tabular numbers, stable row heights, visible selected row.
- Status badges: semantic color plus text, never color alone.
- Empty/error/loading states: always include a next action.
- Modals/drawers: preserve focus management and use tinted overlays, never pure black.

## Motion

- Motion is functional: state change, drawer open/close, selected-row movement, streaming activity.
- Use transform and opacity only.
- Respect `prefers-reduced-motion`.
- Keep durations between 150ms and 260ms for product UI.

## Do

- Make run status, provider readiness, budget, and next action visible.
- Show proof/evidence before secondary decoration.
- Keep workspace navigation stable across routes.
- Use signal green sparingly for the action path.
- Keep synthetic-source labels visible in task/report contexts.

## Do Not

- Do not use gradient text, decorative glass, generic glowing cards, or purple/blue AI gradients.
- Do not add a landing page or hero in front of the usable product.
- Do not use emoji UI.
- Do not collapse data-heavy evidence into marketing cards.
- Do not animate layout dimensions.
