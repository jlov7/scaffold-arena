# Protocol-v1 route map

The Protocol-v1 Workbench owns `/` and `/workbench/*`. Unknown Workbench paths recover to Compare and preserve only durable selections supplied in the URL.

| Route | Purpose |
| --- | --- |
| `/` | Compare decision surface. |
| `/workbench/studies` | Select or import a StudyPack. |
| `/workbench/design` | Create or recover an experiment specification. |
| `/workbench/preflight` | Freeze and inspect execution readiness. |
| `/workbench/execute` | Create, recover, cancel, or resume durable executions. |
| `/workbench/analyze` | Inspect immutable analysis and exports. |
| `/workbench/xray`, `/workbench/observatory`, `/workbench/counterfactual`, `/workbench/forge`, `/workbench/trace-lab` | Open optional diagnostic or planning surfaces. |
| `/workbench/review`, `/workbench/evidence`, `/workbench/settings` | Inspect review, custody, and settings records. |

The legacy `/arena`, `/results`, `/history`, `/leaderboard`, and `/settings` routes remain separate compatibility routes. They do not establish Protocol-v1 execution or evidence state.

Navigation may record consent-gated local events such as `route_changed`, `route_timing`, and `nav_confusion_signal`. These are implementation signals, not user-outcome evidence.
