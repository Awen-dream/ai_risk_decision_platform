from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Sequence

from services.observability import (
    add_gauge,
    increment_counter,
    observe_histogram,
    set_gauge,
)


class SQLiteDatabase:
    """Small SQLite transaction and schema migration helper."""

    def __init__(self, path: Path, *, busy_timeout_ms: int = 5000) -> None:
        self.path = path
        self._busy_timeout_ms = busy_timeout_ms
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def migrate(self, version: int, name: str, statements: Sequence[str]) -> None:
        with self.transaction() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            existing = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = ?",
                (version,),
            ).fetchone()
            if existing is not None:
                return
            for statement in statements:
                connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations(version, name) VALUES (?, ?)",
                (version, name),
            )

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            self.path,
            timeout=self._busy_timeout_ms / 1000,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout = {self._busy_timeout_ms}")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        started_at = time.perf_counter()
        increment_counter("database.sqlite.transactions.started")
        add_gauge("database.sqlite.transactions.active", 1.0)
        try:
            with self.connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    yield connection
                except Exception:
                    connection.rollback()
                    raise
                else:
                    connection.commit()
            increment_counter("database.sqlite.transactions.completed")
            set_gauge("database.sqlite.ready", 1.0)
        except sqlite3.Error:
            increment_counter("database.sqlite.transactions.failed")
            set_gauge("database.sqlite.ready", 0.0)
            raise
        except Exception:
            increment_counter("database.sqlite.transactions.failed")
            raise
        finally:
            add_gauge("database.sqlite.transactions.active", -1.0)
            observe_histogram(
                "database.sqlite.transaction.duration_seconds",
                time.perf_counter() - started_at,
            )

    def is_ready(self) -> bool:
        try:
            with self.connection() as connection:
                ready = connection.execute("SELECT 1").fetchone()[0] == 1
                set_gauge("database.sqlite.ready", 1.0 if ready else 0.0)
                return ready
        except sqlite3.Error:
            set_gauge("database.sqlite.ready", 0.0)
            return False
