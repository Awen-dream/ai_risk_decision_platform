from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.session_store import InMemorySessionStore
from services.case_service import InMemoryCaseService
from validation.postgres_smoke import (
    resolve_postgres_dsn,
    run_postgres_smoke,
)


class PostgresSmokeTests(unittest.TestCase):
    def test_resolve_postgres_dsn_prefers_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            dsn_path = Path(tmp_dir) / "postgres-dsn"
            dsn_path.write_text("postgresql://risk:secret@db/risk\n", encoding="utf-8")

            dsn = resolve_postgres_dsn(
                dsn="postgresql://wrong",
                dsn_file=str(dsn_path),
            )

        self.assertEqual(dsn, "postgresql://risk:secret@db/risk")

    def test_postgres_smoke_runs_store_contract(self) -> None:
        session_store = InMemorySessionStore()
        case_service = InMemoryCaseService()

        report = run_postgres_smoke(
            "postgresql://risk:secret@db/risk",
            database_ready=lambda dsn: True,
            session_store_factory=lambda dsn: session_store,
            case_service_factory=lambda dsn: case_service,
        )

        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["summary"]["passed"], 4)
        self.assertEqual(
            [check["name"] for check in report["checks"]],
            [
                "postgres.dsn_configured",
                "postgres.database_ready",
                "postgres.session_store",
                "postgres.case_service",
            ],
        )

    def test_postgres_smoke_fails_when_database_not_ready(self) -> None:
        report = run_postgres_smoke(
            "postgresql://risk:secret@db/risk",
            database_ready=lambda dsn: False,
            session_store_factory=lambda dsn: InMemorySessionStore(),
            case_service_factory=lambda dsn: InMemoryCaseService(),
        )

        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["checks"][1]["name"], "postgres.database_ready")
        self.assertEqual(report["checks"][1]["status"], "failed")


if __name__ == "__main__":
    unittest.main()
