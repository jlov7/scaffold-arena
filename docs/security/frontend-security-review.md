# Frontend Security & Trust Review

Date: 2026-02-19

## Scope
- UI token handling
- Notification permission UX
- URL/query handling
- Clipboard surfaces
- CSP and external resource constraints
- Dependency risk gates

## Findings and Mitigations

### 1) Token exposure risk
- Status: mitigated
- Current behavior: token is read from `VITE_API_TOKEN` or local storage and only attached to API requests in memory.
- Guardrail: settings UI only shows configured/missing state, never token value.

### 2) Notification permission prompts
- Status: mitigated
- Current behavior: permission requested on first run action, not at page load.
- Guardrail: explicit controls in Settings to request/review permission state.

### 3) URL injection and deep-link safety
- Status: mitigated
- Current behavior: view path parsing is allowlisted via `app/viewState.ts`; unknown routes fallback to `arena`.
- Guardrail: run/task/model query handling validates IDs before applying.

### 4) Clipboard abuse surface
- Status: mitigated
- Current behavior: copy actions are user-initiated from explicit buttons only.
- Guardrail: no background clipboard writes.

### 5) CSP and third-party resources
- Status: mitigated
- Current behavior: CSP meta policy added in `frontend/index.html` with allowlist for self + Google Fonts.

### 6) Dependency vulnerabilities
- Status: mitigated
- Current behavior: CI includes `pnpm audit --prod --audit-level high` as a merge gate.

## Remaining Risk
- Inline theme bootstrap script requires `'unsafe-inline'` in CSP. Recommended next step: move bootstrap to external hashed script and tighten CSP.

## Sign-off Checklist
- [x] Token value never rendered in UI
- [x] Permission prompts are explicit and user-triggered
- [x] Unknown routes do not execute arbitrary logic
- [x] Clipboard actions are explicit and visible
- [x] CI dependency audit gate configured
