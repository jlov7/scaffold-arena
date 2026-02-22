# Scaffold Arena — Release Readiness Plan

> **50 items. 6 priority tiers. One path from broken prototype to world-class product.**
>
> Generated: 2026-02-19 | Status: Pre-release audit complete

---

## Table of Contents

- [Executive Summary](#executive-summary)
- [How to Read This Plan](#how-to-read-this-plan)
- [Phase 1 — Critical Bug Fixes](#phase-1--critical-bug-fixes-stop-shipping-broken-things)
- [Phase 2 — Security & Stability](#phase-2--security--stability-safe-to-deploy)
- [Phase 3 — Reliability & Resilience](#phase-3--reliability--resilience-wont-fall-over)
- [Phase 4 — Infrastructure & DevOps](#phase-4--infrastructure--devops-deployable--maintainable)
- [Phase 5 — UX Polish & Completeness](#phase-5--ux-polish--completeness-feels-professional)
- [Phase 6 — Feature Completeness](#phase-6--feature-completeness-world-class)
- [Implementation Schedule](#implementation-schedule)
- [Dependency Graph](#dependency-graph)
- [Risk Register](#risk-register)
- [Definition of Done](#definition-of-done)
- [Appendix: File Impact Map](#appendix-file-impact-map)

---

## Executive Summary

Scaffold Arena has a complete architectural skeleton — 4 scaffolds, 3 tasks, real-time SSE streaming, evaluation harness, autopsy analysis, proof comparison, and report generation — all wired into a polished React frontend with the Dark Precision design system.

**However, the app has critical bugs that prevent 2 of 3 tasks from scoring, zero tests, zero authentication, and zero deployment infrastructure.** It is a well-architected prototype, not a releasable product.

This plan addresses every gap in 6 phases:

| Phase | Items | Effort | Outcome |
|-------|-------|--------|---------|
| **1. Critical Bugs** | 5 | ~3 hrs | App actually works end-to-end |
| **2. Security & Stability** | 7 | ~8 hrs | Safe to expose to users |
| **3. Reliability & Resilience** | 8 | ~14 hrs | Handles failures gracefully |
| **4. Infrastructure & DevOps** | 5 | ~10 hrs | Deployable and maintainable |
| **5. UX Polish** | 13 | ~12 hrs | Feels like a real product |
| **6. World-Class Features** | 12 | ~30 hrs | Competitive differentiation |
| **Total** | **50** | **~77 hrs** | **Release-ready** |

**Minimum viable release** = Phases 1–3 (20 items, ~25 hrs).
**Production-grade release** = Phases 1–5 (38 items, ~47 hrs).
**World-class release** = All phases (50 items, ~77 hrs).

---

## How to Read This Plan

Each item follows this format:

> ### #N — Title `[EFFORT]` `[TAGS]`
> **Problem:** What's wrong or missing
> **Solution:** What to build
> **Files:** Which files are created or modified
> **Dependencies:** Which items must be completed first
> **Acceptance Criteria:** How to verify it's done

**Effort scale:**

| Label | Time | Description |
|-------|------|-------------|
| `XS` | <30 min | Config change, one-liner fix |
| `S` | 30 min – 1 hr | Single-file fix, small component |
| `M` | 1–3 hrs | Multi-file feature, moderate complexity |
| `L` | 3–8 hrs | Major feature, multiple components |
| `XL` | 8+ hrs | System-level change, extensive work |

**Tags:** `bug` `security` `testing` `infra` `ux` `feature` `a11y` `perf`

---

## Phase 1 — Critical Bug Fixes *(Stop shipping broken things)*

> **Goal:** Make the app actually work end-to-end for all 3 tasks.
> **Estimated effort:** ~3 hours
> **Prerequisite for:** Everything else

---

### #1 — Fix task_type key mismatch in evaluation harness `S` `bug`

**Problem:** The evaluation harness checks for `"risk_analysis"` and `"research_synthesis"` but the actual task classes define `task_type = "risk"` and `task_type = "research"`. When either task is evaluated, `WEIGHT_TABLES[task.task_type]` raises a `KeyError`, and the scaffold is marked as failed. **2 of 3 tasks are completely broken.**

**Solution:** Align the keys. Two approaches (pick one):
- **Option A (recommended):** Update `WEIGHT_TABLES` keys and all `if/elif` branches in `harness.py` to match the actual task_type values (`"risk"`, `"research"`).
- **Option B:** Update `RiskAnalysisTask.task_type` to `"risk_analysis"` and `ResearchSynthesisTask.task_type` to `"research_synthesis"`.

Option A is safer — it changes the consumer to match the producer, not the other way around.

**Files:**
- `backend/evaluation/harness.py` — Update `WEIGHT_TABLES` keys (line ~20) and `if/elif` branches (lines ~56, ~65, ~82)

**Dependencies:** None

**Acceptance Criteria:**
- [x] `WEIGHT_TABLES` contains keys matching all 3 task_type values
- [x] All `if/elif` branches in `evaluate()` match actual task_type values
- [x] Running evaluation for all 3 tasks produces scores (not `KeyError`)

---

### #2 — Fix task_type key mismatch in autopsy analyzer `S` `bug`

**Problem:** Same mismatch as #1, but in `autopsy/analyzer.py`. The analyzer's task-specific failure analysis branches check `"risk_analysis"` and `"research_synthesis"` instead of `"risk"` and `"research"`. Autopsy analysis falls through to a generic path for 2 of 3 tasks.

**Solution:** Update all `if/elif` comparisons in `analyzer.py` to use the actual task_type values.

**Files:**
- `backend/autopsy/analyzer.py` — Update task_type comparisons (lines ~169–216)

**Dependencies:** None (but should align with #1's chosen approach)

**Acceptance Criteria:**
- [x] Autopsy analyzer correctly identifies task-specific failures for all 3 task types
- [x] Task-type comparisons match actual `task.task_type` values

---

### #3 — Fix PDF dependency mismatch `XS` `bug`

**Problem:** `pyproject.toml` declares `reportlab` as the PDF optional dependency, but `report/pdf.py` imports `weasyprint`. Anyone who installs the `pdf` extra still can't generate PDFs.

**Solution:** Either change the dependency to `weasyprint` or rewrite `pdf.py` to use `reportlab`. Since `weasyprint` is already the import target, change the declared dependency.

**Files:**
- `backend/pyproject.toml` — Replace `reportlab>=4.0` with `weasyprint>=62.0` in `[project.optional-dependencies]`

**Dependencies:** None

**Acceptance Criteria:**
- [x] `uv pip install -e ".[pdf]"` installs the correct PDF library
- [x] `report/pdf.py` imports succeed after installation
- [x] PDF export produces a valid PDF file

---

### #4 — Fix report generator error handling for unknown IDs `S` `bug`

**Problem:** `report/markdown.py` calls `get_task(task_id)` and `get_model(model_id)` which raise `ValueError` on unknown IDs. The code has `task.name if task else task_id` guard clauses, but they're dead code because the function raises instead of returning `None`. Unknown IDs crash the `/api/reports` endpoint with an unhandled 500 error.

**Solution:** Wrap `get_task()` and `get_model()` calls in try/except, falling back to the raw ID string.

**Files:**
- `backend/report/markdown.py` — Add try/except around `get_task()` and `get_model()` calls (lines ~22–25)

**Dependencies:** None

**Acceptance Criteria:**
- [x] Report generates successfully even with an unknown task_id or model_id
- [x] Known IDs still resolve to human-readable names
- [x] No 500 errors on the `/api/reports` endpoint

---

### #5 — Fix LLM judge info keys in report `XS` `bug`

**Problem:** The report template reads `judge_info.get("model")` and `judge_info.get("enabled")`, but the actual judge result dict uses keys `"model_id"`, `"scores"`, and `"explanation"`. The LLM Judge section of the report always shows `N/A` / `False` regardless of actual judge data.

**Solution:** Update the key access to match the actual judge result structure.

**Files:**
- `backend/report/markdown.py` — Fix judge_info key access (lines ~60–62)

**Dependencies:** None

**Acceptance Criteria:**
- [x] Report correctly displays the judge model ID when LLM judge is enabled
- [x] Report correctly displays judge-generated scores and notes

---

## Phase 2 — Security & Stability *(Safe to deploy)*

> **Goal:** Prevent abuse, enforce limits, validate input.
> **Estimated effort:** ~8 hours
> **Prerequisite for:** Any deployment beyond localhost

---

### #6 — Add API authentication `M` `security`

**Problem:** Zero authentication exists. Any client with network access can trigger unlimited API-key-burning runs against your Anthropic account.

**Solution:** Implement a simple bearer token authentication scheme:
- Add `API_SECRET_KEY` to settings (env var)
- Create a FastAPI `Depends()` that checks `Authorization: Bearer <token>` header
- Apply to all mutating endpoints (`POST /api/runs`, `/api/comparisons`, `/api/autopsy`, `/api/patch-reruns`, `/api/reports`)
- Leave `GET /api/health` and `GET /api/meta` unauthenticated
- Frontend sends the token from a config/env (or prompt on first load)

**Files:**
- `backend/config/settings.py` — Add `api_secret_key: str` field
- `backend/core/auth.py` — New file: `verify_token` dependency
- `backend/main.py` — Add `Depends(verify_token)` to protected endpoints
- `frontend/src/api/client.ts` — Add `Authorization` header to all requests
- `.env.example` — Add `API_SECRET_KEY` documentation

**Dependencies:** None

**Acceptance Criteria:**
- [x] Unauthenticated requests to protected endpoints return 401
- [x] Valid bearer token grants access
- [x] Invalid/missing token is rejected with clear error message
- [x] GET endpoints remain accessible without auth
- [x] Frontend correctly sends token with all requests

---

### #7 — Add rate limiting `M` `security`

**Problem:** No rate limiting exists. A single client can POST `/api/runs` in a tight loop and issue unlimited concurrent Anthropic API calls, bounded only by the provider semaphore.

**Solution:** Add `slowapi` rate limiting:
- Global rate limit: 60 requests/minute per IP
- Run creation: 5 runs/minute per IP
- Comparison/autopsy/report: 10/minute per IP
- Return `429 Too Many Requests` with `Retry-After` header

**Files:**
- `backend/pyproject.toml` — Add `slowapi` dependency
- `backend/main.py` — Configure `SlowAPI` middleware and per-endpoint limits

**Dependencies:** None

**Acceptance Criteria:**
- [x] Exceeding rate limit returns 429 with `Retry-After` header
- [x] Normal usage is unaffected
- [x] Different endpoints have appropriate limits

---

### #8 — Add cost cap / budget limits `M` `security`

**Problem:** No per-run or daily spend ceiling. A single user can burn unlimited API costs.

**Solution:**
- Add `max_cost_per_run_usd` (default: $2.00) and `daily_budget_usd` (default: $50.00) to settings
- Track cumulative daily spend in an in-memory counter (reset daily)
- Before each LLM call in `provider.py`, check remaining budget
- If budget exceeded, raise a `BudgetExceededError` that the scaffold catches gracefully
- Return remaining budget info in `/api/meta` response

**Files:**
- `backend/config/settings.py` — Add budget settings
- `backend/core/provider.py` — Add pre-call budget check
- `backend/core/budget.py` — New file: budget tracker with daily reset
- `backend/main.py` — Include budget info in `/api/meta`

**Dependencies:** None

**Acceptance Criteria:**
- [x] Run stops gracefully when per-run cost limit is hit
- [x] New runs rejected when daily budget is exhausted
- [x] Budget info visible in `/api/meta` response
- [x] Budget limits configurable via environment variables

---

### #9 — Add request size limits `XS` `security`

**Problem:** No request body size limits. A client could send a multi-MB string in the `/api/autopsy` `output` field or `/api/reports` `results` dict.

**Solution:**
- Add request body size limit at the ASGI layer (1MB default)
- Add `max_length` validators on string fields in Pydantic request models
- Return 413 Payload Too Large for oversized requests

**Files:**
- `backend/main.py` — Add request size limit middleware
- `backend/main.py` — Add field-level `max_length` constraints to request models

**Dependencies:** None

**Acceptance Criteria:**
- [x] Requests exceeding 1MB are rejected with 413
- [x] Individual string fields are length-limited
- [x] Normal requests are unaffected

---

### #10 — Enforce scaffold execution timeout `S` `security`

**Problem:** `RunOptions.timeout_s = 75` exists as a field but is never applied. A hanging API call or infinite retry loop blocks the scaffold coroutine forever, consuming a semaphore slot permanently.

**Solution:** Wrap the scaffold execution in `asyncio.wait_for()` with the configured timeout:
```python
try:
    async for event in asyncio.wait_for(scaffold.run(...), timeout=options.timeout_s):
        ...
except asyncio.TimeoutError:
    yield scaffold_failed(run_id, scaffold_id, "Scaffold timed out", retryable=False)
```

**Files:**
- `backend/core/run_engine.py` — Wrap `_run_single_scaffold` inner loop with `asyncio.wait_for`

**Dependencies:** None

**Acceptance Criteria:**
- [x] Scaffolds that exceed `timeout_s` are terminated with a `scaffold_failed` event
- [x] Timeout value is configurable via `RunOptions`
- [x] Other scaffolds in the same arena run continue unaffected
- [x] Semaphore is released on timeout

---

### #11 — Evict completed runs from memory `S` `security` `perf`

**Problem:** `_runs: dict[str, RunState]` grows unbounded. Completed runs are never cleaned up. Long-running servers will eventually OOM.

**Solution:**
- Add a TTL-based eviction: after a run completes, keep it for 30 minutes (configurable), then delete
- Use an `asyncio.create_task` that sleeps and cleans up, or a periodic sweep task
- Return 410 Gone for requests to evicted run IDs

**Files:**
- `backend/core/run_engine.py` — Add eviction logic with configurable TTL
- `backend/config/settings.py` — Add `run_ttl_minutes` setting

**Dependencies:** None

**Acceptance Criteria:**
- [x] Completed runs are automatically evicted after TTL expires
- [x] Requests to evicted runs return 410 Gone
- [x] Active/streaming runs are never evicted
- [x] Memory usage stabilizes over time

---

### #12 — Add input validation at endpoint level `M` `security`

**Problem:** `POST /api/runs` accepts any `task_id`, `model_id`, and `scaffold_ids` strings, returns 200, then silently fails in background tasks. Users get a run_id but see `scaffold_failed` events with no clear indication that their input was invalid.

**Solution:**
- Validate `task_id` against registered tasks before creating the run
- Validate `model_id` against `MODEL_REGISTRY` before creating the run
- Validate `scaffold_ids` (if provided) against registered scaffolds
- Validate `options` values (temperature range 0.0–2.0, max_output_tokens > 0)
- Return 400 Bad Request with specific error messages for invalid input

**Files:**
- `backend/main.py` — Add validation logic before `start_arena_run()` call on each relevant endpoint

**Dependencies:** None

**Acceptance Criteria:**
- [x] Unknown task_id returns 400 with `"Unknown task: {id}. Available: [...]"`
- [x] Unknown model_id returns 400 with `"Unknown model: {id}. Available: [...]"`
- [x] Invalid option values return 400 with specific constraint messages
- [x] Valid requests continue to work identically

---

## Phase 3 — Reliability & Resilience *(Won't fall over)*

> **Goal:** Handle failures gracefully, test everything, provide feedback.
> **Estimated effort:** ~14 hours
> **Prerequisite for:** Confident deployment

---

### #13 — Backend test suite `XL` `testing`

**Problem:** Zero test files exist despite pytest being configured. No coverage of the evaluation harness, JSON extraction, scaffolds, events, or API routes — all of which have confirmed bugs.

**Solution:** Write a comprehensive test suite covering:
- **Unit tests:** `json_extract.py` (all 4 fallback strategies), `events.py` (event formatting), `models.py` (cost calculation), `deterministic.py` (each metric function), `harness.py` (weight tables, all task types)
- **Integration tests:** API endpoint validation (valid/invalid inputs, error responses), SSE event streaming, scaffold lifecycle
- **Edge case tests:** empty output, malformed JSON, unknown task/model IDs, timeout scenarios, cancellation

**Files:**
- `backend/tests/` — New directory with:
  - `test_json_extract.py`
  - `test_events.py`
  - `test_models.py`
  - `test_deterministic.py`
  - `test_harness.py`
  - `test_api.py`
  - `test_run_engine.py`
  - `conftest.py` (shared fixtures)

**Dependencies:** #1, #2 (fix bugs before writing tests that assert correct behavior)

**Acceptance Criteria:**
- [x] `uv run pytest` passes with 0 failures
- [x] Coverage ≥80% on `evaluation/`, `utils/`, `core/events.py`, `config/models.py`
- [x] All 3 task types have evaluation tests
- [x] JSON extraction has tests for all 4 fallback strategies + edge cases
- [x] API endpoints have tests for valid input, invalid input, and error responses

---

### #14 — Frontend test suite `L` `testing`

**Problem:** Zero frontend tests. No vitest, no testing-library. Components, hooks, and API client are completely untested.

**Solution:**
- Add vitest + @testing-library/react + msw (mock service worker)
- Test critical hooks: `useArenaRun` (state transitions), `useSSE` (connection lifecycle)
- Test key components: `ScoreDashboard` (ranking logic), `TaskSelector` (selection state), `ArenaPanel` (status rendering)
- Test API client: request formatting, error handling

**Files:**
- `frontend/package.json` — Add vitest, @testing-library/react, @testing-library/jest-dom, msw
- `frontend/vitest.config.ts` — New file
- `frontend/src/__tests__/` — New directory with:
  - `useArenaRun.test.ts`
  - `useSSE.test.ts`
  - `ScoreDashboard.test.tsx`
  - `TaskSelector.test.tsx`
  - `ArenaPanel.test.tsx`
  - `api/client.test.ts`

**Dependencies:** #34 (remove dead deps first to avoid test setup issues)

**Acceptance Criteria:**
- [x] `pnpm test` passes with 0 failures
- [x] Critical hooks have state transition tests
- [x] Key components render correctly for all status variants
- [x] API client correctly formats requests and handles errors

---

### #15 — Add provider retry logic with exponential backoff `M` `bug`

**Problem:** `provider.py` makes single-attempt API calls. Anthropic rate limits or transient 5xx errors cause immediate `scaffold_failed`. The `retryable: bool` field in `scaffold_failed` events exists but is always `False` and unused.

**Solution:**
- Add `tenacity` for retry logic with exponential backoff
- Classify errors: retryable (rate limit 429, server 5xx, connection errors) vs fatal (auth 401, bad request 400, content policy)
- Max 3 retries with jitter for retryable errors
- Set `retryable: True` on scaffold_failed events for retryable failures that exhausted retries
- Log retry attempts

**Files:**
- `backend/pyproject.toml` — Add `tenacity` dependency
- `backend/core/provider.py` — Add retry decorator to `stream_text()` and `complete()`

**Dependencies:** #23 (logging should exist to log retries, but not blocking)

**Acceptance Criteria:**
- [x] Rate limit errors (429) trigger retry with exponential backoff
- [x] Server errors (5xx) trigger retry
- [x] Auth errors (401) fail immediately without retry
- [x] Max retry count is configurable
- [x] Retries are logged with attempt number and wait time

---

### #16 — Add React error boundary `S` `ux`

**Problem:** Any render-time exception unmounts the entire React tree, showing a blank white screen with no user feedback.

**Solution:**
- Create a top-level `ErrorBoundary` component with a styled fallback UI
- Create a per-panel `PanelErrorBoundary` so one panel crash doesn't take down the whole app
- Fallback UI shows error message, stack trace (dev only), and a "Reload" button
- Match the Dark Precision design system

**Files:**
- `frontend/src/components/ErrorBoundary.tsx` — New file: top-level error boundary
- `frontend/src/components/PanelErrorBoundary.tsx` — New file: per-panel wrapper
- `frontend/src/main.tsx` — Wrap `<App>` with `<ErrorBoundary>`
- `frontend/src/components/ArenaGrid.tsx` — Wrap each `<ArenaPanel>` with `<PanelErrorBoundary>`

**Dependencies:** None

**Acceptance Criteria:**
- [x] Component render errors show a styled fallback instead of white screen
- [x] Per-panel errors are isolated — other panels continue working
- [x] Fallback includes a "Reload" button
- [x] Error details visible in development mode only

---

### #17 — SSE reconnection with user feedback `M` `ux`

**Problem:** Browser EventSource auto-reconnects but the UI has no awareness of connection state. If the backend dies mid-run, `isRunning` stays `true` forever and the user sees a frozen interface.

**Solution:**
- Add connection state tracking to `useSSE`: `connected`, `reconnecting`, `failed`
- After N consecutive reconnection failures (e.g., 5), set state to `failed` and close EventSource
- Add a reconnection timeout: if no successful reconnect within 30s, fail
- Expose connection state from `useArenaRun` so the UI can show a "Connection lost" banner
- Add a "Retry" button in the banner

**Files:**
- `frontend/src/hooks/useSSE.ts` — Add connection state tracking, retry counting, failure detection
- `frontend/src/hooks/useArenaRun.ts` — Expose connection state
- `frontend/src/App.tsx` — Render connection status banner when disconnected

**Dependencies:** None

**Acceptance Criteria:**
- [x] Connection loss shows a visible "Connection lost — retrying..." banner
- [x] After 5 failed retries, banner shows "Connection failed" with Retry button
- [x] Successful reconnection dismisses the banner
- [x] `isRunning` resets to `false` on permanent connection failure

---

### #18 — Prevent double-click race on Run button `S` `bug`

**Problem:** Between clicking "Run Arena" and receiving the `run_started` SSE event, the button still shows "Run Arena". A rapid double-click fires `createArenaRun` twice, creating two simultaneous arena runs.

**Solution:**
- Set `isRunning` to `true` immediately in `startRun()` (before the API call), not on the first SSE event
- Add a `useRef`-based in-flight guard to `startRun()` to reject concurrent calls
- If the API call fails, reset `isRunning` to `false`

**Files:**
- `frontend/src/hooks/useArenaRun.ts` — Set `isRunning` immediately, add in-flight guard

**Dependencies:** None

**Acceptance Criteria:**
- [x] Button changes to "Cancel" immediately on click (before SSE connects)
- [x] Rapid double-click only creates one run
- [x] If API call fails, button reverts to "Run Arena"

---

### #19 — Handle backend errors for all operations `M` `ux`

**Problem:** Only `fetchMeta()` failure shows an error to the user. Run start failure, comparison failure, and several other operations silently swallow errors — the user sees nothing.

**Solution:**
- Add try/catch in `handleRun` with error state and user notification
- Add error feedback in `handleRunComparison` (currently only resets loading)
- Ensure all `catch` blocks surface errors to the user via the toast system (#26)
- Add a connection error state for SSE failures

**Files:**
- `frontend/src/App.tsx` — Add try/catch and error states to all async handlers
- `frontend/src/hooks/useArenaRun.ts` — Add error state for run creation failure

**Dependencies:** #26 (toast system for showing errors — can use inline fallback initially)

**Acceptance Criteria:**
- [x] Failed run creation shows error message to user
- [x] Failed comparison shows error message
- [x] Failed autopsy shows error in modal (already partially done)
- [x] Failed report shows error in modal (already partially done)
- [x] No errors are silently swallowed

---

### #20 — Add graceful shutdown handling `S` `infra`

**Problem:** No `shutdown` event handler. Background tasks are abruptly cancelled on `SIGTERM`, potentially leaving Anthropic API connections half-open and queued events undelivered.

**Solution:**
- Add `@app.on_event("shutdown")` (or `lifespan` context manager) that:
  - Cancels all active runs gracefully (sets `cancelled = True`, waits briefly)
  - Closes SSE connections
  - Logs shutdown
- Handle `SIGTERM` and `SIGINT` signals

**Files:**
- `backend/main.py` — Add shutdown handler with run cancellation and cleanup

**Dependencies:** #23 (logging, but not blocking)

**Acceptance Criteria:**
- [x] `SIGTERM` triggers graceful shutdown
- [x] Active runs are cancelled before process exit
- [x] No orphaned API connections after shutdown
- [x] Shutdown completes within 10 seconds

---

## Phase 4 — Infrastructure & DevOps *(Deployable & maintainable)*

> **Goal:** CI/CD pipeline, containerization, observability.
> **Estimated effort:** ~10 hours
> **Prerequisite for:** Team development, staging/production deployment

---

### #21 — Docker setup (Dockerfile + docker-compose) `L` `infra`

**Problem:** No containerization. Can't deploy to any container platform (Railway, Fly.io, AWS ECS, etc.).

**Solution:**
- `Dockerfile` for backend (Python 3.11 + uv)
- `Dockerfile` for frontend (Node 22 + pnpm, multi-stage build with nginx)
- `docker-compose.yml` that runs both services with:
  - Environment variable passthrough
  - Health checks
  - Volume mounts for development
  - Network configuration

**Files:**
- `backend/Dockerfile` — New file
- `frontend/Dockerfile` — New file
- `docker-compose.yml` — New file (root level)
- `frontend/nginx.conf` — New file (production static serving config)

**Dependencies:** None

**Acceptance Criteria:**
- [x] `docker compose up` starts both backend and frontend
- [x] Frontend proxies API requests to backend
- [x] Health check endpoint responds
- [x] Hot reload works in development mode
- [x] Production build produces optimized images

---

### #22 — GitHub Actions CI/CD pipeline `L` `infra`

**Problem:** No automated quality gates. PRs can merge with broken types, failing tests, or lint errors.

**Solution:** Create GitHub Actions workflows:
- **`ci.yml`** — On push/PR to main:
  - Backend: `uv run ruff check`, `uv run pytest`, `uv run mypy`
  - Frontend: `pnpm lint`, `pnpm test`, `pnpm build` (includes tsc)
  - Both must pass before merge
- **`docker.yml`** — On push to main: build and test Docker images

**Files:**
- `.github/workflows/ci.yml` — New file
- `.github/workflows/docker.yml` — New file
- `backend/pyproject.toml` — Add `ruff` and `mypy` to dev dependencies

**Dependencies:** #13, #14 (tests must exist before CI runs them)

**Acceptance Criteria:**
- [x] PRs show CI status checks
- [x] Failing tests block merge
- [x] Type errors block merge
- [x] Lint errors block merge
- [x] Docker build is verified on push to main

---

### #23 — Add structured logging `M` `infra`

**Problem:** Zero `import logging` anywhere. Errors are silently swallowed in `except` blocks. No way to debug production issues.

**Solution:**
- Configure Python `logging` with structured JSON output (using `structlog` or `python-json-logger`)
- Add log calls at key points: run start/end, scaffold start/end/fail, API call start/end, evaluation results, errors
- Include context fields: `run_id`, `scaffold_id`, `task_id`, `model_id`
- Log level configurable via environment variable

**Files:**
- `backend/pyproject.toml` — Add `structlog` dependency
- `backend/config/logging.py` — New file: logging configuration
- `backend/core/run_engine.py` — Add log calls at lifecycle points
- `backend/core/provider.py` — Add log calls for API calls and errors
- `backend/evaluation/harness.py` — Add log calls for evaluation results
- `backend/main.py` — Initialize logging on startup

**Dependencies:** None

**Acceptance Criteria:**
- [x] All run lifecycle events are logged with structured context
- [x] Errors include full exception info
- [x] Log level is configurable via `LOG_LEVEL` env var
- [x] Logs are JSON-formatted for production parsing

---

### #24 — Add persistent storage (SQLite) `L` `infra`

**Problem:** Everything is in-memory. Server restart = all history lost. Can't run multiple instances behind a load balancer.

**Solution:**
- Add SQLite via `aiosqlite` for run persistence
- Store: run metadata, scaffold results, evaluation scores, comparison results
- Keep the hot path (SSE streaming) in-memory for performance
- Persist to SQLite on run completion
- Add `GET /api/runs` endpoint to list past runs
- Add `GET /api/runs/{id}` endpoint to retrieve past run results

**Files:**
- `backend/pyproject.toml` — Add `aiosqlite` dependency
- `backend/core/storage.py` — New file: SQLite storage layer
- `backend/core/run_engine.py` — Persist completed runs to storage
- `backend/main.py` — Add run history endpoints, initialize DB on startup

**Dependencies:** #11 (run eviction pairs with persistence — evict from memory, keep in DB)

**Acceptance Criteria:**
- [x] Completed runs survive server restart
- [x] `GET /api/runs` returns past runs with metadata
- [x] `GET /api/runs/{id}` returns full run results
- [x] SSE streaming performance is unaffected
- [x] Database file is created automatically on first startup

---

### #25 — Tighten CORS for production `XS` `security`

**Problem:** `allow_methods=["*"]` and `allow_headers=["*"]` is overly permissive. The origin split logic doesn't strip whitespace.

**Solution:**
- Restrict `allow_methods` to `["GET", "POST", "OPTIONS"]`
- Restrict `allow_headers` to `["Authorization", "Content-Type"]`
- Strip whitespace from comma-split CORS origins
- Document production CORS setup in `.env.example`

**Files:**
- `backend/main.py` — Tighten CORS configuration
- `.env.example` — Document CORS_ORIGINS for production

**Dependencies:** None

**Acceptance Criteria:**
- [x] Only GET, POST, OPTIONS methods are allowed
- [x] Only required headers are allowed
- [x] Whitespace in CORS_ORIGINS env var is handled
- [x] Frontend still works with updated CORS

---

## Phase 5 — UX Polish & Completeness *(Feels professional)*

> **Goal:** Accessible, responsive, polished user experience.
> **Estimated effort:** ~12 hours
> **Prerequisite for:** Public launch, user testing

---

### #26 — Add toast notification system `M` `ux`

**Problem:** Errors are either shown inline in modals or silently swallowed. No global transient feedback mechanism.

**Solution:**
- Add `sonner` (lightweight, unstyled toast library — 3KB)
- Create a `<Toaster>` at the app root with Dark Precision styling
- Use toasts for: run failed, comparison failed, copied to clipboard, report exported, connection issues
- Replace silent `catch` blocks with toast notifications

**Files:**
- `frontend/package.json` — Add `sonner`
- `frontend/src/App.tsx` — Add `<Toaster>` component
- `frontend/src/components/Toast.tsx` — New file: styled toast wrapper
- All files with silent `catch` blocks — Add toast calls

**Dependencies:** None

**Acceptance Criteria:**
- [x] Error toasts appear for all failed operations
- [x] Success toasts appear for clipboard copy, export
- [x] Toasts auto-dismiss after 5 seconds
- [x] Toasts match Dark Precision design system
- [x] Multiple toasts stack correctly

---

### #27 — Fix ProofComparison responsive layout `S` `ux`

**Problem:** Fixed `grid-cols-[180px_1fr_1fr_80px_80px_90px_80px_80px_80px]` with no responsive override. On mobile (<768px), content clips and overflows without scroll.

**Solution:**
- Wrap the grid in `overflow-x-auto` container
- Add a mobile-friendly card layout alternative for `<md` breakpoint
- Or: convert to a responsive table with horizontal scroll

**Files:**
- `frontend/src/components/ProofComparison.tsx` — Add responsive wrapper and mobile layout

**Dependencies:** None

**Acceptance Criteria:**
- [x] ProofComparison is usable on 375px-wide screens
- [x] No horizontal overflow without scroll affordance
- [x] Desktop layout unchanged

---

### #28 — Modal accessibility (ARIA, focus trap, Escape) `M` `a11y`

**Problem:** Neither modal has `role="dialog"`, `aria-modal`, `aria-labelledby`, focus trap, or Escape key handler. They're invisible to screen readers and keyboard-only users.

**Solution:**
- Add proper ARIA attributes to both modals
- Implement focus trap (focus stays inside modal while open)
- Add `Escape` key handler to close modals
- Move focus to first focusable element on open
- Return focus to trigger element on close
- Add `aria-label` to all interactive elements

**Files:**
- `frontend/src/components/AutopsyModal.tsx` — Add ARIA, focus trap, Escape handler
- `frontend/src/components/ReportModal.tsx` — Add ARIA, focus trap, Escape handler

**Dependencies:** None

**Acceptance Criteria:**
- [x] Screen reader announces modal title on open
- [x] Tab key cycles within modal (focus trap)
- [x] Escape key closes modal
- [x] Focus returns to trigger button on close
- [x] Modal backdrop click closes modal

---

### #29 — Add keyboard shortcuts `S` `ux` `a11y`

**Problem:** No keyboard shortcuts exist. Power users can't run arenas, close modals, or navigate without mouse.

**Solution:**
- `Cmd/Ctrl + Enter` — Run Arena (or Cancel if running)
- `Escape` — Close any open modal
- `?` — Show keyboard shortcut help overlay
- Use a small keyboard shortcut hook (no library needed)

**Files:**
- `frontend/src/hooks/useKeyboardShortcuts.ts` — New file
- `frontend/src/App.tsx` — Register shortcuts
- `frontend/src/components/KeyboardShortcutHelp.tsx` — New file: `?` overlay

**Dependencies:** None

**Acceptance Criteria:**
- [x] Cmd+Enter triggers run from anywhere on page
- [x] Escape closes open modals
- [x] `?` shows shortcut reference overlay
- [x] Shortcuts don't fire when typing in form fields

---

### #30 — Add loading skeletons `S` `ux`

**Problem:** All loading states are pulsing text ("Connecting to arena...", "Computing...", "Analyzing..."). No skeleton placeholders to preserve layout.

**Solution:**
- Create a `Skeleton` component (animated gradient bar matching Dark Precision)
- Use skeletons for: initial meta load (task cards + model dropdown), comparison computing, autopsy analysis
- Replace `animate-pulse` text with skeleton shapes that match the final content layout

**Files:**
- `frontend/src/components/Skeleton.tsx` — New file: reusable skeleton component
- `frontend/src/App.tsx` — Use skeletons for meta loading state
- `frontend/src/components/ProofComparison.tsx` — Use skeletons for loading state
- `frontend/src/components/AutopsyModal.tsx` — Use skeletons for loading state

**Dependencies:** None

**Acceptance Criteria:**
- [x] Skeleton shapes match the layout of the final content
- [x] Skeletons animate with a subtle shimmer
- [x] No layout shift when real content loads

---

### #31 — Make ScoreDashboard tooltip keyboard-accessible `S` `a11y`

**Problem:** `BreakdownTooltip` only shows on mouse hover. Keyboard-only users and screen readers can't access score breakdowns.

**Solution:**
- Add `tabIndex={0}` to the score cell
- Show tooltip on `focus` as well as `hover`
- Add `aria-describedby` linking the tooltip
- Add `role="tooltip"` to the tooltip element

**Files:**
- `frontend/src/components/ScoreDashboard.tsx` — Update `ScoreCell` with focus handling and ARIA

**Dependencies:** None

**Acceptance Criteria:**
- [x] Tab key can focus score cells
- [x] Tooltip appears on focus (not just hover)
- [x] Screen reader announces tooltip content
- [x] Tooltip dismisses on blur/Escape

---

### #32 — Add copy-to-clipboard functionality `S` `ux`

**Problem:** Users can't copy streaming output, scores, or report markdown from within the app.

**Solution:**
- Add a copy button to:
  - `StreamingText` component (copy raw output)
  - `ReportModal` (copy markdown)
  - `ScoreDashboard` (copy results as formatted text)
- Use `navigator.clipboard.writeText()` with toast confirmation

**Files:**
- `frontend/src/components/StreamingText.tsx` — Add copy button
- `frontend/src/components/ReportModal.tsx` — Add copy button
- `frontend/src/components/ScoreDashboard.tsx` — Add copy button
- `frontend/src/utils/clipboard.ts` — New file: clipboard helper with fallback

**Dependencies:** #26 (toast for "Copied!" feedback)

**Acceptance Criteria:**
- [x] Copy button appears on hover/focus for each copyable section
- [x] Click copies content to clipboard
- [x] Toast confirms "Copied to clipboard"
- [x] Fallback for browsers without clipboard API

---

### #33 — Add estimated run cost display `S` `ux`

**Problem:** Model dropdown shows raw token pricing (`$3/$15`) but doesn't estimate actual run cost. Users have no idea how much a run will cost before clicking.

**Solution:**
- Calculate estimated cost based on: model pricing × average tokens per scaffold × number of scaffolds
- Display "Estimated cost: ~$X.XX" below the model dropdown
- Update estimate when task or model selection changes
- Add a tooltip explaining the estimate is approximate

**Files:**
- `frontend/src/components/TaskSelector.tsx` — Add cost estimation display
- `frontend/src/types/index.ts` — Add cost estimation fields to meta types (or compute client-side)

**Dependencies:** None

**Acceptance Criteria:**
- [x] Estimated cost shown before run starts
- [x] Estimate updates when task or model changes
- [x] Tooltip explains it's approximate
- [x] Estimate is within 2x of actual cost for typical runs

---

### #34 — Remove dead dependencies `XS` `perf`

**Problem:** `framer-motion` (~130KB gzipped), `recharts`, `react-markdown`, and `lucide-react` are all installed but have zero imports in `src/`. They inflate the bundle and slow installs.

**Solution:** Remove all four from `package.json` and reinstall.

**Files:**
- `frontend/package.json` — Remove `framer-motion`, `recharts`, `react-markdown`, `lucide-react`

**Dependencies:** None

**Acceptance Criteria:**
- [x] `pnpm build` still succeeds
- [x] Bundle size decreases
- [x] No import errors

---

### #35 — Add persistent state (localStorage + URL params) `M` `ux`

**Problem:** Page refresh = full reset. Selected task/model are lost. No way to share or bookmark a specific state.

**Solution:**
- Persist last-selected task and model to `localStorage`
- Restore on page load
- Add URL search params for task and model: `?task=extraction&model=claude-sonnet-4-6`
- URL params take precedence over localStorage

**Files:**
- `frontend/src/hooks/usePersistedState.ts` — New file: localStorage hook
- `frontend/src/App.tsx` — Use persisted state for task/model selection
- `frontend/src/components/TaskSelector.tsx` — Accept initial values from props

**Dependencies:** None

**Acceptance Criteria:**
- [x] Refresh preserves last-selected task and model
- [x] URL params override localStorage
- [x] Sharing a URL with params preselects the right task/model
- [x] No errors if localStorage is unavailable

---

### #36 — Add custom favicon and app icons `XS` `ux`

**Problem:** Default Vite logo. No branded favicon, no Apple touch icon, no web manifest.

**Solution:**
- Design a simple arena/bracket favicon (SVG for crispness)
- Generate PNG variants for Apple touch icon and Android
- Add `manifest.json` for PWA metadata
- Replace Vite favicon reference in `index.html`

**Files:**
- `frontend/public/favicon.svg` — New file
- `frontend/public/apple-touch-icon.png` — New file
- `frontend/public/manifest.json` — New file
- `frontend/index.html` — Update favicon references, add manifest link

**Dependencies:** None

**Acceptance Criteria:**
- [x] Browser tab shows custom icon (not Vite logo)
- [x] Apple touch icon appears when bookmarking on iOS
- [x] Manifest file has correct metadata

---

### #37 — Add Open Graph and meta tags `XS` `ux`

**Problem:** Sharing a link on Twitter/LinkedIn/Slack shows no title, description, or preview image.

**Solution:**
- Add `<meta name="description">`, `og:title`, `og:description`, `og:image`, `og:type`, `twitter:card`, `twitter:title`, `twitter:description`
- Create an OG image (1200×630) showing the arena concept
- Add to `index.html` `<head>`

**Files:**
- `frontend/index.html` — Add meta tags
- `frontend/public/og-image.png` — New file: Open Graph preview image

**Dependencies:** None

**Acceptance Criteria:**
- [x] Link shared on Twitter shows title + description + image
- [x] Link shared on Slack shows rich preview
- [x] Meta description is ≤160 characters

---

### #38 — Add footer with version and credits `XS` `ux`

**Problem:** No version number, credits, or links visible in the app.

**Solution:**
- Add a minimal footer below `<main>` with:
  - Version from `package.json` (injected at build time via Vite define)
  - "Built with Anthropic Claude" attribution
  - GitHub repo link (when public)
- Style to be subtle and unobtrusive

**Files:**
- `frontend/src/App.tsx` — Add `<footer>` element
- `frontend/vite.config.ts` — Inject version from package.json

**Dependencies:** None

**Acceptance Criteria:**
- [x] Version number visible in footer
- [x] Footer doesn't visually compete with main content
- [x] Version auto-updates from package.json on build

---

## Phase 6 — Feature Completeness *(World-class)*

> **Goal:** Differentiation features that make Scaffold Arena exceptional.
> **Estimated effort:** ~30 hours
> **These are the features that make people say "wow."**

---

### #39 — Run history panel `L` `feature`

**Problem:** Every page load is a blank slate. Users can't review, compare, or reference previous runs.

**Solution:**
- Add a collapsible sidebar or dropdown showing past runs
- Each entry shows: timestamp, task, model, winner, top score
- Clicking a past run loads its results into the ScoreDashboard
- Store in SQLite (#24) and display via `GET /api/runs`

**Files:**
- `frontend/src/components/RunHistory.tsx` — New file
- `frontend/src/App.tsx` — Integrate history panel
- Backend already has storage from #24

**Dependencies:** #24 (persistent storage)

**Acceptance Criteria:**
- [x] Past runs are listed with key metadata
- [x] Clicking a run loads its results
- [x] Most recent runs appear first
- [x] Empty state says "No runs yet"

---

### #40 — Result caching for repeated task+model combos `M` `feature` `perf`

**Problem:** Running the same task + model combination re-runs everything from scratch, burning API credits. During demos, this is wasteful.

**Solution:**
- Cache results keyed by `(task_id, model_id, scaffold_id, options_hash)`
- On run start, check cache and serve cached results if available
- Add a "Force re-run" toggle to bypass cache
- Cache TTL configurable (default: 24 hours)
- Show "Cached" badge on results served from cache

**Files:**
- `backend/core/cache.py` — New file: result cache with TTL
- `backend/core/run_engine.py` — Check cache before running scaffolds
- `frontend/src/components/TaskSelector.tsx` — Add "Force re-run" toggle
- `frontend/src/components/ArenaPanel.tsx` — Show "Cached" badge

**Dependencies:** #24 (storage layer)

**Acceptance Criteria:**
- [x] Second run of same config serves cached results instantly
- [x] "Force re-run" bypasses cache
- [x] Cache entries expire after TTL
- [x] "Cached" badge is visible on cached results

---

### #41 — Side-by-side output diff view `L` `feature`

**Problem:** Understanding *why* scaffolds scored differently requires reading both outputs fully. No visual diff exists.

**Solution:**
- Add a "Compare Outputs" button to ScoreDashboard
- Opens a split-pane view showing two scaffold outputs side by side
- Highlight differences using a diff algorithm (e.g., `diff-match-patch` or `jsdiff`)
- Color-code: green for additions in the better output, red for omissions
- Allow selecting which two scaffolds to compare

**Files:**
- `frontend/src/components/OutputDiff.tsx` — New file: diff viewer component
- `frontend/package.json` — Add `diff` or `diff-match-patch` library
- `frontend/src/components/ScoreDashboard.tsx` — Add "Compare Outputs" button

**Dependencies:** None

**Acceptance Criteria:**
- [x] Users can select any two scaffolds to compare
- [x] Differences are visually highlighted
- [x] Additions and omissions are color-coded
- [x] Long outputs are scrollable with synchronized scroll

---

### #42 — Scaffold configuration UI `M` `feature`

**Problem:** Users can't adjust temperature, max tokens, or scaffold-specific parameters. Everything uses server defaults.

**Solution:**
- Add an "Advanced Settings" expandable section in TaskSelector
- Allow overriding: temperature (0.0–2.0 slider), max_output_tokens, timeout
- Send overrides as `options` in the run request
- Show current settings in each ArenaPanel header during run

**Files:**
- `frontend/src/components/AdvancedSettings.tsx` — New file: settings panel
- `frontend/src/components/TaskSelector.tsx` — Integrate settings panel
- `frontend/src/types/index.ts` — Add options types

**Dependencies:** #12 (input validation, so server validates option values)

**Acceptance Criteria:**
- [x] Temperature slider adjusts from 0.0 to 2.0
- [x] Max tokens can be set
- [x] Settings persist in localStorage
- [x] Default values match current server defaults

---

### #43 — Custom task creation (paste your prompt) `L` `feature`

**Problem:** Users are locked to 3 built-in tasks. Can't test scaffolding on their own use cases.

**Solution:**
- Add a "Custom Task" card in TaskSelector
- Opens a form with: task name, prompt text, expected output schema (optional JSON schema), evaluation weights
- Custom tasks use generic deterministic evaluation (schema validity + completeness)
- Store custom tasks in localStorage (frontend) and send as request payload

**Files:**
- `frontend/src/components/CustomTaskForm.tsx` — New file: task creation form
- `frontend/src/components/TaskSelector.tsx` — Add "Custom Task" card
- `backend/main.py` — Accept custom task definition in run request
- `backend/tasks/custom.py` — New file: dynamic task from user-provided config

**Dependencies:** None

**Acceptance Criteria:**
- [x] Users can create a custom task with name + prompt
- [x] Custom task runs through all 4 scaffolds
- [x] Results are evaluated with generic metrics
- [x] Custom tasks saved in localStorage for reuse
- [x] Optional JSON schema enables schema validation metrics

---

### #44 — Model comparison mode `L` `feature`

**Problem:** Can only compare scaffolds for a single model. Users can't see "does Model A + Bare beat Model B + Bare?" — which is a key insight.

**Solution:**
- Add a "Model vs Model" toggle mode
- In this mode: select one scaffold, two models
- Run the same scaffold with both models simultaneously
- Show results side by side with the same ScoreDashboard format
- Reuses existing ArenaGrid with 2 panels instead of 4

**Files:**
- `frontend/src/components/TaskSelector.tsx` — Add mode toggle and second model dropdown
- `frontend/src/hooks/useArenaRun.ts` — Support model-comparison mode
- `backend/main.py` — Accept `mode: "scaffold" | "model"` in run request
- `backend/core/run_engine.py` — Handle model-comparison run mode

**Dependencies:** None

**Acceptance Criteria:**
- [x] Users can switch between scaffold-comparison and model-comparison modes
- [x] Model comparison runs one scaffold on two models simultaneously
- [x] Results are displayed side by side
- [x] Evaluation and scoring work identically in both modes

---

### #45 — Shareable run URLs `M` `feature`

**Problem:** Can't share a link to a specific run result. Every page load starts fresh.

**Solution:**
- After a run completes, update the URL to include the run ID: `/runs/{id}`
- Loading a run URL fetches results from the API and displays them
- Add a "Share" button that copies the URL to clipboard
- Requires persistent storage (#24) to serve past run data

**Files:**
- `frontend/src/App.tsx` — Add URL-based routing for run results
- `frontend/src/api/client.ts` — Add `fetchRun(id)` API call
- `frontend/src/components/ScoreDashboard.tsx` — Add "Share" button
- Backend already has `GET /api/runs/{id}` from #24

**Dependencies:** #24 (persistent storage), #32 (clipboard utility)

**Acceptance Criteria:**
- [x] URL updates after run completes
- [x] Opening a run URL loads the results
- [x] "Share" button copies URL to clipboard
- [x] Shared URL works for anyone with access

---

### #46 — Export results to JSON `S` `feature`

**Problem:** Report exports to Markdown/PDF but raw structured results aren't downloadable for programmatic use.

**Solution:**
- Add a "Download JSON" button to ScoreDashboard
- Export includes: run metadata, all scaffold results, evaluation breakdown, metrics, comparison data
- Pretty-printed with 2-space indentation

**Files:**
- `frontend/src/components/ScoreDashboard.tsx` — Add "Download JSON" button
- `frontend/src/utils/export.ts` — New file: JSON export helper

**Dependencies:** None

**Acceptance Criteria:**
- [x] JSON download includes all run data
- [x] File is named `scaffold-arena-{task}-{timestamp}.json`
- [x] JSON is pretty-printed and human-readable
- [x] All numeric values are actual numbers (not strings)

---

### #47 — Dark/light theme toggle `M` `ux`

**Problem:** Dark-only. Some users need light mode for presentations, screenshots, or printed reports.

**Solution:**
- Add a theme toggle button in the header
- Define light theme CSS variables as a parallel set
- Toggle by adding/removing a `data-theme="light"` attribute on `<html>`
- Persist preference in localStorage
- Respect `prefers-color-scheme` on first visit

**Files:**
- `frontend/src/styles/theme.css` — Add light theme variables under `[data-theme="light"]`
- `frontend/src/hooks/useTheme.ts` — New file: theme toggle hook with localStorage
- `frontend/src/App.tsx` — Add theme toggle button in header

**Dependencies:** None

**Acceptance Criteria:**
- [x] Toggle switches between dark and light themes
- [x] Preference persists across sessions
- [x] First visit respects system preference
- [x] All components are readable in both themes
- [x] No flash of wrong theme on load

---

### #48 — Guided onboarding tour `M` `feature`

**Problem:** The "How it works" section is static text. New users may not understand the workflow or what buttons do.

**Solution:**
- Add a step-by-step guided tour using a lightweight library (e.g., `driver.js` — 5KB)
- Steps: (1) Task selection, (2) Model selection, (3) Run button, (4) Arena panels, (5) Score dashboard, (6) Proof comparison
- Trigger on first visit (localStorage flag)
- Add a "Take the tour" button in the header for returning users
- Highlight UI elements with an overlay

**Files:**
- `frontend/package.json` — Add `driver.js`
- `frontend/src/components/GuidedTour.tsx` — New file: tour configuration
- `frontend/src/App.tsx` — Integrate tour trigger

**Dependencies:** None

**Acceptance Criteria:**
- [x] Tour starts automatically on first visit
- [x] Each step highlights the relevant UI element
- [x] Users can skip or dismiss the tour
- [x] "Take the tour" button available for returning users
- [x] Tour doesn't interfere with normal app usage

---

### #49 — Browser notification on run completion `S` `feature`

**Problem:** Arena runs take 10–60 seconds. Users who tab away have no way to know when results are ready.

**Solution:**
- Request notification permission on first run
- Send a browser `Notification` when `run_complete` event fires (only if tab is not focused)
- Include winner scaffold name and top score in notification
- Add a `document.title` flash ("✓ Results Ready — Scaffold Arena") as a fallback

**Files:**
- `frontend/src/hooks/useArenaRun.ts` — Add notification on run_complete
- `frontend/src/utils/notifications.ts` — New file: notification permission + send helpers

**Dependencies:** None

**Acceptance Criteria:**
- [x] Browser notification appears when run completes and tab is unfocused
- [x] Notification shows winner name and score
- [x] Title bar flashes when run completes
- [x] Permission is requested gracefully (not on page load)
- [x] No notification if tab is focused

---

### #50 — Historical leaderboard / aggregate stats `L` `feature`

**Problem:** Each run is isolated. Over many runs, which scaffold wins most often? Which tasks benefit most from scaffolding? Aggregate data tells the scaffolding story more powerfully than any single run.

**Solution:**
- Add a "Leaderboard" tab/section showing:
  - Win rate by scaffold (across all runs)
  - Average score by scaffold per task type
  - Average cost by scaffold
  - Best QPD (quality per dollar) configurations
  - Score distribution charts (using a lightweight chart library)
- Powered by aggregate queries on the SQLite database
- Adds a `GET /api/stats` endpoint

**Files:**
- `backend/core/stats.py` — New file: aggregate query logic
- `backend/main.py` — Add `GET /api/stats` endpoint
- `frontend/src/components/Leaderboard.tsx` — New file: stats dashboard
- `frontend/src/App.tsx` — Add leaderboard tab/section
- `frontend/package.json` — Add lightweight chart library (e.g., `chart.js` via `react-chartjs-2`, or keep `recharts` from #34 if needed here)

**Dependencies:** #24 (persistent storage), #39 (run history — leaderboard needs multiple runs)

**Acceptance Criteria:**
- [x] Win rate displayed per scaffold
- [x] Average score per scaffold per task
- [x] Charts visualize score distributions
- [x] Stats update after each new run
- [x] Empty state shows "Run at least 3 arenas to see stats"

---

## Implementation Schedule

### Suggested execution order (with parallelization)

```
Week 1: Foundation
├── Day 1-2: Phase 1 (Critical Bugs)          ← ~3 hrs, unblocks everything
├── Day 2-3: Phase 2 (Security & Stability)    ← ~8 hrs, parallel work possible
│   ├── #6 Auth + #7 Rate limiting             ← can be done together
│   ├── #8 Budget + #9 Size limits             ← can be done together
│   └── #10 Timeout + #11 Eviction + #12 Validation
└── Day 3-4: Start Phase 3
    ├── #16 Error boundary                     ← quick win
    ├── #17 SSE reconnection
    ├── #18 Double-click guard
    └── #15 Provider retry

Week 2: Testing & Infrastructure
├── Day 5-6: #13 Backend test suite            ← largest single item
├── Day 6-7: #14 Frontend test suite           ← parallel with backend tests
├── Day 7:   #19 Error handling + #20 Shutdown
├── Day 8:   Phase 4 starts
│   ├── #21 Docker setup
│   ├── #23 Structured logging                 ← parallel with Docker
│   └── #25 CORS tightening
└── Day 9:   #22 CI/CD pipeline (depends on tests)
             #24 SQLite storage

Week 3: Polish
├── Day 10-11: Phase 5 (UX Polish)
│   ├── #26 Toast system                       ← unblocks #32
│   ├── #27 Responsive ProofComparison
│   ├── #28 Modal accessibility
│   ├── #29 Keyboard shortcuts
│   ├── #34 Remove dead deps                   ← quick win
│   ├── #36 Favicon + #37 OG tags + #38 Footer ← batch these
│   └── #30 Skeletons + #31 Tooltip a11y
├── Day 12:
│   ├── #32 Clipboard (needs #26)
│   ├── #33 Cost estimation
│   └── #35 Persistent state

Week 4+: World-Class Features
├── #39 Run history (needs #24)
├── #41 Output diff view
├── #43 Custom task creation
├── #44 Model comparison mode
├── #46 JSON export
├── #47 Dark/light theme
├── #48 Guided tour
├── #49 Browser notifications
├── #40 Result caching (needs #24)
├── #42 Scaffold config UI (needs #12)
├── #45 Shareable URLs (needs #24, #32)
└── #50 Leaderboard (needs #24, #39)
```

---

## Dependency Graph

```
Legend:  A ──→ B  means "B depends on A" (A must be done first)

Phase 1 (no dependencies — start here)
  #1 ──→ #13 (fix bugs before testing them)
  #2 ──→ #13
  #3 (standalone)
  #4 (standalone)
  #5 (standalone)

Phase 2 (standalone — can parallel with Phase 1 fixes)
  #6 through #12 (all independent of each other)

Phase 3
  #13 ──→ #22 (tests before CI)
  #14 ──→ #22 (tests before CI)
  #15 (standalone)
  #16 (standalone)
  #17 (standalone)
  #18 (standalone)
  #19 ──→ #26 (toast system for error display)
  #20 (standalone)

Phase 4
  #11 ──→ #24 (eviction pairs with persistence)
  #13 + #14 ──→ #22 (CI needs tests)

Phase 5
  #26 ──→ #32 (clipboard needs toast for feedback)
  #34 ──→ #14 (clean deps before test setup)

Phase 6
  #24 ──→ #39 (history needs storage)
  #24 ──→ #40 (caching needs storage)
  #24 + #32 ──→ #45 (shareable URLs need storage + clipboard)
  #24 + #39 ──→ #50 (leaderboard needs storage + history)
  #12 ──→ #42 (config UI needs input validation)
```

---

## Risk Register

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Anthropic API changes break provider.py | High | Low | Pin SDK version, add integration test |
| SQLite performance under concurrent writes | Medium | Medium | Use WAL mode, test with 50 concurrent runs |
| Weasyprint installation issues on Linux | Medium | High | Provide Docker image with pre-installed deps, document alternatives |
| SSE connection limits in production (behind proxy) | High | Medium | Document proxy configuration, add WebSocket fallback option |
| Bundle size growth from new dependencies | Low | Medium | Track bundle size in CI, tree-shake aggressively |
| Custom tasks enabling prompt injection | High | Low | Sandbox custom prompts, add content filtering |
| Cost overrun during demo/testing | High | Medium | Budget limits (#8), result caching (#40) |
| localStorage quota exceeded | Low | Low | Implement LRU eviction, cap storage usage |

---

## Definition of Done

A feature is "done" when:

- [x] Code is written and compiles (TypeScript `--noEmit`, Python imports clean)
- [x] Tests pass (if test infrastructure exists for that layer)
- [x] No regressions in existing functionality
- [x] Matches Dark Precision design system (frontend changes)
- [x] Accessible — keyboard navigable, screen reader friendly (frontend changes)
- [x] Works on mobile (≥375px) and desktop (frontend changes)
- [x] Error states handled and surfaced to user
- [x] No console errors or warnings in browser
- [x] Code reviewed (or self-reviewed against CONTRIBUTING.md guidelines)

---

## Appendix: File Impact Map

Every file in the project, mapped to which items touch it:

### Backend

| File | Items |
|------|-------|
| `main.py` | #6, #7, #9, #12, #20, #24, #25, #43, #44, #50 |
| `config/settings.py` | #6, #8, #11 |
| `config/models.py` | — |
| `core/run_engine.py` | #10, #11, #23, #24, #40 |
| `core/provider.py` | #8, #15, #23 |
| `core/events.py` | — |
| `core/registry.py` | — |
| `evaluation/harness.py` | #1, #23 |
| `evaluation/deterministic.py` | — |
| `evaluation/llm_judge.py` | — |
| `autopsy/analyzer.py` | #2 |
| `report/markdown.py` | #4, #5 |
| `report/pdf.py` | — |
| `tasks/*.py` | — |
| `scaffolds/*.py` | — |
| `utils/json_extract.py` | — |
| `pyproject.toml` | #3, #7, #15, #22, #23, #24 |

### Frontend

| File | Items |
|------|-------|
| `App.tsx` | #16, #17, #19, #26, #29, #35, #38, #39, #44, #47, #48, #50 |
| `components/ArenaPanel.tsx` | #40 |
| `components/ArenaGrid.tsx` | #16 |
| `components/TaskSelector.tsx` | #33, #35, #40, #42, #44 |
| `components/ScoreDashboard.tsx` | #31, #32, #41, #45, #46 |
| `components/ProofComparison.tsx` | #27, #30 |
| `components/AutopsyModal.tsx` | #28, #30 |
| `components/ReportModal.tsx` | #28, #32 |
| `components/StreamingText.tsx` | #32 |
| `hooks/useArenaRun.ts` | #17, #18, #19, #49 |
| `hooks/useSSE.ts` | #17 |
| `api/client.ts` | #6, #24, #45 |
| `types/index.ts` | #33, #42 |
| `styles/theme.css` | #47 |
| `index.html` | #36, #37 |
| `package.json` | #14, #26, #34, #41, #48 |
| `vite.config.ts` | #38 |

### New Files (to be created)

| File | Item |
|------|------|
| `backend/core/auth.py` | #6 |
| `backend/core/budget.py` | #8 |
| `backend/core/storage.py` | #24 |
| `backend/core/cache.py` | #40 |
| `backend/core/stats.py` | #50 |
| `backend/config/logging.py` | #23 |
| `backend/tasks/custom.py` | #43 |
| `backend/tests/` (8 files) | #13 |
| `backend/Dockerfile` | #21 |
| `frontend/src/components/ErrorBoundary.tsx` | #16 |
| `frontend/src/components/PanelErrorBoundary.tsx` | #16 |
| `frontend/src/components/Toast.tsx` | #26 |
| `frontend/src/components/Skeleton.tsx` | #30 |
| `frontend/src/components/KeyboardShortcutHelp.tsx` | #29 |
| `frontend/src/components/AdvancedSettings.tsx` | #42 |
| `frontend/src/components/CustomTaskForm.tsx` | #43 |
| `frontend/src/components/RunHistory.tsx` | #39 |
| `frontend/src/components/OutputDiff.tsx` | #41 |
| `frontend/src/components/Leaderboard.tsx` | #50 |
| `frontend/src/components/GuidedTour.tsx` | #48 |
| `frontend/src/hooks/useKeyboardShortcuts.ts` | #29 |
| `frontend/src/hooks/usePersistedState.ts` | #35 |
| `frontend/src/hooks/useTheme.ts` | #47 |
| `frontend/src/utils/clipboard.ts` | #32 |
| `frontend/src/utils/export.ts` | #46 |
| `frontend/src/utils/notifications.ts` | #49 |
| `frontend/vitest.config.ts` | #14 |
| `frontend/Dockerfile` | #21 |
| `frontend/nginx.conf` | #21 |
| `docker-compose.yml` | #21 |
| `.github/workflows/ci.yml` | #22 |
| `.github/workflows/docker.yml` | #22 |

---

*This plan is a living document. Items may be re-prioritized as implementation reveals new dependencies or as user testing surfaces unexpected issues.*
