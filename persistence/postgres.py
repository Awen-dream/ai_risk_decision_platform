from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Sequence

from services.observability import (
    add_gauge,
    increment_counter,
    observe_histogram,
    set_gauge,
)


class PostgresDriverUnavailable(RuntimeError):
    """Raised when the optional PostgreSQL driver is not installed."""


class PostgresDatabase:
    """Small PostgreSQL transaction and schema migration helper."""

    def __init__(
        self,
        dsn: str,
        *,
        connect_factory: Callable[[str, bool], Any] | None = None,
    ) -> None:
        if not dsn:
            raise ValueError("PostgreSQL DSN is required")
        self.dsn = dsn
        self._connect_factory = connect_factory

    def migrate(self, version: int, name: str, statements: Sequence[str]) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            existing = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = %s",
                (version,),
            ).fetchone()
            if existing is not None:
                return
            for statement in statements:
                connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations(version, name) VALUES (%s, %s)",
                (version, name),
            )

    @contextmanager
    def connection(self) -> Iterator[Any]:
        connection = self._connect(autocommit=True)
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        started_at = time.perf_counter()
        increment_counter("database.postgres.transactions.started")
        add_gauge("database.postgres.transactions.active", 1.0)
        connection = None
        try:
            connection = self._connect(autocommit=False)
            yield connection
            connection.commit()
            increment_counter("database.postgres.transactions.completed")
            set_gauge("database.postgres.ready", 1.0)
        except Exception:
            if connection is not None:
                connection.rollback()
            increment_counter("database.postgres.transactions.failed")
            set_gauge("database.postgres.ready", 0.0)
            raise
        finally:
            if connection is not None:
                connection.close()
            add_gauge("database.postgres.transactions.active", -1.0)
            observe_histogram(
                "database.postgres.transaction.duration_seconds",
                time.perf_counter() - started_at,
            )

    def is_ready(self) -> bool:
        try:
            with self.connection() as connection:
                row = connection.execute("SELECT 1 AS ready").fetchone()
                ready = _row_value(row, "ready", 0) == 1
                set_gauge("database.postgres.ready", 1.0 if ready else 0.0)
                return ready
        except Exception:
            set_gauge("database.postgres.ready", 0.0)
            return False

    def _connect(self, *, autocommit: bool) -> Any:
        if self._connect_factory is not None:
            return self._connect_factory(self.dsn, autocommit)
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise PostgresDriverUnavailable(
                "Install psycopg to use AI_RISK_*_STORE_BACKEND=postgres"
            ) from exc
        return psycopg.connect(
            self.dsn,
            autocommit=autocommit,
            row_factory=dict_row,
        )


def _row_value(row: Any, key: str, index: int) -> Any:
    if isinstance(row, dict):
        return row[key]
    return row[index]
