from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from core.models import AgentRequest, AgentResponse
from core.session_store import PostgresSessionStore, SessionStore
from persistence.postgres import PostgresDatabase
from services.case_service import CaseService, PostgresCaseService


@dataclass
class PostgresSmokeCheck:
    name: str
    status: str
    detail: str
    duration_ms: float


class PostgresSmokeRunner:
    def __init__(self) -> None:
        self.checks: list[PostgresSmokeCheck] = []

    def check(self, name: str, operation: Callable[[], str]) -> None:
        started_at = time.perf_counter()
        try:
            detail = operation()
        except Exception as exc:
            self.checks.append(
                PostgresSmokeCheck(
                    name=name,
                    status="failed",
                    detail=f"{type(exc).__name__}: {exc}",
                    duration_ms=(time.perf_counter() - started_at) * 1000,
                )
            )
            return
        self.checks.append(
            PostgresSmokeCheck(
                name=name,
                status="passed",
                detail=detail,
                duration_ms=(time.perf_counter() - started_at) * 1000,
            )
        )

    def report(self) -> dict[str, Any]:
        passed = sum(check.status == "passed" for check in self.checks)
        failed = len(self.checks) - passed
        return {
            "status": "passed" if failed == 0 else "failed",
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "summary": {
                "total": len(self.checks),
                "passed": passed,
                "failed": failed,
            },
            "checks": [asdict(check) for check in self.checks],
        }


def resolve_postgres_dsn(*, dsn: str = "", dsn_file: str = "") -> str:
    if dsn_file:
        return Path(dsn_file).read_text(encoding="utf-8").strip()
    return dsn or os.getenv("AI_RISK_POSTGRES_DSN", "")


def run_postgres_smoke(
    dsn: str,
    *,
    database_ready: Callable[[str], bool] | None = None,
    session_store_factory: Callable[[str], SessionStore] | None = None,
    case_service_factory: Callable[[str], CaseService] | None = None,
) -> dict[str, Any]:
    runner = PostgresSmokeRunner()
    session_holder: dict[str, Any] = {}
    database_ready = database_ready or (lambda value: PostgresDatabase(value).is_ready())
    session_store_factory = session_store_factory or (lambda value: PostgresSessionStore(value))
    case_service_factory = case_service_factory or (lambda value: PostgresCaseService(value))

    runner.check("postgres.dsn_configured", lambda: _validate_dsn(dsn))
    runner.check("postgres.database_ready", lambda: _validate_database_ready(dsn, database_ready))

    def session_check() -> str:
        session_store = session_store_factory(dsn)
        session = session_store.create_session()
        request = AgentRequest(
            query="PostgreSQL smoke investigation",
            context={"country": "BR", "channel": "credit_card"},
        )
        response = AgentResponse(
            agent_name="investigation",
            summary="PostgreSQL smoke test completed",
            intent="metric_anomaly",
            confidence=0.91,
            suggested_actions=["Keep monitoring the metric"],
        )
        updated = session_store.append_turn(session.session_id, request, response)
        fetched = session_store.get_session(session.session_id)
        if fetched is None:
            raise AssertionError("created session could not be fetched")
        if len(fetched.turns) != 1:
            raise AssertionError(f"expected 1 persisted turn, got {len(fetched.turns)}")
        if updated.session_id != fetched.session_id:
            raise AssertionError("append_turn returned a different session")
        session_holder["session"] = fetched
        return f"session_id={fetched.session_id} turns={len(fetched.turns)}"

    def case_check() -> str:
        session = session_holder.get("session")
        if session is None:
            raise AssertionError("session smoke check did not produce a session")
        case_service = case_service_factory(dsn)
        case = case_service.create_case_from_session(session, turn_index=1)
        duplicate = case_service.create_case_from_session(session, turn_index=1)
        if duplicate.case_id != case.case_id:
            raise AssertionError("case creation is not idempotent for a session turn")
        updated = case_service.update_case_status(
            case.case_id,
            "in_review",
            "PostgreSQL smoke status update",
        )
        if updated is None or updated.status != "in_review":
            raise AssertionError("case status update did not persist")
        listed = case_service.list_cases(session_id=session.session_id, limit=10)
        if not any(item.case_id == case.case_id for item in listed):
            raise AssertionError("case list did not include the smoke case")
        total = case_service.count_cases(session_id=session.session_id)
        if total < 1:
            raise AssertionError("case count did not include the smoke case")
        return f"case_id={case.case_id} status={updated.status} session_cases={total}"

    runner.check("postgres.session_store", session_check)
    runner.check("postgres.case_service", case_check)
    return runner.report()


def _validate_dsn(dsn: str) -> str:
    if not dsn:
        raise AssertionError("PostgreSQL DSN is not configured")
    return "PostgreSQL DSN is configured"


def _validate_database_ready(
    dsn: str,
    database_ready: Callable[[str], bool],
) -> str:
    if not database_ready(dsn):
        raise AssertionError("PostgreSQL database is not ready")
    return "PostgreSQL database responded to readiness probe"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run PostgreSQL persistence smoke checks.")
    parser.add_argument("--dsn", default=os.getenv("AI_RISK_POSTGRES_DSN", ""))
    parser.add_argument("--dsn-file", default=os.getenv("AI_RISK_POSTGRES_DSN_FILE", ""))
    parser.add_argument("--skip-if-unconfigured", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args(argv)

    dsn = resolve_postgres_dsn(dsn=args.dsn, dsn_file=args.dsn_file)
    if not dsn and args.skip_if_unconfigured:
        report = {
            "status": "skipped",
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "summary": {"total": 0, "passed": 0, "failed": 0},
            "checks": [],
        }
    else:
        report = run_postgres_smoke(dsn)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["status"] in {"passed", "skipped"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
