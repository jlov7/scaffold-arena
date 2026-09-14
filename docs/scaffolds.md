# Scaffold mechanisms

This guide describes four implemented legacy scaffold mechanisms. It does not rank them or claim that one improves model output. No comparative live study is recorded; see [evidence status](evidence-status.md) for the current claim boundary.

A scaffold is orchestration around a model call. The legacy run API accepts a task, model, and one or more scaffold IDs. It validates the selection before starting a run, then exposes run events through a GET-only event stream. The mechanisms below can change the prompts, number of calls, validation steps, and failure modes. Whether those changes improve a defined outcome is a testable hypothesis, not a result in this repository.

## Implemented mechanisms

| ID | Mechanism | Source behavior |
| --- | --- | --- |
| `bare` | Single prompt | Streams one task prompt and returns the assembled output. |
| `plan_execute_verify` | Plan, execute, verify | Requests a plan, streams an answer using that plan and the task schema, then requests a JSON-only verification pass. |
| `tool_error_recovery` | Draft and schema repair | Streams a draft, parses it with the shared JSON extractor, validates it against the task schema, and may stream one repair. |
| `memory_critique` | Decompose, synthesize, critique, refine | Requests a decomposition, solves the returned subtasks, streams a synthesis, requests a critique, then streams a refinement. |

The implementation may stop early when a run is cancelled. The recovery mechanism defaults to at most one repair; its configured limit can change that behavior. The decomposition mechanism uses model-generated subtasks, so its number of provider calls can vary. None of these implementation details predicts quality, cost, or latency for a particular model or task.

## What each mechanism is intended to test

- A single prompt provides a simple comparison condition.
- A planning and verification sequence tests whether explicit intermediate instructions alter schema-bound output.
- A parser and schema-validation path tests whether a specific formatting error can be identified and repaired.
- Decomposition and critique test whether additional intermediate context and a review pass alter a multi-part response.

These are proposed mechanisms. A valid comparison needs a frozen task family, model or runtime identity, evaluation contract, budget, controls, and retained evidence. It must also preserve the required deterministic evaluation weight. The [benchmark card](benchmarking/benchmark_card.md) and [reproducibility guide](benchmarking/reproducibility.md) define the broader protocol boundary.

## Reading a run

The legacy scaffolds emit phase changes, streamed output fragments, provider usage, and a final output. Usage and cost are evidence fields, not estimates in this guide: pricing is derived from the versioned model catalog in `backend/config/models.py`, and unavailable usage remains unavailable. Inspect a run record, its evaluation, and its trace or report before drawing a conclusion.

## Maintaining a mechanism

The source implementations are in `backend/scaffolds/`; their shared interface is `backend/scaffolds/base.py`. Registration is initialized by the backend runtime and run requests are validated against that registry. Changes to a mechanism require matching tests and the repository gate. Documentation alone does not establish that a changed mechanism is effective.
