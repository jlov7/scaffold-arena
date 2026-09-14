# Workbench semantic landmark map

This note describes the Protocol-v1 Workbench shell. It is a source-oriented accessibility reference, not an accessibility certification.

## Shared Workbench landmarks

- A skip link targets `#workbench-main`.
- Command and mobile bars identify the Workbench controls and current status.
- Primary and mobile navigation use the `Workbench areas` label.
- `main#workbench-main` contains the active stage and receives programmatic focus.
- The evidence inspector is an aside with an accessible label.
- The mobile evidence panel uses a modal dialog with keyboard focus handling.

## Surface expectation

Every Workbench area presents a stage heading and a mode control. Guided mode keeps durable identifiers and raw objects out of the default surface; Lab exposes the same persisted context for technical inspection. A surface may show a HOLD, partial state, or unknown value without inferring a successful execution.

Dialog behavior and assistive-technology compatibility require revision-specific automated and human evidence. See the [accessibility verification note](../reviews/accessibility-audit-v1.md).
