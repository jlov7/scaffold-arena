# Durable blind review

`POST /api/v1/annotation-batches` creates a project-scoped, immutable blind-assignment batch from durable evaluated attempts. Scores, raw outputs, artifact digests, and caller-supplied blind payloads are rejected at creation.

- Every item names an existing attempt. The service rechecks project-owned input, output, trace, immutable evaluation, result artifact, evaluator identity, and grader plan before writing a deterministic blinded payload.
- Assignments use distinct pseudonyms whose identities remain explicitly unverified.
- A batch carries a versioned, SHA-256-bound data-only rubric. Dimension IDs must exactly match the frozen qualitative grader bindings.
- Annotation submissions record immutable scores for every dimension. Exact replays are safe; missing, extra, or changed scores conflict.
- Adjudication is admitted only after complete per-dimension disagreement and requires the bound blinded artifact.
- Assignment views never expose treatment, harness, factor, scaffold, adapter, score, or control-plane identifiers.
- Status is derived from durable rows: `PENDING`, `IN_REVIEW`, `NEEDS_ADJUDICATION`, or `COMPLETE`.

The claim ceiling is durable review custody and later-analysis readiness. The service does not self-assert human calibration, reviewer identity, or independent validation.
