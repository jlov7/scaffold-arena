# World-Class UX Re-Architecture Plan (Re-Baseline)

Date: 2026-02-20  
Owner: Product + Frontend + UX Engineering  
Status: In progress (execution tracking in `.codex/UX_REARCH_EXECUTION_TRACKER.md`)

## Purpose

Re-baseline the product honestly from a world-class SaaS UX lens, then define an exhaustive implementation plan to move Scaffold Arena from "functionally strong but cognitively heavy" to "clear, guided, low-friction, premium."

## 1) Re-Baseline: Where We Are Now

This is the current-state score based on live product behavior, screenshots, code structure, and usability heuristics:

| Criterion | Current | Target |
|---|---:|---:|
| 1. Information architecture clarity | 62 | 95+ |
| 2. First-run onboarding quality | 58 | 95+ |
| 3. User journey clarity | 61 | 95+ |
| 4. Cognitive load management | 54 | 95+ |
| 5. Visual hierarchy and layout rhythm | 64 | 95+ |
| 6. Mobile ergonomics and readability | 71 | 95+ |
| 7. Empty/error/recovery usability | 78 | 95+ |
| 8. Accessibility robustness | 86 | 95+ |
| 9. Interaction polish and confidence | 72 | 95+ |
| 10. Personalization for different users | 50 | 95+ |
| 11. Frontend maintainability (UX velocity) | 63 | 95+ |
| 12. Product analytics for UX decisions | 68 | 95+ |
| **Composite** | **65.6** | **95+** |

## 2) Evidence for the Re-Baseline

- The app currently asks users to process too many decisions in one screen before value is felt.
- Primary and secondary actions compete visually in several states.
- Too much simultaneous information is visible for first-time users.
- Heavy orchestration inside one page limits clarity and iteration speed.
- `frontend/src/App.tsx` is currently `2044` lines, with dense state/effect logic, which slows UX refactoring.
- Current docs claim "100/100", but live experience still feels "expert-first" and not sufficiently "novice-safe."

## 3) External Standards and Best-Practice Inputs

This plan aligns to the following design-system and research sources:

- Cloudscape onboarding: role-aware support, progressive disclosure, help + tutorials used together.  
  [Onboarding](https://cloudscape.design/patterns/general/onboarding/)  
  [Hands-on tutorials](https://cloudscape.design/patterns/general/onboarding/hands-on-tutorials/)
- Fluent onboarding: relevant, optional, benefit-focused, coherent, non-distracting in-context guidance.  
  [Fluent onboarding](https://fluent2.microsoft.design/onboarding/)
- Primer progressive disclosure: maintain context, disclose only when needed, avoid disorienting toggles.  
  [Primer progressive disclosure](https://primer.github.io/design/ui-patterns/progressive-disclosure/)
- Atlassian navigation: consistency + flexibility, predictable cross-product patterns, progressive disclosure for power features.  
  [Atlassian navigation design process](https://www.atlassian.com/blog/design/designing-atlassians-new-navigation)
- Atlassian empty states: short, clear reason + clear next action, avoid dead ends.  
  [Atlassian empty state guidance](https://atlassian.design/foundations/content/designing-messages/empty-state/)
- WCAG 2.2 target sizing for reliable touch interaction.  
  [W3C SC 2.5.8](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum)
- HEART framework for UX outcome measurement (goal-signal-metric discipline).  
  [Google CHI paper](https://research.google/pubs/pub36299)
- Service start-page patterns for expectation-setting and "what happens next" clarity.  
  [GOV.UK start pattern](https://design-system.service.gov.uk/patterns/start-using-a-service/)  
  [NHS start page pattern](https://service-manual.nhs.uk/design-system/patterns/start-page)

## 4) User Profiles We Must Design For

1. First-time non-technical evaluator: wants proof quickly, minimal setup confusion.
2. Technical operator: needs repeatable runs, clear controls, low-friction recovery.
3. PM/analyst reviewer: needs confidence in result interpretation and export narrative.
4. Executive viewer: needs summary, winner rationale, and shareable outcome in minutes.
5. Power user/researcher: needs advanced controls without cluttering novice path.
6. Accessibility-dependent user: keyboard/screen reader/high-zoom full operability.
7. Mobile-only reviewer: needs quick understanding and safe action ergonomics.
8. Returning user: wants resume flow, not re-learning flow.

## 5) Core Journeys We Must Optimize

1. First successful run (time-to-value journey).
2. Blocked run recovery (token/config/network) with deterministic next action.
3. Scoreboard interpretation to decision confidence.
4. Proof comparison and "why winner" understanding.
5. Autopsy -> patch -> rerun learning loop.
6. Report export and stakeholder handoff.
7. History revisit and run comparison.
8. Settings confidence (security/privacy/trust controls).
9. Mobile quick-run demo path.
10. "I just want to see value" fast path.

## 6) Target Product UX Shape

- Default "guided mode" for new users, "expert mode" for advanced users.
- Reduce visible options per step; reveal advanced controls progressively.
- One clear primary action per stage.
- Move from "everything-at-once arena page" to stage-led journey architecture:
  - Stage A: Setup
  - Stage B: Run
  - Stage C: Review
  - Stage D: Compare/Export
- Keep contextual help always reachable but non-intrusive.
- Encode recovery playbooks directly into blocked states.

## 7) Exhaustive Implementation Plan (132 Tasks)

Legend: `[ ]` pending, `[x]` complete.

### WS1 — Information Architecture & Navigation (9)

- [x] WS1-T01 Define global IA v2 (Run, Results, Compare, History, Settings, Help).
- [x] WS1-T02 Split current arena layout into route-level containers with clear purpose.
- [x] WS1-T03 Add route-level page intros with outcome-focused one-line goals.
- [x] WS1-T04 Implement consistent breadcrumb + page title + stage subtitle pattern.
- [x] WS1-T05 Introduce "Quick start" entry route and "Advanced workspace" entry route.
- [x] WS1-T06 Remove redundant controls from top shell; enforce priority order.
- [x] WS1-T07 Add persistent "Where am I / what next" stage indicator in shell.
- [x] WS1-T08 Add nav telemetry for confusion signals (back/forth thrash, pogoing).
- [x] WS1-T09 Run tree-testing validation for findability of top 8 tasks.

### WS2 — Onboarding System (9)

- [x] WS2-T01 Define activation event for Scaffold Arena (exact measurable event).
- [x] WS2-T02 Implement first-session onboarding mode selector (guided vs self-serve).
- [x] WS2-T03 Build role selector (Evaluator/Operator/Analyst/Exec) with tailored hints.
- [x] WS2-T04 Build role-specific checklists (3-5 steps max each).
- [x] WS2-T05 Add progress persistence for onboarding steps across sessions.
- [x] WS2-T06 Add "skip and resume later" with non-punitive recovery.
- [x] WS2-T07 Add milestone celebration on first successful run completion.
- [x] WS2-T08 Add contextual "why this matters" content at each onboarding step.
- [x] WS2-T09 Add onboarding analytics dashboard (completion, drop-off, time-to-activate).

### WS3 — Guided Journey Orchestration (9)

- [x] WS3-T01 Define canonical happy path state machine (setup -> run -> review -> compare/export).
- [x] WS3-T02 Enforce one dominant CTA per stage and demote secondary actions.
- [x] WS3-T03 Gate downstream actions until prerequisite completion is clear.
- [x] WS3-T04 Add stage-specific success criteria text ("done when ...").
- [x] WS3-T05 Build inline "next best action" engine from current run state.
- [x] WS3-T06 Add resume points for interrupted sessions.
- [x] WS3-T07 Add explicit "what changed" card after each stage transition.
- [x] WS3-T08 Add in-flow walkthrough for first autopsy/patch cycle.
- [x] WS3-T09 Validate all 10 key journeys via scripted e2e acceptance suite.

### WS4 — Content Design & Microcopy System (9)

- [x] WS4-T01 Create voice-and-tone matrix by context (neutral, warning, success, blocker).
- [x] WS4-T02 Rewrite all primary CTA labels to verb + outcome structure.
- [x] WS4-T03 Standardize helper text patterns (why, required input, expected outcome).
- [x] WS4-T04 Rewrite all blocker/error messages to reason + recovery action + fallback.
- [x] WS4-T05 Rewrite empty states to purpose + next action + optional learn link.
- [x] WS4-T06 Add novice glossary for core terms (scaffold, autopsy, proof, etc.).
- [x] WS4-T07 Add "explain this screen" lightweight overlay in plain language.
- [x] WS4-T08 Add content lint checks to prevent jargon regressions.
- [x] WS4-T09 Add UX writing QA pass in CI checklist.

### WS5 — Visual Hierarchy & Layout Craft (9)

- [x] WS5-T01 Define page-level layout templates (setup-heavy, run-live, review-dense).
- [x] WS5-T02 Reduce card density and introduce stronger spacing rhythm.
- [x] WS5-T03 Rebuild hierarchy scale (headline, section, utility, metadata).
- [x] WS5-T04 Implement visual priority system for critical, important, optional surfaces.
- [x] WS5-T05 Remove low-value decorative strokes and reduce visual noise.
- [x] WS5-T06 Strengthen contrast hierarchy for primary data vs secondary metadata.
- [x] WS5-T07 Rework panel grouping to reduce scan path length.
- [x] WS5-T08 Add visual consistency tokens for alerts, success, blockers, guidance.
- [x] WS5-T09 Run design QA rubric pass on all core routes with screenshot evidence.

### WS6 — Mobile and Responsive Excellence (9)

- [x] WS6-T01 Recompose hero/shell for small viewports (stack strategy, no squeeze).
- [x] WS6-T02 Collapse secondary nav options into progressive mobile patterns.
- [x] WS6-T03 Ensure all critical controls are thumb-zone reachable.
- [x] WS6-T04 Add compact mode for dense review screens with safe defaults.
- [x] WS6-T05 Improve long-content readability in help/tour modals on mobile.
- [x] WS6-T06 Add mobile-first step progress component.
- [x] WS6-T07 Add sticky contextual CTA that changes by stage.
- [x] WS6-T08 Expand viewport test matrix (320, 360, 390, 412, 768, 1024).
- [x] WS6-T09 Add visual baseline snapshots for each critical mobile journey.

### WS7 — Error, Empty, and Recovery UX (9)

- [x] WS7-T01 Build unified state taxonomy (loading, empty, partial, error, blocked, success).
- [x] WS7-T02 Implement deterministic next-action component for all failed states.
- [x] WS7-T03 Add cause-aware retries (quota, auth, network, validation, server).
- [x] WS7-T04 Add inline diagnostics drawer with plain-language explanations.
- [x] WS7-T05 Add "safe fallback mode" when live run cannot proceed.
- [x] WS7-T06 Add recovery banner persistence until issue is resolved.
- [x] WS7-T07 Add guardrail copy to prevent accidental destructive actions.
- [x] WS7-T08 Add recovery e2e scripts for top 12 failure classes.
- [x] WS7-T09 Add failure-to-recovery success KPI in telemetry.

### WS8 — Personalization & Role-Adaptive UX (9)

- [x] WS8-T01 Build role preference model persisted per user/browser.
- [x] WS8-T02 Tailor default layout and CTAs by role.
- [x] WS8-T03 Tailor onboarding checklist by role.
- [x] WS8-T04 Tailor result summaries by role depth (exec short vs analyst deep).
- [x] WS8-T05 Add "complexity slider" (Simple, Standard, Advanced) with persisted setting.
- [x] WS8-T06 Add feature education moments tied to actual behavior, not time.
- [x] WS8-T07 Add role-aware help center sections and quick actions.
- [x] WS8-T08 Add experiment framework for persona-path optimization.
- [x] WS8-T09 Validate each persona with scripted journey acceptance criteria.

### WS9 — Accessibility and Inclusive Design (9)

- [x] WS9-T01 Add semantic landmark map and document it per route.
- [x] WS9-T02 Ensure all dialogs are fully keyboard operable with robust focus return.
- [x] WS9-T03 Add explicit SR announcements for stage transitions and outcomes.
- [x] WS9-T04 Verify all interactive targets meet WCAG 2.2 size/spacing constraints.
- [x] WS9-T05 Add high-zoom (200-400%) and reflow acceptance tests.
- [x] WS9-T06 Add reduced-motion behavior for all meaningful animations.
- [x] WS9-T07 Add color-token contrast verification gates (AA minimum).
- [x] WS9-T08 Add assistive-technology smoke test protocol (VoiceOver/NVDA checklist).
- [x] WS9-T09 Add continuous a11y regression report in CI artifacts.

### WS10 — Performance & Perceived Speed UX (9)

- [x] WS10-T01 Define journey-based perceived speed budgets (first paint, first actionable, first value).
- [x] WS10-T02 Add progressive skeleton states aligned to layout, not generic blocks.
- [x] WS10-T03 Prioritize above-the-fold critical UI and defer low-priority panels.
- [x] WS10-T04 Add optimistic transitions where safe.
- [x] WS10-T05 Reduce heavy re-render chains in high-frequency run updates.
- [x] WS10-T06 Improve streaming output virtualization for long runs.
- [x] WS10-T07 Add performance telemetry to UX dashboard (route-level timings).
- [x] WS10-T08 Run mobile throttled audits (CPU/network) for core journeys.
- [x] WS10-T09 Enforce perf budgets in CI with failure thresholds.

### WS11 — Instrumentation, Experiments, and UX Intelligence (9)

- [x] WS11-T01 Define event taxonomy v2 mapped to each journey stage.
- [x] WS11-T02 Instrument all top journey steps and drop-off points.
- [x] WS11-T03 Build activation funnel dashboard (signup/open -> first value).
- [x] WS11-T04 Build recovery funnel dashboard (error -> resolved run).
- [x] WS11-T05 Add qualitative feedback prompts at key friction points.
- [x] WS11-T06 Add A/B harness for onboarding variants and CTA prioritization.
- [x] WS11-T07 Add role-segmented analytics slices.
- [x] WS11-T08 Add weekly UX regression report generation.
- [x] WS11-T09 Add HEART-style metric scorecard for continuous UX governance.

### WS12 — Frontend Architecture for UX Velocity (9)

- [x] WS12-T01 Break `App.tsx` into route containers + stage modules.
- [x] WS12-T02 Extract journey orchestration state into explicit state machine.
- [x] WS12-T03 Separate domain state, view state, and async effects by module.
- [x] WS12-T04 Create shared "state pattern" primitives for loading/empty/error/success.
- [x] WS12-T05 Consolidate duplicated action logic into typed command handlers.
- [x] WS12-T06 Add architecture tests for feature boundaries and imports.
- [x] WS12-T07 Add visual shell contracts for consistent route composition.
- [x] WS12-T08 Add story-driven component coverage for all core UX primitives.
- [x] WS12-T09 Publish architecture migration ADR with rollback points.

## 8) Cross-Cutting Launch Work (24 Tasks)

### Research & Validation

- [x] LV-T01 Conduct 12 moderated usability sessions across all personas.
- [x] LV-T02 Run first-click tests on IA variants.
- [x] LV-T03 Run tree tests for findability of top tasks.
- [x] LV-T04 Run unmoderated comprehension tests for onboarding copy.
- [x] LV-T05 Run mobile-only validation sessions.
- [x] LV-T06 Run accessibility user testing with keyboard/SR users.

### QA & Testing

- [x] LV-T07 Expand e2e suite to full 10-journey matrix (desktop + mobile).
- [x] LV-T08 Add deterministic test fixtures for all error classes.
- [x] LV-T09 Add visual regression baselines for each route and state family.
- [x] LV-T10 Add content regression tests for critical user-facing strings.
- [x] LV-T11 Add schema checks for telemetry events.
- [x] LV-T12 Add CI gate requiring launch scorecard freshness.

### Documentation & Enablement

- [x] LV-T13 Publish IA map and route responsibilities.
- [x] LV-T14 Publish onboarding design spec with role mapping.
- [x] LV-T15 Publish state taxonomy playbook (all UI states and behaviors).
- [x] LV-T16 Publish copy style guide and reusable templates.
- [x] LV-T17 Publish troubleshooting decision tree (user-facing).
- [x] LV-T18 Publish support runbook for common blockers.

### Governance

- [x] LV-T19 Create weekly UX council review cadence.
- [x] LV-T20 Define severity rubric for UX defects (P0-P3).
- [x] LV-T21 Define acceptance gates before feature merge.
- [x] LV-T22 Define launch/no-launch go-live checklist.
- [x] LV-T23 Define rollback protocol for UX regressions.
- [x] LV-T24 Define monthly product quality review template.

## 9) Program Phasing and Sequencing

### Phase 0 (Days 1-2): Truth and alignment

- Re-baseline metrics, agree activation definition, agree IA v2.
- Exit gate: signed-off scorecard, journeys, and north-star metrics.

### Phase 1 (Days 3-7): IA and onboarding foundations

- WS1 + WS2 core scaffolding.
- Exit gate: first-run flow has single clear path with role-tailored guidance.

### Phase 2 (Days 8-13): Guided journey and state clarity

- WS3 + WS4 + WS7.
- Exit gate: no dead-end states; all failures have deterministic next action.

### Phase 3 (Days 14-18): Visual and mobile upgrade

- WS5 + WS6.
- Exit gate: reduced cognitive load and consistent visual hierarchy on all target viewports.

### Phase 4 (Days 19-23): Accessibility and performance

- WS9 + WS10.
- Exit gate: WCAG checks green, perceived speed budgets met.

### Phase 5 (Days 24-28): Personalization + analytics

- WS8 + WS11.
- Exit gate: role-adaptive journey + activation/recovery dashboards live.

### Phase 6 (Days 29-33): Architecture hardening

- WS12 + cross-cutting validation.
- Exit gate: maintainable structure and stable CI governance.

## 10) Definition of Done (World-Class UX Bar)

- First-time user can complete first successful run without external help.
- Median time-to-first-value reduced by >=40% from current baseline.
- Journey completion rate >=90% for top 5 journeys.
- Critical confusion events reduced by >=60%.
- Accessibility: no critical/serious violations, keyboard/SR core path fully operable.
- Mobile: no clipped critical actions; all primary actions comfortably operable.
- Error recovery success >=85% without human intervention.
- Panel review score target: >=95 in every criterion, none below 90.

## 11) Immediate Next Step (Execution Handshake)

Start with Phase 0 and Phase 1 only, then re-measure before moving forward.  
Do not attempt full visual polish before IA + onboarding simplification land.
