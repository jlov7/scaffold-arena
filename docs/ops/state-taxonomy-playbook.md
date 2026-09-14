# Workbench state taxonomy

This playbook defines the states the Workbench must explain without inferring an outcome.

| State | Meaning | Required behavior |
| --- | --- | --- |
| `loading` | A persisted record or route context is being recovered. | Show what is loading and avoid a premature conclusion. |
| `empty` | No relevant durable record is selected. | Explain the next selection or creation action. |
| `partial` | Evidence or execution history is incomplete. | Preserve the missing state and offer only lawful recovery actions. |
| `HOLD` or `blocked` | A declared precondition is not satisfied. | State the cause, consequence, and remediation. |
| `error` | A request or validation operation failed. | State the observable failure and a safe retry or correction. |
| `completed` | A durable operation reached a terminal completed state. | Direct the reader to analysis and its evidence ceiling. |

Unknown usage, cost, adequacy, or provenance remains unknown; it is never displayed as zero, a PASS, or a successful provider action. Guided mode must not require manually entered durable identifiers or provenance objects when the system can recover persisted context.

The source and revision-specific tests define the implementation. The local telemetry tracker may record recovery interactions with consent; it is not evidence of user outcomes or a durable analytics service.
