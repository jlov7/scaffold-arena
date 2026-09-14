# Decision-first Workbench

The Workbench is organized around four user jobs:

| Job | Primary question | Surface |
| --- | --- | --- |
| Compare | What study and frozen comparison should be evaluated next? | Study Canvas and Run Cockpit |
| Diagnose | What persisted evidence should be inspected before changing a harness? | Harness Home / X-Ray and Trace / Counterfactual Lab |
| Improve | What bounded proposal is worth planning next? | Arena Forge |
| Prove | What does the available evidence actually support? | Evidence Room and Decision Canvas |

The underlying protocol remains `Study → Design → Preflight → Execute → Analyze → Trace → Review → Evidence`. The decision canvas reveals that path as context, but keeps one primary decision and its next lawful action on screen.

## Guided and Lab

Guided and Lab are views over the same persisted selection, frozen protocol objects, API operations, event stream, analysis, trace, and evidence records. Guided does not construct an alternate browser-only protocol object.

Guided is deliberately constrained:

- it discovers selected durable studies, comparisons, runs, attempts, reports, and receipts automatically;
- it shows cost and adequacy previews before a consequential action;
- it renders HOLD with a cause, consequence, and remediation;
- it withholds raw durable IDs, digests, canonical JSON, and manual provenance construction; and
- it keeps execution on HOLD when no persisted capture integration has supplied immutable provenance.

Lab exposes the full object-level route: durable IDs, events, digests, frozen design and analysis configuration, trace diagnostics, evidence details, and export actions. Lab input is still validated against the same API contract. It does not weaken preflight, custody, reservation, or evidence gates.

## Evidence and accessibility boundary

No result surface is complete without its evidence ceiling and a verification or reproduction action. Unknown cost, usage, or adequacy is displayed as unknown, never as zero or a PASS.

The shell supplies keyboard navigation, focus restoration, screen-reader labels, non-colour status text and icons, reduced-motion styling, responsive table containment, and chart/table alternatives. Optional X-Ray, Observatory, Counterfactual, Forge, and Trace Lab surfaces are deferred and asserted outside the Workbench first-load closure by `frontend/scripts/check-budgets.mjs`. The current aggregate emitted-JavaScript cap is 610,000 bytes; a recorded candidate build measured 609,190 bytes. The Workbench first-load ceiling is unchanged.

The local test and build gates validate product behavior only. They do not establish a usability study, assistive-technology certification, live-provider behavior, production readiness, security assurance, causal validity, or independent reproduction.
