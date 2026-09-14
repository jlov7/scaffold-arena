from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from adapters_v1.transport import AdapterTransportLimits, EventChannel
from protocol_v1.canonical import sha256
from protocol_v1.models import TraceEvent


def _event(sequence: int) -> TraceEvent:
    payload = {"sequence": sequence}
    return TraceEvent(
        trace_id="trace-one",
        episode_id="episode-one",
        attempt_id="attempt-one",
        sequence=sequence,
        actor="harness",
        event_type="state",
        timestamp=datetime(2026, 8, 17, tzinfo=UTC),
        monotonic_time=float(sequence),
        payload=payload,
        payload_hash=sha256(payload),
    )


def test_pending_event_limit_must_not_exceed_total_event_limit() -> None:
    with pytest.raises(ValidationError, match="pending event limit"):
        AdapterTransportLimits(max_events=2, max_pending_events=3)


@pytest.mark.asyncio
async def test_claimed_slow_consumer_applies_ordered_backpressure() -> None:
    channel = EventChannel(max_pending_events=1)
    iterator = channel.iterate()

    first_read = asyncio.create_task(anext(iterator))
    await channel.emit(_event(0))
    assert (await first_read).sequence == 0

    await channel.emit(_event(1))
    blocked = asyncio.create_task(channel.emit(_event(2)))
    await asyncio.sleep(0)
    assert blocked.done() is False
    assert [item.sequence for item in channel.events] == [0, 1]

    assert (await anext(iterator)).sequence == 1
    await asyncio.wait_for(blocked, timeout=1)
    assert (await anext(iterator)).sequence == 2
    await channel.close()
    with pytest.raises(StopAsyncIteration):
        await anext(iterator)


@pytest.mark.asyncio
async def test_post_hoc_stream_retains_all_events_without_backpressure_deadlock() -> None:
    channel = EventChannel(max_pending_events=1)
    for sequence in range(4):
        await asyncio.wait_for(channel.emit(_event(sequence)), timeout=1)
    await channel.close()

    observed = [item.sequence async for item in channel.iterate()]
    assert observed == [0, 1, 2, 3]
    assert [item.sequence for item in channel.events] == observed


@pytest.mark.asyncio
async def test_close_wakes_blocked_producer_without_committing_its_event() -> None:
    channel = EventChannel(max_pending_events=1)
    iterator = channel.iterate()

    first_read = asyncio.create_task(anext(iterator))
    await channel.emit(_event(0))
    assert (await first_read).sequence == 0
    await channel.emit(_event(1))

    blocked = asyncio.create_task(channel.emit(_event(2)))
    await asyncio.sleep(0)
    assert blocked.done() is False

    await channel.close()
    with pytest.raises(RuntimeError, match="closed"):
        await blocked
    assert [item.sequence for item in channel.events] == [0, 1]
    assert (await anext(iterator)).sequence == 1
    with pytest.raises(StopAsyncIteration):
        await anext(iterator)


@pytest.mark.asyncio
async def test_event_stream_can_be_claimed_only_once() -> None:
    channel = EventChannel(max_pending_events=1)
    await channel.close()
    assert [item async for item in channel.iterate()] == []
    with pytest.raises(RuntimeError, match="only once"):
        assert [item async for item in channel.iterate()] == []
