# Live adapter event backpressure

Scaffold Arena bounds two different event resources for command and HTTP RPC adapters:

- `max_events` limits the **total retained trace evidence** accepted from one attempt;
- `max_pending_events` limits the **live undelivered backlog** after a consumer claims the event stream.

The defaults are:

```text
max_events = 10,000
max_pending_events = 256
```

`max_pending_events` must be between 1 and 65,536 and may not exceed `max_events`. When a caller lowers `max_events` without specifying a pending limit, the pending default is lowered to the same value when necessary.

## Delivery model

`EventChannel` retains every accepted event in order. It never drops, samples, or coalesces trace evidence.

Before a consumer claims `stream_events`, producers may complete and retain the total bounded trace. This preserves execute-then-read and post-hoc adapter integrations: execution does not deadlock merely because no live consumer has attached.

After the single consumer claims the stream:

1. each delivered event advances the consumed cursor;
2. a producer may remain ahead by at most `max_pending_events` events;
3. further emission waits on an `asyncio.Condition` until the consumer advances or the channel closes;
4. close and cancellation wake all blocked producers and the consumer;
5. an event waiting when the channel closes is rejected rather than appended after closure.

The retained event list remains independently protected by parser-level `max_events`. Backpressure therefore removes the second unbounded `asyncio.Queue` backlog without weakening complete trace retention.

## Cancellation and cleanup

Command timeout, process termination, HTTP response closure, task cancellation, transport-limit failure, and explicit adapter cancellation all close the channel. Close is idempotent.

A blocked producer wakes and receives a closed-channel error. A consumer may drain events already committed before observing end-of-stream. Per-attempt event channels are removed during adapter cleanup.

## Claim boundary

Backpressure establishes bounded memory behavior for the in-process delivery path. It does not prove that an external subprocess or remote server stopped producing data after cancellation, nor does it establish completeness beyond the adapter's captured and validated event stream.
