# Troubleshooting Decision Tree and Support Runbook

Use this as the first response guide for users and support engineers.

## User-Facing Decision Tree

1. Can you start a run?
2. If no:
   - Are you offline?
     - Yes: reconnect and retry from Arena.
     - No: continue.
   - Do you have a valid API key in Settings?
     - No: open Settings and configure token.
     - Yes: continue.
   - Is the connection retrying/stuck?
     - Yes: wait for retry; if still stalled, use Retry action.
     - No: continue.
   - Did the run fail with missing required fields?
     - Yes: open help playbook, tighten extraction instructions, rerun.
3. If still blocked, enable safe fallback mode and continue with history/results while fixing root cause.

## Common Blockers Runbook

| Blocker class | User symptom | First action | Escalation action |
| --- | --- | --- | --- |
| `auth_missing` | Run blocked before start | Configure API key in Settings | Verify provider key format and environment loading |
| `offline` | “cannot start run while offline” | Restore network and retry | Validate browser/network policy constraints |
| `retrying` | Connection banner remains retrying | Wait one cycle, then retry | Check backend SSE health and logs |
| `schema_invalid` | Output rejected by evaluator | Tighten prompt schema instructions | Run autopsy and apply suggested patch |
| `rate_limited` | 429 or quota failures | Retry with delay | Switch to cheaper model or reduce token limits |
| `server_error` | 5xx failures | Retry once | Escalate backend incident and activate fallback mode |

## Support Escalation Standard

1. Capture blocker type, run id, task id, and timestamp.
2. Confirm whether user can continue in safe fallback mode.
3. Provide one deterministic next action within 2 minutes.
4. If unresolved after two attempts, escalate with reproduction steps and logs.

## Exit Criteria

- User completes run or safely continues in fallback mode.
- Root-cause category assigned.
- Recovery action documented for future playbook updates.
