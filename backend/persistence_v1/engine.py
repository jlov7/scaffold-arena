from __future__ import annotations

from pathlib import Path

from sqlalchemy import Engine, create_engine, event


def create_persistence_engine(database_url: str, *, worker_concurrency: int = 1) -> Engine:
    """Build a Core engine. SQLite is intentionally single-worker for v1."""
    if database_url.startswith("sqlite") and worker_concurrency > 1:
        raise ValueError("SQLite persistence_v1 requires worker_concurrency <= 1; use Postgres for workers")
    if database_url.startswith("sqlite:///") and database_url != "sqlite:///:memory:":
        Path(database_url.removeprefix("sqlite:///")) .parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(database_url, future=True, pool_pre_ping=not database_url.startswith("sqlite"))
    if database_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()
    return engine
