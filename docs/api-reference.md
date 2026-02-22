# API Reference

> Complete endpoint documentation for the Scaffold Arena backend.

**Base URL:** `http://localhost:8000`

---

## Health Check

### `GET /api/health`

Verify the backend is running.

**Response:**

```json
{
    "status": "ok"
}
```

---

## Application Metadata

### `GET /api/meta`

Returns available models, tasks, scaffolds, and feature flags. The frontend calls this once on load to populate the UI.
Model entries include a `provider` field (`anthropic`, `openai`, `gemini`, or `openrouter`).

**Response:**

```json
{
    "models": [
        {
            "id": "claude-sonnet-4-6",
            "label": "Claude Sonnet 4.6",
            "provider": "anthropic",
            "input_usd_per_mtok": 3.0,
            "output_usd_per_mtok": 15.0
        },
        {
            "id": "claude-haiku-4-5",
            "label": "Claude Haiku 4.5",
            "provider": "anthropic",
            "input_usd_per_mtok": 1.0,
            "output_usd_per_mtok": 5.0
        },
        {
            "id": "gpt-4.1-mini",
            "label": "GPT-4.1 mini",
            "provider": "openai",
            "input_usd_per_mtok": 0.4,
            "output_usd_per_mtok": 1.6
        },
        {
            "id": "gemini-2.5-flash",
            "label": "Gemini 2.5 Flash",
            "provider": "gemini",
            "input_usd_per_mtok": 0.3,
            "output_usd_per_mtok": 2.5
        },
        {
            "id": "openrouter/openai/gpt-4.1-mini",
            "label": "OpenRouter • GPT-4.1 mini",
            "provider": "openrouter",
            "input_usd_per_mtok": 0.5,
            "output_usd_per_mtok": 2.0
        }
    ],
    "tasks": [
        {
            "id": "extraction",
            "name": "Structured Extraction",
            "subtitle": "Parse legal amendments into structured JSON",
            "type": "extraction",
            "synthetic_sources": false
        }
    ],
    "scaffolds": [
        {
            "id": "bare",
            "name": "Bare Prompt",
            "subtitle": "Single-shot, no scaffolding"
        }
    ],
    "features": {
        "llm_judge": true,
        "pdf_export": false
    }
}
```

---

## Arena Runs

### `POST /api/runs`

Start an arena run. Launches all specified scaffolds concurrently against the selected task.

**Request Body:**

```json
{
    "task_id": "extraction",
    "model_id": "claude-sonnet-4-6",
    "scaffold_ids": ["bare", "plan_execute_verify", "tool_error_recovery", "memory_critique"],
    "options": {
        "temperature": 0,
        "max_output_tokens": 2048,
        "timeout_s": 75
    }
}
```

| Field | Type | Required | Default | Description |
|-------|------|:--------:|---------|-------------|
| `task_id` | string | Yes | — | Task to run |
| `model_id` | string | No | `claude-sonnet-4-6` | Model to use |
| `scaffold_ids` | string[] | No | All 4 scaffolds | Which scaffolds to run |
| `options` | object | No | See defaults | Run options |

**Response:**

```json
{
    "run_id": "run_20250219_143022_a1b2c3d4",
    "stream_url": "/api/runs/run_20250219_143022_a1b2c3d4/events",
    "cancel_url": "/api/runs/run_20250219_143022_a1b2c3d4/cancel"
}
```

The run executes in the background. Connect to `stream_url` via EventSource to receive events.

---

### `GET /api/runs/{run_id}/events`

SSE event stream for a running arena. Connect with `EventSource` (browser native) or any SSE client.

**Connection:**

```javascript
const source = new EventSource('/api/runs/run_xxx/events')
source.addEventListener('scaffold_delta', (e) => {
    const data = JSON.parse(e.data)
    console.log(data.scaffold_id, data.delta)
})
```

**Event Types:**

#### `run_started`

Emitted once when the run begins.

```json
{
    "run_id": "run_20250219_143022_a1b2c3d4",
    "ts_ms": 1708354222000,
    "task_id": "extraction",
    "scaffold_ids": ["bare", "plan_execute_verify", "tool_error_recovery", "memory_critique"]
}
```

#### `scaffold_started`

Emitted when a scaffold begins execution.

```json
{
    "run_id": "run_xxx",
    "ts_ms": 1708354222100,
    "scaffold_id": "bare"
}
```

#### `scaffold_phase`

Emitted when a scaffold enters a new phase (planning, executing, verifying, etc.).

```json
{
    "run_id": "run_xxx",
    "ts_ms": 1708354222200,
    "scaffold_id": "plan_execute_verify",
    "phase": "planning"
}
```

#### `scaffold_delta`

Streaming text token. Emitted frequently during output generation.

```json
{
    "run_id": "run_xxx",
    "ts_ms": 1708354222300,
    "scaffold_id": "bare",
    "delta": " the amendment"
}
```

#### `scaffold_completed`

Emitted when a scaffold finishes successfully.

```json
{
    "run_id": "run_xxx",
    "ts_ms": 1708354230000,
    "scaffold_id": "bare",
    "output": "{\"amendments\": [...]}",
    "metrics": {
        "input_tokens": 1200,
        "output_tokens": 800,
        "cost_usd": 0.0156,
        "wall_time_ms": 3200,
        "num_api_calls": 1
    }
}
```

#### `scaffold_failed`

Emitted when a scaffold encounters an error.

```json
{
    "run_id": "run_xxx",
    "ts_ms": 1708354230000,
    "scaffold_id": "bare",
    "error": "Provider API error: rate limited"
}
```

#### `evaluation_completed`

Emitted after a scaffold's output is scored.

```json
{
    "run_id": "run_xxx",
    "ts_ms": 1708354231000,
    "scaffold_id": "bare",
    "total_score": 41.2,
    "breakdown": {
        "schema_validity": 60.0,
        "field_accuracy": 25.0
    },
    "weights": {
        "schema_validity": {"weight": 0.45, "type": "deterministic"},
        "field_accuracy": {"weight": 0.30, "type": "deterministic"},
        "completeness": {"weight": 0.15, "type": "judge"},
        "reasoning_clarity": {"weight": 0.10, "type": "judge"}
    },
    "notes": ["Missing field: effective_date", "Invalid type for: parties"],
    "judge": null
}
```

#### `run_complete`

Emitted once when all scaffolds have finished. This is the final event — the SSE connection closes after this.

```json
{
    "run_id": "run_xxx",
    "ts_ms": 1708354240000,
    "winner_scaffold_id": "memory_critique",
    "results": {
        "bare": {
            "output": "...",
            "metrics": { "..." },
            "evaluation": { "..." }
        },
        "memory_critique": {
            "output": "...",
            "metrics": { "..." },
            "evaluation": { "..." }
        }
    }
}
```

#### `heartbeat`

Keep-alive event sent every 15 seconds during inactivity.

```json
{
    "run_id": "run_xxx",
    "ts_ms": 1708354255000
}
```

---

### `POST /api/runs/{run_id}/cancel`

Cancel a running arena. Scaffolds stop at their next cancellation checkpoint.

**Response:**

```json
{
    "status": "cancelled"
}
```

---

## Proof Comparison

### `POST /api/comparisons`

Run the 3-case proof comparison: cheap+winning, expensive+bare, expensive+winning.

**Request Body:**

```json
{
    "task_id": "extraction",
    "expensive_model_id": "claude-sonnet-4-6",
    "cheap_model_id": "claude-haiku-4-5",
    "winning_scaffold_id": "memory_critique",
    "control_scaffold_id": "bare",
    "options": null
}
```

| Field | Type | Required | Default | Description |
|-------|------|:--------:|---------|-------------|
| `task_id` | string | Yes | — | Task to run |
| `expensive_model_id` | string | No | `claude-sonnet-4-6` | The "expensive" model |
| `cheap_model_id` | string | No | `claude-haiku-4-5` | The "cheap" model |
| `winning_scaffold_id` | string | Yes | — | Best scaffold from the arena |
| `control_scaffold_id` | string | No | `bare` | Baseline scaffold |

**Response:**

```json
{
    "run_id": "cmp_20250219_143500_e5f6g7h8",
    "stream_url": "/api/runs/cmp_20250219_143500_e5f6g7h8/events"
}
```

**SSE Events:** Uses comparison-specific events (`comparison_started`, `case_started`, `case_completed`, `case_evaluation_completed`, `comparison_complete`) on the same EventSource endpoint.

---

## Autopsy

### `POST /api/autopsy`

Analyze why a scaffold scored poorly. Returns classified failures with evidence and a machine-applicable patch.

**Request Body:**

```json
{
    "task_id": "extraction",
    "scaffold_id": "bare",
    "output": "{\"amendments\": [...]}",
    "evaluation": {
        "total_score": 41.2,
        "breakdown": {"schema_validity": 60.0, "field_accuracy": 25.0},
        "notes": ["Missing field: effective_date"]
    },
    "metrics": {
        "input_tokens": 1200,
        "output_tokens": 800,
        "cost_usd": 0.0156,
        "wall_time_ms": 3200,
        "num_api_calls": 1
    }
}
```

**Response:**

```json
{
    "failures": [
        {
            "type": "missing_field",
            "description": "The 'effective_date' field is required but was not extracted",
            "severity": "critical",
            "evidence": "Schema requires 'effective_date' (string, date format). Output JSON has no such key."
        },
        {
            "type": "incorrect_type",
            "description": "The 'parties' field should be an array but was returned as a string",
            "severity": "major",
            "evidence": "Expected array of party objects, got: \"Acme Corp and Beta Inc\""
        }
    ],
    "patch": {
        "system_prompt_append": "CRITICAL: You MUST include the effective_date field...",
        "output_schema_enforcement": true
    },
    "summary": "2 failures found: 1 critical (missing required field), 1 major (incorrect type). Patch adds explicit field requirements to system prompt."
}
```

---

## Patch & Rerun

### `POST /api/patch-reruns`

Rerun a single scaffold with a configuration patch applied.

**Request Body:**

```json
{
    "task_id": "extraction",
    "model_id": "claude-sonnet-4-6",
    "scaffold_id": "bare",
    "base_config": {},
    "patch": {
        "system_prompt_append": "CRITICAL: You MUST include the effective_date field...",
        "output_schema_enforcement": true
    }
}
```

**Response:**

```json
{
    "run_id": "pr_20250219_144000_i9j0k1l2",
    "stream_url": "/api/runs/pr_20250219_144000_i9j0k1l2/events"
}
```

Uses the same SSE event stream as arena runs (connect to `stream_url`).

---

## Reports

### `POST /api/reports`

Generate a comprehensive audit report in Markdown (and optionally PDF).

**Request Body:**

```json
{
    "task_id": "extraction",
    "model_id": "claude-sonnet-4-6",
    "results": {
        "bare": { "metrics": {}, "evaluation": {} },
        "memory_critique": { "metrics": {}, "evaluation": {} }
    },
    "comparison": { "...": "comparison results" },
    "autopsy": { "...": "autopsy results" },
    "patch_rerun": { "...": "patch rerun results" }
}
```

| Field | Type | Required | Description |
|-------|------|:--------:|-------------|
| `task_id` | string | Yes | Task that was run |
| `model_id` | string | Yes | Model that was used |
| `results` | object | Yes | Arena results (all scaffolds) |
| `comparison` | object | No | Proof comparison results |
| `autopsy` | object | No | Autopsy findings |
| `patch_rerun` | object | No | Patch rerun results |

**Response:**

```json
{
    "markdown": "# Scaffold Arena Report\n\n## Arena Results\n...",
    "pdf_base64": null
}
```

`pdf_base64` is `null` when PDF export is disabled or weasyprint is not installed. When available, it contains the base64-encoded PDF bytes.

---

## Error Handling

All endpoints return standard HTTP error codes:

| Code | Meaning |
|:----:|---------|
| `200` | Success |
| `404` | Run not found |
| `422` | Validation error (invalid request body) |
| `500` | Internal server error |

Error responses follow this format:

```json
{
    "detail": "Run not found"
}
```

---

## CORS

The backend accepts requests from origins listed in the `CORS_ORIGINS` environment variable (comma-separated). Default: `http://localhost:5173`.

## Rate Limits

Scaffold Arena respects provider API rate limits. The `MAX_CONCURRENT_LLM_CALLS` setting (default: 3) controls how many simultaneous API calls can be in flight. If you hit provider rate limits, reduce this value.
