# State Taxonomy Playbook

This playbook defines canonical UI states and required behavior contracts.

## Canonical State Set

1. `loading`
2. `empty`
3. `partial`
4. `error`
5. `blocked`
6. `success`

Implementation source:

- `frontend/src/features/states/taxonomy.ts`
- `frontend/src/components/StateCallout.tsx`

## State Behavior Contracts

| State | Definition | Required UX behavior |
| --- | --- | --- |
| `loading` | A run is actively processing | Show progress context, suppress premature decision actions |
| `empty` | No result set is loaded | Provide deterministic next action (run or load history) |
| `partial` | New run is active while older results remain | Warn users against final conclusions until completion |
| `error` | Latest operation failed | Show cause-aware remediation and retry path |
| `blocked` | Preconditions unmet (token/connectivity/etc.) | Prioritize recovery actions and safe fallback path |
| `success` | Results are ready for analysis | Prioritize review, comparison, autopsy, and export |

## Recovery Rules

- Every `error` and `blocked` state must include an explicit next action.
- Recovery actions must be deterministic and context-aware:
  - Auth -> settings/token path.
  - Rate limit -> wait/retry guidance.
  - Validation -> input/schema correction.
  - Server/network -> retry and fallback instructions.
- Safe fallback mode must remain visible until explicitly exited.

## Telemetry Requirements

The following events are mandatory for recovery analytics:

- `onboarding_blocker_detected`
- `onboarding_blocker_resolved`
- `fallback_mode_enabled`
- `fallback_mode_disabled`

These power failure-to-recovery KPIs in the telemetry dashboard.
