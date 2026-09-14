"""Cursor-based durable event reads for a GET-only SSE transport."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select

from persistence_v1 import ArenaRepository
from persistence_v1.schema import attempt_events, attempts


@dataclass(frozen=True)
class EventReadResult:
    events: tuple[Mapping[str, Any], ...]
    next_cursor: int
    reset: bool
    retention_floor: int
    snapshot: Mapping[str, Any] | None


class DurableEventReader:
    def __init__(self, repository: ArenaRepository):
        self.repository = repository

    def read(self, attempt_id: str, *, after_sequence: int = 0, retention_floor: int | None = None) -> EventReadResult:
        if after_sequence < 0:
            raise ValueError("after_sequence cannot be negative")
        with self.repository.engine.connect() as conn:
            observed_floor = conn.execute(select(func.min(attempt_events.c.sequence)).where(attempt_events.c.attempt_id == attempt_id)).scalar_one_or_none()
            floor = max(int(observed_floor or 1), int(retention_floor or 1))
            reset = after_sequence < floor - 1
            cursor = floor - 1 if reset else after_sequence
            rows = conn.execute(select(attempt_events).where(
                attempt_events.c.attempt_id == attempt_id, attempt_events.c.sequence > cursor,
            ).order_by(attempt_events.c.sequence)).mappings().all()
            attempt = conn.execute(select(attempts).where(attempts.c.id == attempt_id)).mappings().first()
        events = tuple(dict(row) for row in rows)
        next_cursor = int(events[-1]["sequence"]) if events else cursor
        snapshot = dict(attempt) if reset and attempt is not None else None
        return EventReadResult(events, next_cursor, reset, floor, snapshot)
