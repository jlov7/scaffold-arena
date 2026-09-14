# Trace Lab semantic alignment

Trace Lab compares two already-persisted protocol-v1 attempt traces from the same project and frozen experiment. It is a diagnostic instrument. It does not execute either harness, reconstruct missing events, score an outcome, or establish why one attempt succeeded or failed.

## Admission boundary

A complete comparison requires both attempts to:

- exist in the selected project;
- belong to the same persisted experiment;
- be distinct attempts;
- have a completed attempt status;
- carry an explicit `trace_complete: true` capture marker;
- contain unique, contiguous protocol event sequences;
- contain no more than **1,024 persisted trace events per attempt**.

The 1,024-event limit is applied before normalization or quadratic sequence alignment. Larger traces receive a typed `trace_too_large` HOLD rather than consuming unbounded memory or CPU. Gapped, reordered, or completeness-unverified traces require explicit diagnostic partial mode and remain visibly excluded from complete-trace conclusions.

## What is aligned

Every persisted event contributes only evidence-safe alignment metadata:

- durable event ID;
- semantic anchor;
- normalized ordinal;
- relative monotonic or wall-clock time;
- persisted payload SHA-256 digest;
- optional state-evidence reference.

Raw payloads are not returned by the alignment response. Declared semantic-anchor overrides may reference only durable event IDs already present in one of the source traces.

The service produces a source digest over the two durable trace identities and any declared anchor overrides. Each individual source digest binds persisted event IDs and protocol metadata while excluding raw payload bytes; the payload digest remains part of that identity.

## Alignment algorithm

Trace Lab uses deterministic weighted global sequence alignment:

1. Semantic anchors must match for a diagonal alignment.
2. Same-anchor events with equal observation digests receive the strongest score.
3. Same-anchor events without complete digest evidence may align as anchor-only observations.
4. Same-anchor events with different digests are retained as an explicit `CONTENT_DIFFERENCE` rather than being presented as equal.
5. Inserted or missing events become `LEFT_ONLY` or `RIGHT_ONLY` rows.
6. Deterministic tie-breaking makes equivalent inputs reproduce the same row sequence.

The score calculation keeps two numeric rows in memory. A one-byte traceback cell is retained for each event pair so the exact alignment can be reconstructed within the admitted bound.

The public row statuses are:

| Status | Meaning |
| --- | --- |
| `MATCH` | The semantic anchors align and no observed content difference is established. When both digests are present, equal digests mean the recorded payload bytes were identical. |
| `CONTENT_DIFFERENCE` | The same semantic anchor was observed on both sides, but the persisted payload digests differ. |
| `LEFT_ONLY` | An observed left-trace event has no aligned right-trace event. |
| `RIGHT_ONLY` | An observed right-trace event has no aligned left-trace event. |

## First meaningful divergence

The first meaningful divergence is derived from the aligned row sequence, not from equal numeric ordinals. This prevents one inserted event from shifting every later comparison and prevents repeated anchors from pairing only by their first positional occurrence.

Unmatched `START` and `REQUEST` scaffolding rows are ignored as headline divergences. A content difference at the same request anchor remains meaningful because the persisted observation itself differs.

For one-sided divergences, Trace Lab may include the nearest observed evidence reference on the absent side. This supplies bilateral inspection context; it does not assert that the contextual event was aligned to, caused, or counterfactually replaced the one-sided event.

## Claim boundary

Every normal Trace Lab response is labelled:

```text
DIAGNOSTIC_ONLY
```

The following conclusions are **not** supported by alignment alone:

- an event was correct;
- two equal hashes imply semantic correctness;
- a differing hash explains an outcome;
- a left-only or right-only event caused success or failure;
- missing state or events can be reconstructed;
- clock-normalized order proves real-time causality;
- a harness mechanism has a causal effect.

Hashes establish the identity of observed bytes. State references establish the identity of observed state evidence. Neither establishes truth, relevance, independence, or cause.

The lower-level helper retains the compatibility parameter for a declared
comparison-invariant flag, but no derived persisted cross-arm invariants check
exists in v1. Therefore that caller flag cannot promote any divergence, and
the helper as well as the persistence-backed Trace Lab API emit only
`DIAGNOSTIC_ONLY` until such evidence exists.

## API response

`POST /api/v1/trace-analyses` returns additive v1.1 fields under `alignment`:

```json
{
  "source_digest": "...",
  "source_digests": {"left": "...", "right": "..."},
  "matched_anchors": 3,
  "exact_observation_matches": 2,
  "content_differences": 1,
  "left_only": 0,
  "right_only": 0,
  "clock_skew_tolerant": true,
  "rows": [
    {
      "position": 0,
      "status": "MATCH",
      "anchor": "request",
      "left": {
        "event_id": "...",
        "ordinal": 0,
        "observation_digest": "...",
        "relative_ms": 0,
        "evidence_ref": null
      },
      "right": {
        "event_id": "...",
        "ordinal": 0,
        "observation_digest": "...",
        "relative_ms": 0,
        "evidence_ref": null
      }
    }
  ]
}
```

Existing request fields and summary counts are preserved. `first_meaningful_divergence.alignment_position` points to the returned row rather than forcing clients to infer a position from attempt-local ordinals.
