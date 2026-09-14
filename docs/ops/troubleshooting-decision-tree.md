# Workbench troubleshooting guide

Use this guide for a visible Workbench failure or HOLD. Do not invent missing provider, runtime, cost, or provenance information.

1. Confirm the selected StudyPack, experiment, and execution context.
2. If preflight is HOLD, read the listed capability, manipulation, budget, isolation, or adequacy requirement and correct that requirement before requesting execution.
3. If an execution is partial, recover its persisted history and event stream. A partial record is not a completed result.
4. If a request fails, retain the displayed error and retry only when the operation is idempotent or the interface presents a recovery action.
5. If an adapter or runtime is unavailable, treat it as unavailable. Configure it through the approved local or team deployment path; do not substitute another provider or fabricate a receipt.
6. If analysis or evidence is unavailable, return to the selected execution and confirm the required frozen and persisted records exist.

For escalation, record the revision, route, selected durable identifiers when available, timestamp, visible error or HOLD reason, and safe reproduction steps. Do not include credentials, private inputs, restricted artifacts, or raw sensitive payloads. The exit condition is a verified recovery or a truthful HOLD, not merely a retry.
