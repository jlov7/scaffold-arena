# ADR 006: Separate local workbench readiness from team deployment

- Status: Accepted
- Date: 2026-08-14
- Decision owner: Scaffold Arena maintainers

## Context

The current workbench has documented local startup, configuration, CORS,
security, and release checks. Those artifacts do not establish a shared-team
identity model, hosted secret management, tenancy, operational monitoring, or
an independently reproduced deployment.

## Decision

Local-workbench validation does not transfer to team deployment. Named
environment configuration, server-side credential ownership, access control,
audit retention, backup/recovery, monitoring, and an external reproduction
packet each require their own evidence before advancement.

Team authentication is a fail-closed PostgreSQL-only boundary: OIDC
Authorization Code + PKCE, browser-bound transaction state, server-side opaque
sessions, project memberships, and durable audit records. Personal mode
remains a no-login local workbench with its personal/local authority ceiling.
This does not establish retention, backup/recovery, monitoring, external
validation, or team deployment readiness; those require their own evidence.

Local provider tokens may be configured for a session, but they are not team
credential management. Local CORS, rate limiting, and API-token controls are
defence-in-depth evidence, not a multi-tenant authorization claim.

## Consequences

- Local setup can be documented and validated without representing it as a
  hosted service.
- Team deployment work cannot inherit `VALIDATED` from the local workbench.
- Deployment claims require environment-specific evidence and all applicable gates.

## Alternatives rejected

- Describing localhost setup as team deployment: it hides ownership and
  operational gaps.
- Adding a generic deployment label without per-control evidence: it prevents
  targeted verification.
