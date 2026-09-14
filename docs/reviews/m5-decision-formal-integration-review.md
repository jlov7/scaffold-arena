# M5 engineering verification note

**Evidence date:** 2026-09-14
**Revision boundary:** working tree `bc40b5b9e4d82e74164188d0f44ac3c69ede9863`

The recorded full release gate for this tree included the lifecycle, invocation, reservation, PostgreSQL-parity, frontend, accessibility, visual, and performance lanes. The relevant design boundaries are documented in the [decision-first Workbench guide](../guides/decision-first-workbench.md) and the [invocation and reservation lifecycle model](../architecture/invocation-reservation-lifecycle-model.md).

The deterministic checks exercise the implemented lifecycle contract, including terminal admission, request identity, reservation transitions, cancellation, and unknown-usage handling. They are regression evidence for the checked source, not a record of production incidents or a claim about provider behavior.

This note supports only revision-bounded local engineering verification. It does not establish production security, complete fault tolerance, provider behavior, causal effect, benchmark validity, accessibility certification, general usability, or independent assurance. Re-run the repository gate on the exact candidate before relying on this note.
