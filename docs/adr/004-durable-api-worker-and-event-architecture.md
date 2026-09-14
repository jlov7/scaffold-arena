# ADR 004: Keep run submission, execution, and event observation separate

- Status: Accepted
- Date: 2026-08-14
- Decision owner: Scaffold Arena maintainers

## Context

An arena run can outlive the initiating browser request, emits progress from
multiple scaffolds, and must remain inspectable after streaming reconnects.
Mixing run creation with a long-lived stream makes cancellation, retry, and
history recovery ambiguous.

## Decision

The durable architecture is:

1. `POST /api/runs` validates and creates a durable run identity.
2. A background worker executes the selected scaffolds and writes terminal
   results plus an ordered event record.
3. `GET /api/runs/{id}/events` is the GET-only SSE observation channel.
4. `GET /api/runs/{id}` and diagnostics/export endpoints recover durable state
   after stream loss; cancellation is an explicit command endpoint.

Run events are append-only operational evidence, not score truth by
themselves. The versioned event taxonomy owns event names and required fields.
Workers may fan out scaffold work, but final scores, provider usage, and
terminal status must be persisted against the same run identity.

## Consequences

- SSE remains GET-only; clients never use POST as a streaming channel.
- API request handlers do not become the sole owner of long-running execution.
- A queue, database, or worker replacement must preserve run identity,
  cancellation semantics, event ordering, and recovery endpoints.

## Alternatives rejected

- A single POST response stream: poor reconnect and cancellation semantics.
- Browser-only execution state: cannot provide durable history or audits.
