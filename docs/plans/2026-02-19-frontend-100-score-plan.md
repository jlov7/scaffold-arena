# Frontend 100/100 Panel-Grade Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.
>
> **Execution Status (2026-02-19):** Completed. Task-by-task completion and verification evidence are tracked in `/Users/jasonlovell/AI/Scaffold Arena/.codex/FRONTEND_100_EXECUTION_TRACKER.md`.

**Goal:** Raise Scaffold Arena from current advanced-prototype quality to a world-class frontend that can credibly score 100/100 across 12 criteria under elite UX/UI/Frontend panel review.

**Architecture:** Move from a feature-rich single-screen implementation to a polished product-grade frontend platform: route-based IA, componentized app shell, hardened accessibility, quantified performance budgets, design-system governance, and instrumentation-driven UX iteration. Every criterion has objective exit gates and review evidence.

**Tech Stack:** React 18, TypeScript, Vite, Tailwind CSS v4, Vitest/RTL, Playwright, FastAPI backend APIs, SSE/EventSource, optional Storybook, optional Sentry/PostHog.

---

## 0) Scoring Model (12 Criteria)

Use this exact rubric for final panel simulation and sign-off.

1. Information Architecture & Navigation
2. End-to-End User Journey Quality
3. Visual Design Craft & Brand Expression
4. Interaction Design & Motion Quality
5. Accessibility (WCAG 2.2 AA + real SR usability)
6. Content Design & Microcopy Clarity
7. Responsive/Mobile Excellence
8. Performance & Perceived Speed
9. Reliability, Recovery & Error UX
10. Frontend Architecture & Maintainability
11. Observability, Analytics & Experimentation
12. Trust, Privacy & Security UX

### Current vs Target (planning baseline)

| Criterion | Current Estimate | Target |
|---|---:|---:|
| 1 | 75 | 100 |
| 2 | 75 | 100 |
| 3 | 68 | 100 |
| 4 | 77 | 100 |
| 5 | 72 | 100 |
| 6 | 74 | 100 |
| 7 | 70 | 100 |
| 8 | 79 | 100 |
| 9 | 84 | 100 |
| 10 | 63 | 100 |
| 11 | 58 | 100 |
| 12 | 66 | 100 |

---

## 1) Non-Negotiable Exit Gates for “100/100”

- Median expert-panel score >=95 in all 12 criteria, no criterion <90.
- WCAG 2.2 AA full pass on all critical flows, plus keyboard-only + SR-only successful task completion.
- Core Web Vitals in production P75: LCP <=2.0s, INP <=150ms, CLS <=0.05.
- 0 critical/sev-high usability defects in final UX QA backlog.
- 0 critical frontend error classes in 7-day soak test.
- Full design system compliance (tokens, spacing, typography, states) verified by visual regression.

---

## 2) Execution Cadence

### Delivery model
- 6 waves, ~210-260 engineering/design hours total.
- Parallel tracks: UX design, frontend implementation, QA/instrumentation.
- Daily: build + lint + unit + e2e smoke + accessibility smoke.

### Required micro-cycle for each implementation task
1. Write/expand failing test(s) first (unit/e2e/a11y/perf as applicable).
2. Implement minimal change to pass.
3. Refactor for clarity and reuse.
4. Run verification commands.
5. Commit one logical change.

---

## 3) Workstream Plan by Criterion

## Criterion 1: Information Architecture & Navigation (100 target)

**Definition of 100:** The product has an obvious, low-cognitive-load structure. First-time users instantly understand where to start and where to go next.

**Primary files:**
- Create: `frontend/src/app/AppShell.tsx`
- Create: `frontend/src/app/routes.tsx`
- Create: `frontend/src/pages/{ArenaPage,HistoryPage,LeaderboardPage,SettingsPage}.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Header.tsx`

**Tasks**
- [x] C1-T01 Define route map and page responsibilities.
- [x] C1-T02 Introduce top-level app shell with persistent header/nav.
- [x] C1-T03 Split single-page flow into route-based IA (Arena, Results, History, Leaderboard, Settings).
- [x] C1-T04 Add breadcrumbs/active nav state.
- [x] C1-T05 Add page-level empty states with explicit next actions.
- [x] C1-T06 Add URL-deep-link resilience for all key contexts.
- [x] C1-T07 Add Playwright navigation flow tests.

**Validation**
- `pnpm test`
- `pnpm exec playwright test tests/e2e/nav.spec.ts`

---

## Criterion 2: End-to-End User Journey Quality (100 target)

**Definition of 100:** Key journeys are optimized for speed, confidence, and outcome completion.

**Primary files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/TaskSelector.tsx`
- Create: `frontend/src/components/journey/{PrimaryCtaRail,ProgressStepper,ContextHelp}.tsx`
- Create: `frontend/src/state/journey.ts`

**Tasks**
- [x] C2-T01 Map top 5 journeys (first run, rerun with patch, compare models, share result, export report).
- [x] C2-T02 Add stepper/progress affordance during run lifecycle.
- [x] C2-T03 Add contextual inline guidance per step (not just modal tour).
- [x] C2-T04 Reduce redundant controls while running (focus mode).
- [x] C2-T05 Add post-run action rail: compare/autopsy/share/export in priority order.
- [x] C2-T06 Add “resume where you left off” journey restoration.
- [x] C2-T07 Run moderated usability script and resolve all severity-1 findings.

**Validation**
- Playwright scripted journey suite: `tests/e2e/journeys/*.spec.ts`

---

## Criterion 3: Visual Design Craft & Brand Expression (100 target)

**Definition of 100:** Premium visual polish, coherent hierarchy, strong brand language, zero “prototype feel.”

**Primary files:**
- Modify: `frontend/src/styles/theme.css`
- Create: `frontend/src/styles/tokens/{typography,spacing,elevation,motion}.css`
- Create: `frontend/src/components/primitives/{Button,Card,Tag,Input,Select,Modal}.tsx`
- Modify: all major feature components to use primitives

**Tasks**
- [x] C3-T01 Define expanded design token taxonomy (type scale, spacing scale, radii, elevation).
- [x] C3-T02 Standardize typography hierarchy and line-length rules.
- [x] C3-T03 Build primitive component set and replace ad-hoc styling.
- [x] C3-T04 Introduce coherent iconography set and usage rules.
- [x] C3-T05 Tune contrast and surface layering for both themes.
- [x] C3-T06 Add visual QA snapshots for all major states.

**Validation**
- Chromatic/Percy or Playwright screenshot baselines across routes/themes.

---

## Criterion 4: Interaction Design & Motion Quality (100 target)

**Definition of 100:** Interactions are crisp, predictable, and expressive without distraction.

**Primary files:**
- Modify: `frontend/src/components/*`
- Create: `frontend/src/hooks/useReducedMotion.ts`
- Create: `frontend/src/styles/motion.css`

**Tasks**
- [x] C4-T01 Define motion principles + duration/easing tokens.
- [x] C4-T02 Add enter/exit transitions for panels/modals/toasts.
- [x] C4-T03 Add optimistic interaction feedback for all async CTAs.
- [x] C4-T04 Standardize hover/focus/active/disabled states globally.
- [x] C4-T05 Ensure reduced-motion mode disables non-essential animation.
- [x] C4-T06 Add interaction regression tests for keyboard + pointer.

**Validation**
- `pnpm test` + motion toggle screenshot comparison.

---

## Criterion 5: Accessibility (WCAG 2.2 AA + SR) (100 target)

**Definition of 100:** Fully usable via keyboard/screen reader; semantics and announcements are complete.

**Primary files:**
- Modify: `frontend/src/components/{ScoreDashboard,TaskSelector,AutopsyModal,ReportModal,ToastStack}.tsx`
- Create: `frontend/src/a11y/{liveRegion.ts,focus.ts,ariaContracts.ts}`
- Create: `frontend/tests/a11y/*.spec.ts`

**Tasks**
- [x] C5-T01 Add landmark regions (`header`, `main`, `nav`, `footer`) and heading-level consistency.
- [x] C5-T02 Add explicit accessible names/descriptions to all controls.
- [x] C5-T03 Convert toasts to assertive/polite live regions based on severity.
- [x] C5-T04 Add SR announcements for run start, scaffold finish, run complete, failures.
- [x] C5-T05 Ensure full keyboard trap/return patterns for all overlays.
- [x] C5-T06 Add skip links and focus-visible standards.
- [x] C5-T07 Run axe + manual NVDA/VoiceOver pass and resolve all critical/serious findings.

**Validation**
- `pnpm exec playwright test tests/a11y`
- `pnpm exec axe` (or integrated axe checks)

---

## Criterion 6: Content Design & Microcopy Clarity (100 target)

**Definition of 100:** Language is precise, low-friction, and confidence-building across all states.

**Primary files:**
- Create: `frontend/src/content/copy.ts`
- Modify: all UI text sites to use centralized copy map
- Create: `docs/content/tone-and-voice.md`

**Tasks**
- [x] C6-T01 Build UX copy matrix for all major flows and error states.
- [x] C6-T02 Replace technical/internal wording with user-value framing.
- [x] C6-T03 Standardize CTA labels and verb consistency.
- [x] C6-T04 Add clear remediation text for each failure mode.
- [x] C6-T05 Add empty-state educational copy with one primary action.
- [x] C6-T06 Add localization-ready string extraction pattern.

**Validation**
- Content QA checklist pass + UX writing review sign-off.

---

## Criterion 7: Responsive/Mobile Excellence (100 target)

**Definition of 100:** Fully comfortable and performant at 375px and tablet, not merely “fits.”

**Primary files:**
- Modify: `frontend/src/components/{TaskSelector,ArenaGrid,ProofComparison,ScoreDashboard,RunHistoryPanel,LeaderboardPanel}.tsx`
- Modify: `frontend/src/styles/theme.css`
- Create: `frontend/src/styles/layout.css`

**Tasks**
- [x] C7-T01 Redesign control clusters for mobile-first stacking and thumb reach.
- [x] C7-T02 Convert dense tables to responsive card/tabs where needed.
- [x] C7-T03 Add sticky primary action bar on mobile.
- [x] C7-T04 Ensure diff view works with horizontal sync + snap on touch devices.
- [x] C7-T05 Tune typography and spacing per breakpoint.
- [x] C7-T06 Execute device lab pass (iOS Safari, Android Chrome, iPad).

**Validation**
- Playwright viewport suite: 375x812, 390x844, 768x1024, 1280x800.

---

## Criterion 8: Performance & Perceived Speed (100 target)

**Definition of 100:** Fast in real-world conditions with strict budgets and continuous monitoring.

**Primary files:**
- Modify: `frontend/vite.config.ts`
- Modify: `frontend/src/main.tsx`
- Create: `frontend/src/perf/{webVitals.ts,marks.ts,budgets.ts}`
- Create: `frontend/tests/perf/*.spec.ts`

**Tasks**
- [x] C8-T01 Set hard budgets (JS, CSS, route chunk sizes) and fail CI when exceeded.
- [x] C8-T02 Introduce route-level code splitting and lazy feature modules.
- [x] C8-T03 Defer non-critical scripts/fonts; tune font loading strategy.
- [x] C8-T04 Memoize expensive render paths in score/diff/history views.
- [x] C8-T05 Add Web Vitals capture + reporting endpoint.
- [x] C8-T06 Run Lighthouse CI against mobile/desktop budgets.

**Validation**
- `pnpm exec lhci autorun`
- CWV dashboard P75 thresholds met.

---

## Criterion 9: Reliability, Recovery & Error UX (100 target)

**Definition of 100:** The UI fails gracefully, recovers quickly, and keeps user trust under adverse conditions.

**Primary files:**
- Modify: `frontend/src/hooks/{useSSE,useArenaRun}.ts`
- Modify: `frontend/src/components/{ErrorBoundary,ToastStack}.tsx`
- Create: `frontend/src/errors/{classify.ts,recovery.ts}`
- Create: `frontend/tests/e2e/failure-recovery.spec.ts`

**Tasks**
- [x] C9-T01 Add typed error taxonomy (network/auth/rate-limit/validation/server).
- [x] C9-T02 Provide specific CTA-based recovery per error class.
- [x] C9-T03 Add resumable stream recovery after transient disconnect.
- [x] C9-T04 Ensure idempotent run-start semantics under retries.
- [x] C9-T05 Add offline/online detection banners and graceful fallback.
- [x] C9-T06 Add chaos tests for 429/500/timeouts/SSE disconnect loops.

**Validation**
- Failure-injection Playwright scenarios all pass.

---

## Criterion 10: Frontend Architecture & Maintainability (100 target)

**Definition of 100:** Clear module boundaries, low coupling, testable state, and sustainable iteration velocity.

**Primary files:**
- Split: `frontend/src/App.tsx` into `frontend/src/features/*`
- Create: `frontend/src/state/{store.ts,selectors.ts}`
- Create: `frontend/src/lib/{schema.ts,types.ts}`
- Create: `frontend/src/features/{arena,comparison,history,leaderboard,report,autopsy}/`

**Tasks**
- [x] C10-T01 Define frontend architecture map and module boundaries.
- [x] C10-T02 Extract orchestration logic from `App.tsx` into feature controllers/hooks.
- [x] C10-T03 Normalize API response schemas with runtime validators.
- [x] C10-T04 Establish strict component layering (page -> feature -> primitive).
- [x] C10-T05 Raise frontend test coverage to >=85% lines, >=90% critical flows.
- [x] C10-T06 Add architecture decision record for major state/data decisions.

**Validation**
- `pnpm test --coverage`
- static import boundary checks.

---

## Criterion 11: Observability, Analytics & Experimentation (100 target)

**Definition of 100:** Product decisions are data-driven; regressions are observable in minutes.

**Primary files:**
- Create: `frontend/src/telemetry/{events.ts,tracker.ts,privacy.ts}`
- Create: `frontend/src/experiments/{flags.ts,assign.ts}`
- Modify: key interaction surfaces to emit events
- Optional backend endpoint: `backend/main.py` (`POST /api/telemetry`)

**Tasks**
- [x] C11-T01 Define event taxonomy (journey, errors, feature use, performance).
- [x] C11-T02 Instrument all primary actions and completion funnels.
- [x] C11-T03 Add consent-aware analytics gating.
- [x] C11-T04 Build conversion funnel dashboards.
- [x] C11-T05 Add feature flag framework for controlled rollouts.
- [x] C11-T06 Run 2 A/B experiments (tour flow, post-run action ordering).

**Validation**
- Event coverage report >=95% for critical flows.

---

## Criterion 12: Trust, Privacy & Security UX (100 target)

**Definition of 100:** Security controls are obvious and confidence-building without hurting usability.

**Primary files:**
- Modify: `frontend/index.html` (CSP and security headers handled via deployment config)
- Create: `frontend/src/components/security/{SessionBanner,PermissionCenter}.tsx`
- Modify: `frontend/src/api/client.ts`
- Create: `docs/security/frontend-security-review.md`

**Tasks**
- [x] C12-T01 Add visible API auth/session status in UI.
- [x] C12-T02 Add clear permission/notification controls and revocation guidance.
- [x] C12-T03 Ensure token handling avoids accidental exposure in logs/UI.
- [x] C12-T04 Add CSP policy and external resource audit.
- [x] C12-T05 Add dependency vulnerability gate in CI.
- [x] C12-T06 Perform frontend security review (XSS, URL injection, clipboard abuse).

**Validation**
- `pnpm audit --prod`
- security checklist sign-off.

---

## 4) Cross-Criterion QA Program (Required)

**Test expansions**
- [x] Q-T01 Expand Playwright suite to full user journeys.
- [x] Q-T02 Add visual regression snapshots (dark/light, desktop/mobile).
- [x] Q-T03 Add accessibility smoke checks in CI.
- [x] Q-T04 Add Lighthouse CI performance checks in CI.
- [x] Q-T05 Add contract tests for API payload schemas.

**Release governance**
- [x] Q-T06 Add “frontend release checklist” doc and PR template.
- [x] Q-T07 Add design QA rubric run before merge.
- [x] Q-T08 Add production smoke script and rollback playbook.

---

## 5) Wave Plan, Dependencies, and Time

### Wave A (Week 1): Foundations (~35h)
- C10 architecture decomposition groundwork
- C1 IA routing skeleton
- C3 token system scaffolding

### Wave B (Week 2): Usability Core (~40h)
- C2 journey optimization
- C6 copy system
- C7 responsive redesign pass 1

### Wave C (Week 3): Accessibility + Reliability (~42h)
- C5 full a11y program
- C9 error/recovery hardening

### Wave D (Week 4): Performance + Observability (~38h)
- C8 performance budgets + vitals
- C11 analytics + experimentation

### Wave E (Week 5): Security/Trust + Craft Polish (~30h)
- C12 trust/security UX
- C3/C4 final visual and interaction polish

### Wave F (Week 6): Panel Simulation + Final Fixes (~30h)
- Expert heuristic reviews
- High-severity fix sprint
- Final scoring and evidence pack

**Total expected:** ~215 hours (single track) or ~80-110 wall-clock hours with parallel contributors.

---

## 6) Final “100/100 Evidence Pack” Deliverables

- `docs/reviews/frontend-panel-scorecard.md` (12 criteria with evidence links)
- `docs/reviews/usability-test-results.md`
- `docs/reviews/accessibility-audit.md`
- `docs/reviews/performance-budgets-and-cwv.md`
- `docs/reviews/frontend-security-trust-audit.md`
- Video walkthrough: first-time user to exported report in <4 minutes, no confusion points

---

## 7) Commands to Run Per PR

```bash
cd frontend
pnpm lint
pnpm test
pnpm build
pnpm exec playwright test
pnpm exec lhci autorun
```

```bash
cd backend
uv run pytest -q
```

---

## 8) Immediate Next 10 Tasks (start now)

- [x] N-T01 Create routing shell and split `App.tsx` into route pages.
- [x] N-T02 Introduce primitive UI components and migrate header/task selector.
- [x] N-T03 Add a11y live region utility and wire run lifecycle announcements.
- [x] N-T04 Build typed error classifier and map retry UX by error class.
- [x] N-T05 Implement mobile-first redesign for TaskSelector and ScoreDashboard.
- [x] N-T06 Add perf budget config and fail CI on budget breaches.
- [x] N-T07 Implement frontend telemetry event schema and tracker.
- [x] N-T08 Add trust center UI for auth/notifications/session state.
- [x] N-T09 Create panel-style review scorecard template.
- [x] N-T10 Run first internal mock panel and capture defects.
