#!/usr/bin/env python3
"""Bounded analytical and opt-in materialized checks for persistence-v1 scale.

The default path never creates a row per attempt or event.  It checks the
arithmetic and the actual SQLAlchemy metadata/query plans used by the durable
event and lease paths.  ``--materialize PATH`` is an explicit, manual SQLite
exercise of the same logical projection and batches every insert.
"""

import argparse
import hashlib
import importlib
import json
import math
import sqlite3
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

REPORT_PATH = ROOT / "outputs" / "scale_validation.json"
REPORT_VERSION = "scale-validation.v1"
INT32_MAX = 2_147_483_647
DEFAULT_ATTEMPTS = 50_000
DEFAULT_TRACE_EVENTS = 10_000_000
DEFAULT_BATCH_SIZE = 1_000


class ScaleValidationError(ValueError):
    """Raised when a scale declaration is unsafe or internally inconsistent."""


@dataclass(frozen=True)
class ScaleConfig:
    attempts: int = DEFAULT_ATTEMPTS
    trace_events: int = DEFAULT_TRACE_EVENTS
    batch_size: int = DEFAULT_BATCH_SIZE
    execution_count: int = 1


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ScaleValidationError(f"{name} must be a positive integer")
    return value


def validate_config(config: ScaleConfig) -> ScaleConfig:
    """Validate a declared scale without allocating a row-sized collection."""
    if not isinstance(config, ScaleConfig):
        raise ScaleValidationError("config must be a ScaleConfig")
    attempts = _positive_int(config.attempts, "attempts")
    events = _positive_int(config.trace_events, "trace_events")
    batch_size = _positive_int(config.batch_size, "batch_size")
    executions = _positive_int(config.execution_count, "execution_count")
    if executions != 1:
        raise ScaleValidationError("this bounded harness currently models one execution")
    if events < attempts:
        raise ScaleValidationError("trace_events must be at least attempts")
    if events % attempts:
        raise ScaleValidationError(
            "trace_events must divide evenly across attempts for this harness"
        )
    if events > INT32_MAX:
        raise ScaleValidationError("trace_events exceeds the positive SQL INTEGER cursor range")
    if attempts > INT32_MAX:
        raise ScaleValidationError("attempts exceeds the positive SQL INTEGER range")
    return ScaleConfig(attempts, events, batch_size, executions)


def ceil_div(numerator: int, denominator: int) -> int:
    _positive_int(numerator, "numerator")
    _positive_int(denominator, "denominator")
    return (numerator + denominator - 1) // denominator


def event_coordinates(config: ScaleConfig, event_number: int) -> tuple[int, int]:
    """Map a 1-based event number to a 0-based attempt and 1-based sequence."""
    config = validate_config(config)
    if isinstance(event_number, bool) or not isinstance(event_number, int):
        raise ScaleValidationError("event_number must be an integer")
    if not 1 <= event_number <= config.trace_events:
        raise ScaleValidationError("event_number is outside the declared event range")
    per_attempt = config.trace_events // config.attempts
    zero_based = event_number - 1
    return zero_based // per_attempt, zero_based % per_attempt + 1


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _index_contract() -> dict[str, tuple[str, ...]]:
    schema = importlib.import_module("persistence_v1.schema")
    indexes = {
        index.name: tuple(column.name for column in index.columns)
        for table in schema.metadata.tables.values()
        for index in table.indexes
    }
    expected = {
        "ix_attempt_events_attempt_sequence": ("attempt_id", "sequence"),
        "ix_attempt_events_execution_sequence": ("execution_id", "execution_sequence"),
        "ix_jobs_status_available": ("status", "available_at"),
    }
    missing = sorted(name for name in expected if name not in indexes)
    mismatched = {
        name: {"expected": expected[name], "actual": indexes.get(name)}
        for name in expected
        if indexes.get(name) != expected[name]
    }
    if missing or mismatched:
        raise ScaleValidationError(
            f"persistence-v1 index contract mismatch: missing={missing}, mismatched={mismatched}"
        )
    return expected


def _plan_details() -> dict[str, Any]:
    """Run cheap SQLite EXPLAIN checks against the actual v1 metadata indexes."""
    from sqlalchemy import create_engine
    from persistence_v1.schema import attempt_events, jobs, metadata

    engine = create_engine("sqlite:///:memory:", future=True)
    # Only materialize the two tables whose plans are checked.  The complete
    # metadata also contains unrelated dialect-specific trigger DDL; including
    # it here would make a local SQLite planner check depend on other tables.
    metadata.create_all(engine, tables=[attempt_events, jobs])
    queries = {
        "attempt_event_pagination": (
            "SELECT * FROM attempt_events "
            "WHERE attempt_id = ? AND sequence > ? ORDER BY sequence LIMIT ?",
            ("attempt-00000000", 0, 100),
            "ix_attempt_events_attempt_sequence",
        ),
        "execution_event_pagination": (
            "SELECT * FROM attempt_events "
            "WHERE execution_id = ? AND execution_sequence > ? "
            "ORDER BY execution_sequence LIMIT ?",
            ("execution-00000000", 0, 100),
            "ix_attempt_events_execution_sequence",
        ),
        "lease_filter": (
            "SELECT * FROM jobs WHERE status = ? AND "
            "(available_at IS NULL OR available_at <= ?) "
            "ORDER BY created_at, id LIMIT 1",
            ("queued", "2026-01-01T00:00:00+00:00"),
            "ix_jobs_status_available",
        ),
    }
    result: dict[str, Any] = {}
    try:
        with engine.connect() as connection:
            for name, (sql, params, expected_index) in queries.items():
                rows = connection.exec_driver_sql(
                    "EXPLAIN QUERY PLAN " + sql, params
                ).fetchall()
                details = [str(row[-1]) for row in rows]
                joined = " ".join(details)
                uses_index = expected_index in joined
                if not uses_index:
                    raise ScaleValidationError(
                        f"{name} does not use expected index {expected_index}: {details}"
                    )
                result[name] = {
                    "expected_index": expected_index,
                    "uses_expected_index": True,
                    "details": details,
                    "order_by_covered": not any("TEMP B-TREE" in detail for detail in details),
                }
    finally:
        engine.dispose()
    # The current lease index deliberately covers readiness filtering only.
    # created_at/id ordering is an observable plan caveat, not a hidden claim.
    result["lease_filter"]["claim"] = (
        "status/available_at filtering is indexed; created_at,id ordering is "
        "not covered by the v1 index and may require a sort"
    )
    return result


def _storage_estimate(config: ScaleConfig) -> dict[str, Any]:
    # Conservative arithmetic estimates, not measurements of a configured
    # SQLite/Postgres page layout.  Keep each assumption visible in the report.
    assumptions = {
        "attempt_row_bytes": 732,
        "event_row_bytes": 560,
        "event_index_bytes_each": 88,
        "cursor_row_bytes": 100,
        "event_index_count": 2,
        "execution_count": config.execution_count,
        "payload_bytes_included_per_row": {"attempt_request": 256, "attempt_result": 256, "event": 256},
        "caveat": (
            "Planning estimate only: excludes DB pages, WAL, vacuum/fillfactor, "
            "TOAST/JSON encoding, foreign-key indexes, jobs, backups, and provider artifacts."
        ),
    }
    attempts_bytes = config.attempts * assumptions["attempt_row_bytes"]
    event_bytes = config.trace_events * (
        assumptions["event_row_bytes"]
        + assumptions["event_index_count"] * assumptions["event_index_bytes_each"]
    )
    cursor_bytes = config.execution_count * assumptions["cursor_row_bytes"]
    total = attempts_bytes + event_bytes + cursor_bytes
    return {
        "assumptions": assumptions,
        "attempt_table_bytes": attempts_bytes,
        "event_table_and_indexes_bytes": event_bytes,
        "cursor_table_bytes": cursor_bytes,
        "estimated_total_bytes": total,
        "estimated_total_gib": round(total / (1024**3), 6),
    }


def validate_scale(config: ScaleConfig = ScaleConfig()) -> dict[str, Any]:
    """Return a deterministic report for the declared logical scale."""
    config = validate_config(config)
    per_attempt = config.trace_events // config.attempts
    attempt_batches = ceil_div(config.attempts, config.batch_size)
    event_batches = ceil_div(config.trace_events, config.batch_size)
    boundary_events = [1, per_attempt, per_attempt + 1, config.trace_events - 1, config.trace_events]
    coordinates = [
        {
            "event_number": number,
            "attempt_ordinal": event_coordinates(config, number)[0],
            "sequence": event_coordinates(config, number)[1],
        }
        for number in boundary_events
    ]
    expected_indexes = _index_contract()
    plans = _plan_details()
    return {
        "report_version": REPORT_VERSION,
        "mode": "analytical",
        "claim_ceiling": "capacity model/schema validation only; not production load evidence",
        "declared_scale": asdict(config),
        "batching": {
            "attempt_batches": attempt_batches,
            "event_batches": event_batches,
            "max_rows_per_batch": config.batch_size,
            "events_per_attempt": per_attempt,
            "materialization_is_batched": True,
        },
        "cursor": {
            "type": "positive SQL INTEGER-compatible sequence",
            "minimum_cursor": 0,
            "maximum_event_sequence": config.trace_events,
            "maximum_supported_positive_integer": INT32_MAX,
            "range_valid": config.trace_events <= INT32_MAX,
            "cursor_contract": "nonnegative integer; reads use strict sequence > cursor",
        },
        "id_uniqueness": {
            "strategy": "deterministic namespace plus zero-based ordinal; primary key IDs and paired unique keys",
            "attempt_key": "attempt-{attempt_ordinal:08d}",
            "event_key": "event-{event_number:010d}",
            "sampled_boundaries": coordinates,
            "proof": (
                "ordinal-to-key mapping is injective over the declared finite integer "
                "interval; event coordinates are unique pairs"
            ),
            "unique_constraints": [
                "attempts.id",
                "attempt_events(attempt_id, sequence)",
                "attempt_events(execution_id, execution_sequence)",
            ],
        },
        "event_ordering": {
            "per_attempt_sequences": [1, per_attempt],
            "execution_sequences": [1, config.trace_events],
            "strictly_monotonic": True,
            "no_gap_arithmetic": True,
            "ordering_key": "execution_sequence (or sequence within an attempt)",
        },
        "index_contract": {
            "expected": {name: list(columns) for name, columns in expected_indexes.items()},
            "all_present_and_column_ordered": True,
        },
        "query_plans": plans,
        "storage_estimate": _storage_estimate(config),
        "resource_contract": {
            "default_mode_allocates_all_rows": False,
            "default_mode_provider_calls": 0,
            "default_mode_process_storm": False,
            "target_max_seconds": 10,
            "target_max_rss_mb": 300,
        },
        "source_sha256": {"backend/persistence_v1/schema.py": _sha256(BACKEND / "persistence_v1/schema.py")},
        "materialization": {
            "available": True,
            "requires_explicit_path": True,
            "default": False,
            "claim_ceiling": "optional local SQLite projection exercise; not production load evidence",
        },
    }


def _materialize(config: ScaleConfig, destination: Path) -> dict[str, int | str]:
    """Materialize the relevant projection in bounded insert batches."""
    config = validate_config(config)
    destination = destination.expanduser().resolve()
    if destination.exists():
        if destination.is_dir() or destination.stat().st_size:
            raise ScaleValidationError("materialize path must be a new or empty file")
    if not destination.parent.exists():
        raise ScaleValidationError("materialize parent directory must already exist")
    connection = sqlite3.connect(destination)
    try:
        connection.executescript(
            """CREATE TABLE attempts (id TEXT PRIMARY KEY, episode_id TEXT NOT NULL, ordinal INTEGER NOT NULL);
            CREATE TABLE attempt_events (
                id TEXT PRIMARY KEY, attempt_id TEXT NOT NULL, execution_id TEXT NOT NULL,
                sequence INTEGER NOT NULL, execution_sequence INTEGER NOT NULL,
                UNIQUE (attempt_id, sequence), UNIQUE (execution_id, execution_sequence)
            );
            CREATE TABLE execution_event_cursors (execution_id TEXT PRIMARY KEY, last_sequence INTEGER NOT NULL);
            CREATE INDEX ix_attempt_events_attempt_sequence ON attempt_events(attempt_id, sequence);
            CREATE INDEX ix_attempt_events_execution_sequence ON attempt_events(execution_id, execution_sequence);
            """
        )
        for start in range(0, config.attempts, config.batch_size):
            stop = min(start + config.batch_size, config.attempts)
            connection.executemany(
                "INSERT INTO attempts VALUES (?, ?, ?)",
                [(f"attempt-{ordinal:08d}", "episode-00000000", ordinal) for ordinal in range(start, stop)],
            )
            connection.commit()
        per_attempt = config.trace_events // config.attempts
        event_batch: list[tuple[str, str, str, int, int]] = []
        for event_number in range(1, config.trace_events + 1):
            attempt_ordinal, sequence = event_coordinates(config, event_number)
            event_batch.append(
                (
                    f"event-{event_number:010d}",
                    f"attempt-{attempt_ordinal:08d}",
                    "execution-00000000",
                    sequence,
                    event_number,
                )
            )
            if len(event_batch) == config.batch_size or event_number == config.trace_events:
                connection.executemany("INSERT INTO attempt_events VALUES (?, ?, ?, ?, ?)", event_batch)
                connection.commit()
                event_batch.clear()
        connection.execute(
            "INSERT INTO execution_event_cursors VALUES (?, ?)",
            ("execution-00000000", config.trace_events),
        )
        connection.commit()
        attempts_count = int(connection.execute("SELECT COUNT(*) FROM attempts").fetchone()[0])
        events_count = int(connection.execute("SELECT COUNT(*) FROM attempt_events").fetchone()[0])
        cursor = int(connection.execute("SELECT last_sequence FROM execution_event_cursors").fetchone()[0])
        if (attempts_count, events_count, cursor) != (config.attempts, config.trace_events, config.trace_events):
            raise ScaleValidationError("materialized counts or cursor do not match declaration")
        return {
            "path": str(destination),
            "attempt_rows": attempts_count,
            "event_rows": events_count,
            "last_cursor": cursor,
        }
    finally:
        connection.close()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _write_report(report: dict[str, Any]) -> None:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(_canonical_json(report), encoding="utf-8")


def _check_report(report: dict[str, Any]) -> int:
    if not REPORT_PATH.exists():
        print(f"[scale] FAIL: missing {REPORT_PATH.relative_to(ROOT)}", file=sys.stderr)
        return 1
    try:
        actual = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[scale] FAIL: unreadable report: {exc}", file=sys.stderr)
        return 1
    if actual != report:
        print(f"[scale] FAIL: stale {REPORT_PATH.relative_to(ROOT)}; run --write", file=sys.stderr)
        return 1
    print(
        f"[scale] PASS: {report['declared_scale']['attempts']:,} attempts / "
        f"{report['declared_scale']['trace_events']:,} events analytical report is fresh"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="check outputs/scale_validation.json freshness")
    parser.add_argument("--write", action="store_true", help="write the deterministic analytical report")
    parser.add_argument(
        "--materialize",
        metavar="PATH",
        help="explicit new/empty SQLite path for a manual batched exercise",
    )
    parser.add_argument("--attempts", type=int, default=DEFAULT_ATTEMPTS)
    parser.add_argument("--trace-events", type=int, default=DEFAULT_TRACE_EVENTS)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    args = parser.parse_args(argv)
    if args.check and args.write:
        parser.error("--check and --write are mutually exclusive")
    if args.check and args.materialize:
        parser.error("--check cannot be combined with --materialize")
    config = ScaleConfig(args.attempts, args.trace_events, args.batch_size)
    try:
        report = validate_scale(config)
        if args.materialize:
            summary = _materialize(config, Path(args.materialize))
            print(
                f"[scale] materialized {summary['event_rows']:,} events in batches of "
                f"{config.batch_size:,} at {summary['path']}"
            )
        if args.write:
            _write_report(report)
            print(f"[scale] wrote {REPORT_PATH.relative_to(ROOT)}")
        if args.check:
            return _check_report(report)
        if not args.write and not args.materialize:
            print(f"[scale] PASS: analytical {config.attempts:,} attempts / {config.trace_events:,} events")
        return 0
    except (ScaleValidationError, OSError, ImportError, sqlite3.Error) as exc:
        print(f"[scale] FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
