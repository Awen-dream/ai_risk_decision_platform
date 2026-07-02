from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from core.models import (
    RiskActionPlanRecord,
    RiskDecisionRecord,
    SessionRecord,
    StrategyRecommendationRecord,
    WorkflowCase,
    WorkflowCaseHandoffDeliveryEntry,
    WorkflowCaseHistoryEntry,
    WorkflowCaseOperationEntry,
)
from persistence.postgres import PostgresDatabase
from persistence.sqlite import SQLiteDatabase
from services.evidence import build_session_turn_evidence_panel
from services.presentation import build_severity, build_turn_title


ALLOWED_CASE_STATUSES = {"open", "in_review", "strategy_pending", "closed"}


class CaseService(ABC):
    @abstractmethod
    def create_case_from_session(
        self,
        session: SessionRecord,
        turn_index: int | None = None,
    ) -> WorkflowCase:
        """Create a workflow case from one session turn."""

    @abstractmethod
    def get_case(self, case_id: str) -> WorkflowCase | None:
        """Return one case by id if present."""

    @abstractmethod
    def list_cases(
        self,
        *,
        status: str | None = None,
        source_agent: str | None = None,
        intent: str | None = None,
        session_id: str | None = None,
        severity: str | None = None,
        action_queue: str | None = None,
        action_status: str | None = None,
        assigned_to: str | None = None,
        action_overdue: bool | None = None,
        updated_after: str | None = None,
        updated_before: str | None = None,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
        limit: int | None = None,
        offset: int = 0,
    ) -> list[WorkflowCase]:
        """List cases with optional filters."""

    @abstractmethod
    def count_cases(
        self,
        *,
        status: str | None = None,
        source_agent: str | None = None,
        intent: str | None = None,
        session_id: str | None = None,
        severity: str | None = None,
        action_queue: str | None = None,
        action_status: str | None = None,
        assigned_to: str | None = None,
        action_overdue: bool | None = None,
        updated_after: str | None = None,
        updated_before: str | None = None,
    ) -> int:
        """Return the number of cases that match the filters."""

    @abstractmethod
    def update_case_status(
        self,
        case_id: str,
        status: str,
        note: str | None = None,
        assigned_to: str | None = None,
        action_outcome: str | None = None,
    ) -> WorkflowCase | None:
        """Update case status and append history."""

    @abstractmethod
    def append_case_note(
        self,
        case_id: str,
        note: str,
        *,
        assigned_to: str | None = None,
    ) -> WorkflowCase | None:
        """Append an operational note without changing the case status."""

    @abstractmethod
    def publish_case_handoff(
        self,
        case_id: str,
        *,
        destination_type: str,
        destination_key: str,
        note: str | None = None,
    ) -> WorkflowCase | None:
        """Record that a case handoff package has been published."""

    @abstractmethod
    def record_case_handoff_delivery(
        self,
        case_id: str,
        *,
        export_id: str,
        destination_type: str,
        destination_key: str,
        publisher_type: str,
        target_ref: str,
        status: str,
        summary: str,
        created_at: str,
        published_at: str | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WorkflowCase | None:
        """Append a handoff delivery ledger entry to the case."""


class InMemoryCaseService(CaseService):
    """Stores workflow cases in memory for lightweight review and follow-up."""

    def __init__(self) -> None:
        self._cases: dict[str, WorkflowCase] = {}

    def create_case_from_session(
        self,
        session: SessionRecord,
        turn_index: int | None = None,
    ) -> WorkflowCase:
        case = _build_case_from_session(session, turn_index=turn_index)
        existing = _find_case_for_session_turn(
            self._cases.values(),
            case.session_id,
            case.turn_index,
        )
        if existing is not None:
            return existing
        self._cases[case.case_id] = case
        return case

    def get_case(self, case_id: str) -> WorkflowCase | None:
        return self._cases.get(case_id)

    def list_cases(
        self,
        *,
        status: str | None = None,
        source_agent: str | None = None,
        intent: str | None = None,
        session_id: str | None = None,
        severity: str | None = None,
        action_queue: str | None = None,
        action_status: str | None = None,
        assigned_to: str | None = None,
        action_overdue: bool | None = None,
        updated_after: str | None = None,
        updated_before: str | None = None,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
        limit: int | None = None,
        offset: int = 0,
    ) -> list[WorkflowCase]:
        return _filter_cases(
            self._cases.values(),
            status=status,
            source_agent=source_agent,
            intent=intent,
            session_id=session_id,
            severity=severity,
            action_queue=action_queue,
            action_status=action_status,
            assigned_to=assigned_to,
            action_overdue=action_overdue,
            updated_after=updated_after,
            updated_before=updated_before,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=limit,
            offset=offset,
        )

    def count_cases(
        self,
        *,
        status: str | None = None,
        source_agent: str | None = None,
        intent: str | None = None,
        session_id: str | None = None,
        severity: str | None = None,
        action_queue: str | None = None,
        action_status: str | None = None,
        assigned_to: str | None = None,
        action_overdue: bool | None = None,
        updated_after: str | None = None,
        updated_before: str | None = None,
    ) -> int:
        return len(
            _filter_cases(
                self._cases.values(),
                status=status,
                source_agent=source_agent,
                intent=intent,
                session_id=session_id,
                severity=severity,
                action_queue=action_queue,
                action_status=action_status,
                assigned_to=assigned_to,
                action_overdue=action_overdue,
                updated_after=updated_after,
                updated_before=updated_before,
                limit=None,
                offset=0,
            )
        )

    def update_case_status(
        self,
        case_id: str,
        status: str,
        note: str | None = None,
        assigned_to: str | None = None,
        action_outcome: str | None = None,
    ) -> WorkflowCase | None:
        if status not in ALLOWED_CASE_STATUSES:
            raise ValueError(f"Unsupported case status: {status}")
        case = self._cases.get(case_id)
        if case is None:
            return None
        _append_case_status_update(
            case,
            status,
            note,
            assigned_to=assigned_to,
            action_outcome=action_outcome,
        )
        return case

    def append_case_note(
        self,
        case_id: str,
        note: str,
        *,
        assigned_to: str | None = None,
    ) -> WorkflowCase | None:
        case = self._cases.get(case_id)
        if case is None:
            return None
        _append_case_note(case, note, assigned_to=assigned_to)
        return case

    def publish_case_handoff(
        self,
        case_id: str,
        *,
        destination_type: str,
        destination_key: str,
        note: str | None = None,
    ) -> WorkflowCase | None:
        case = self._cases.get(case_id)
        if case is None:
            return None
        _append_case_handoff_publication(
            case,
            destination_type=destination_type,
            destination_key=destination_key,
            note=note,
        )
        return case

    def record_case_handoff_delivery(
        self,
        case_id: str,
        *,
        export_id: str,
        destination_type: str,
        destination_key: str,
        publisher_type: str,
        target_ref: str,
        status: str,
        summary: str,
        created_at: str,
        published_at: str | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WorkflowCase | None:
        case = self._cases.get(case_id)
        if case is None:
            return None
        _append_case_handoff_delivery(
            case,
            export_id=export_id,
            destination_type=destination_type,
            destination_key=destination_key,
            publisher_type=publisher_type,
            target_ref=target_ref,
            status=status,
            summary=summary,
            created_at=created_at,
            published_at=published_at,
            error_type=error_type,
            error_message=error_message,
            metadata=metadata,
        )
        return case


class FileCaseService(CaseService):
    """Stores workflow cases in a local JSON file for lightweight persistence."""

    def __init__(self, file_path: Path) -> None:
        self._file_path = file_path
        self._file_path.parent.mkdir(parents=True, exist_ok=True)

    def create_case_from_session(
        self,
        session: SessionRecord,
        turn_index: int | None = None,
    ) -> WorkflowCase:
        cases = self._load_cases()
        case = _build_case_from_session(session, turn_index=turn_index)
        existing = _find_case_for_session_turn(
            cases.values(),
            case.session_id,
            case.turn_index,
        )
        if existing is not None:
            return existing
        cases[case.case_id] = case
        self._save_cases(cases)
        return case

    def get_case(self, case_id: str) -> WorkflowCase | None:
        return self._load_cases().get(case_id)

    def list_cases(
        self,
        *,
        status: str | None = None,
        source_agent: str | None = None,
        intent: str | None = None,
        session_id: str | None = None,
        severity: str | None = None,
        action_queue: str | None = None,
        action_status: str | None = None,
        assigned_to: str | None = None,
        action_overdue: bool | None = None,
        updated_after: str | None = None,
        updated_before: str | None = None,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
        limit: int | None = None,
        offset: int = 0,
    ) -> list[WorkflowCase]:
        return _filter_cases(
            self._load_cases().values(),
            status=status,
            source_agent=source_agent,
            intent=intent,
            session_id=session_id,
            severity=severity,
            action_queue=action_queue,
            action_status=action_status,
            assigned_to=assigned_to,
            action_overdue=action_overdue,
            updated_after=updated_after,
            updated_before=updated_before,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=limit,
            offset=offset,
        )

    def count_cases(
        self,
        *,
        status: str | None = None,
        source_agent: str | None = None,
        intent: str | None = None,
        session_id: str | None = None,
        severity: str | None = None,
        action_queue: str | None = None,
        action_status: str | None = None,
        assigned_to: str | None = None,
        action_overdue: bool | None = None,
        updated_after: str | None = None,
        updated_before: str | None = None,
    ) -> int:
        return len(
            _filter_cases(
                self._load_cases().values(),
                status=status,
                source_agent=source_agent,
                intent=intent,
                session_id=session_id,
                severity=severity,
                action_queue=action_queue,
                action_status=action_status,
                assigned_to=assigned_to,
                action_overdue=action_overdue,
                updated_after=updated_after,
                updated_before=updated_before,
                limit=None,
                offset=0,
            )
        )

    def update_case_status(
        self,
        case_id: str,
        status: str,
        note: str | None = None,
        assigned_to: str | None = None,
        action_outcome: str | None = None,
    ) -> WorkflowCase | None:
        if status not in ALLOWED_CASE_STATUSES:
            raise ValueError(f"Unsupported case status: {status}")
        cases = self._load_cases()
        case = cases.get(case_id)
        if case is None:
            return None
        _append_case_status_update(
            case,
            status,
            note,
            assigned_to=assigned_to,
            action_outcome=action_outcome,
        )
        self._save_cases(cases)
        return case

    def append_case_note(
        self,
        case_id: str,
        note: str,
        *,
        assigned_to: str | None = None,
    ) -> WorkflowCase | None:
        cases = self._load_cases()
        case = cases.get(case_id)
        if case is None:
            return None
        _append_case_note(case, note, assigned_to=assigned_to)
        self._save_cases(cases)
        return case

    def publish_case_handoff(
        self,
        case_id: str,
        *,
        destination_type: str,
        destination_key: str,
        note: str | None = None,
    ) -> WorkflowCase | None:
        cases = self._load_cases()
        case = cases.get(case_id)
        if case is None:
            return None
        _append_case_handoff_publication(
            case,
            destination_type=destination_type,
            destination_key=destination_key,
            note=note,
        )
        self._save_cases(cases)
        return case

    def record_case_handoff_delivery(
        self,
        case_id: str,
        *,
        export_id: str,
        destination_type: str,
        destination_key: str,
        publisher_type: str,
        target_ref: str,
        status: str,
        summary: str,
        created_at: str,
        published_at: str | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WorkflowCase | None:
        cases = self._load_cases()
        case = cases.get(case_id)
        if case is None:
            return None
        _append_case_handoff_delivery(
            case,
            export_id=export_id,
            destination_type=destination_type,
            destination_key=destination_key,
            publisher_type=publisher_type,
            target_ref=target_ref,
            status=status,
            summary=summary,
            created_at=created_at,
            published_at=published_at,
            error_type=error_type,
            error_message=error_message,
            metadata=metadata,
        )
        self._save_cases(cases)
        return case

    def _load_cases(self) -> dict[str, WorkflowCase]:
        if not self._file_path.exists():
            return {}
        payload = json.loads(self._file_path.read_text(encoding="utf-8"))
        cases: dict[str, WorkflowCase] = {}
        for item in payload.get("cases", []):
            case = _deserialize_case(item)
            cases[case.case_id] = case
        return cases

    def _save_cases(self, cases: dict[str, WorkflowCase]) -> None:
        payload = {
            "cases": [_serialize_case(case) for case in cases.values()],
        }
        self._file_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


class SQLiteCaseService(CaseService):
    """Stores workflow cases transactionally with indexed SQLite queries."""

    _SORT_COLUMNS = {
        "created_at": "created_at",
        "updated_at": "updated_at",
        "status": "status",
        "severity": "severity",
    }

    def __init__(self, database_path: Path) -> None:
        self._database = SQLiteDatabase(database_path)
        self._database.migrate(
            2,
            "create_workflow_cases",
            (
                """
                CREATE TABLE workflow_cases (
                    case_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    turn_index INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    source_agent TEXT NOT NULL,
                    intent TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 0
                )
                """,
                "CREATE INDEX idx_cases_updated_at ON workflow_cases(updated_at DESC)",
                "CREATE INDEX idx_cases_created_at ON workflow_cases(created_at DESC)",
                "CREATE INDEX idx_cases_status ON workflow_cases(status)",
                "CREATE INDEX idx_cases_severity ON workflow_cases(severity)",
                "CREATE INDEX idx_cases_source_agent ON workflow_cases(source_agent)",
                "CREATE INDEX idx_cases_session_id ON workflow_cases(session_id)",
                """
                CREATE UNIQUE INDEX idx_cases_session_turn
                ON workflow_cases(session_id, turn_index)
                """,
            ),
        )

    def create_case_from_session(
        self,
        session: SessionRecord,
        turn_index: int | None = None,
    ) -> WorkflowCase:
        case = _build_case_from_session(session, turn_index=turn_index)
        with self._database.transaction() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM workflow_cases
                WHERE session_id = ? AND turn_index = ?
                """,
                (case.session_id, case.turn_index),
            ).fetchone()
            existing = _case_from_row(row)
            if existing is not None:
                return existing
            connection.execute(
                """
                INSERT INTO workflow_cases(
                    case_id, session_id, turn_index, status, severity,
                    source_agent, intent, created_at, updated_at, payload_json,
                    revision
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """,
                _case_row_values(case),
            )
        return case

    def get_case(self, case_id: str) -> WorkflowCase | None:
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT payload_json FROM workflow_cases WHERE case_id = ?",
                (case_id,),
            ).fetchone()
        return _case_from_row(row)

    def list_cases(
        self,
        *,
        status: str | None = None,
        source_agent: str | None = None,
        intent: str | None = None,
        session_id: str | None = None,
        severity: str | None = None,
        action_queue: str | None = None,
        action_status: str | None = None,
        assigned_to: str | None = None,
        action_overdue: bool | None = None,
        updated_after: str | None = None,
        updated_before: str | None = None,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
        limit: int | None = None,
        offset: int = 0,
    ) -> list[WorkflowCase]:
        where_sql, params = _build_case_where(
            status=status,
            source_agent=source_agent,
            intent=intent,
            session_id=session_id,
            severity=severity,
            updated_after=updated_after,
            updated_before=updated_before,
        )
        if _requires_action_plan_filter(
            action_queue=action_queue,
            action_status=action_status,
            assigned_to=assigned_to,
            action_overdue=action_overdue,
        ):
            with self._database.connection() as connection:
                rows = connection.execute(
                    f"SELECT payload_json FROM workflow_cases {where_sql}",
                    params,
                ).fetchall()
            return _filter_cases(
                [_case_from_row(row) for row in rows],
                action_queue=action_queue,
                action_status=action_status,
                assigned_to=assigned_to,
                action_overdue=action_overdue,
                sort_by=sort_by,
                sort_order=sort_order,
                limit=limit,
                offset=offset,
            )
        sort_column = self._SORT_COLUMNS.get(sort_by, "updated_at")
        direction = "ASC" if sort_order.lower() == "asc" else "DESC"
        pagination_sql = ""
        if limit is not None:
            pagination_sql = " LIMIT ? OFFSET ?"
            params.extend((limit, offset))
        elif offset:
            pagination_sql = " LIMIT -1 OFFSET ?"
            params.append(offset)
        with self._database.connection() as connection:
            rows = connection.execute(
                f"""
                SELECT payload_json FROM workflow_cases
                {where_sql}
                ORDER BY {sort_column} {direction}, case_id {direction}
                {pagination_sql}
                """,
                params,
            ).fetchall()
        return [_case_from_row(row) for row in rows]

    def count_cases(
        self,
        *,
        status: str | None = None,
        source_agent: str | None = None,
        intent: str | None = None,
        session_id: str | None = None,
        severity: str | None = None,
        action_queue: str | None = None,
        action_status: str | None = None,
        assigned_to: str | None = None,
        action_overdue: bool | None = None,
        updated_after: str | None = None,
        updated_before: str | None = None,
    ) -> int:
        where_sql, params = _build_case_where(
            status=status,
            source_agent=source_agent,
            intent=intent,
            session_id=session_id,
            severity=severity,
            updated_after=updated_after,
            updated_before=updated_before,
        )
        if _requires_action_plan_filter(
            action_queue=action_queue,
            action_status=action_status,
            assigned_to=assigned_to,
            action_overdue=action_overdue,
        ):
            with self._database.connection() as connection:
                rows = connection.execute(
                    f"SELECT payload_json FROM workflow_cases {where_sql}",
                    params,
                ).fetchall()
            return len(
                _filter_cases(
                    [_case_from_row(row) for row in rows],
                    action_queue=action_queue,
                    action_status=action_status,
                    assigned_to=assigned_to,
                    action_overdue=action_overdue,
                    limit=None,
                    offset=0,
                )
            )
        with self._database.connection() as connection:
            row = connection.execute(
                f"SELECT COUNT(*) AS total FROM workflow_cases {where_sql}",
                params,
            ).fetchone()
        return int(row["total"])

    def update_case_status(
        self,
        case_id: str,
        status: str,
        note: str | None = None,
        assigned_to: str | None = None,
        action_outcome: str | None = None,
    ) -> WorkflowCase | None:
        if status not in ALLOWED_CASE_STATUSES:
            raise ValueError(f"Unsupported case status: {status}")
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT payload_json FROM workflow_cases WHERE case_id = ?",
                (case_id,),
            ).fetchone()
            case = _case_from_row(row)
            if case is None:
                return None
            _append_case_status_update(
                case,
                status,
                note,
                assigned_to=assigned_to,
                action_outcome=action_outcome,
            )
            connection.execute(
                """
                UPDATE workflow_cases
                SET status = ?, updated_at = ?, payload_json = ?,
                    revision = revision + 1
                WHERE case_id = ?
                """,
                (
                    case.status,
                    case.updated_at,
                    _case_json(case),
                    case.case_id,
                ),
            )
        return case

    def append_case_note(
        self,
        case_id: str,
        note: str,
        *,
        assigned_to: str | None = None,
    ) -> WorkflowCase | None:
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT payload_json FROM workflow_cases WHERE case_id = ?",
                (case_id,),
            ).fetchone()
            case = _case_from_row(row)
            if case is None:
                return None
            _append_case_note(case, note, assigned_to=assigned_to)
            connection.execute(
                """
                UPDATE workflow_cases
                SET updated_at = ?, payload_json = ?,
                    revision = revision + 1
                WHERE case_id = ?
                """,
                (
                    case.updated_at,
                    _case_json(case),
                    case.case_id,
                ),
            )
        return case

    def publish_case_handoff(
        self,
        case_id: str,
        *,
        destination_type: str,
        destination_key: str,
        note: str | None = None,
    ) -> WorkflowCase | None:
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT payload_json FROM workflow_cases WHERE case_id = ?",
                (case_id,),
            ).fetchone()
            case = _case_from_row(row)
            if case is None:
                return None
            _append_case_handoff_publication(
                case,
                destination_type=destination_type,
                destination_key=destination_key,
                note=note,
            )
            connection.execute(
                """
                UPDATE workflow_cases
                SET updated_at = ?, payload_json = ?,
                    revision = revision + 1
                WHERE case_id = ?
                """,
                (
                    case.updated_at,
                    _case_json(case),
                    case.case_id,
                ),
            )
        return case

    def record_case_handoff_delivery(
        self,
        case_id: str,
        *,
        export_id: str,
        destination_type: str,
        destination_key: str,
        publisher_type: str,
        target_ref: str,
        status: str,
        summary: str,
        created_at: str,
        published_at: str | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WorkflowCase | None:
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT payload_json FROM workflow_cases WHERE case_id = ?",
                (case_id,),
            ).fetchone()
            case = _case_from_row(row)
            if case is None:
                return None
            _append_case_handoff_delivery(
                case,
                export_id=export_id,
                destination_type=destination_type,
                destination_key=destination_key,
                publisher_type=publisher_type,
                target_ref=target_ref,
                status=status,
                summary=summary,
                created_at=created_at,
                published_at=published_at,
                error_type=error_type,
                error_message=error_message,
                metadata=metadata,
            )
            connection.execute(
                """
                UPDATE workflow_cases
                SET updated_at = ?, payload_json = ?,
                    revision = revision + 1
                WHERE case_id = ?
                """,
                (
                    case.updated_at,
                    _case_json(case),
                    case.case_id,
                ),
            )
        return case


class PostgresCaseService(CaseService):
    """Stores workflow cases transactionally with indexed PostgreSQL queries."""

    _SORT_COLUMNS = SQLiteCaseService._SORT_COLUMNS

    def __init__(
        self,
        dsn: str,
        *,
        database: PostgresDatabase | None = None,
    ) -> None:
        self._database = database or PostgresDatabase(dsn)
        self._database.migrate(
            102,
            "create_postgres_workflow_cases",
            (
                """
                CREATE TABLE IF NOT EXISTS workflow_cases (
                    case_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    turn_index INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    source_agent TEXT NOT NULL,
                    intent TEXT,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    payload_json JSONB NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(session_id, turn_index)
                )
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_cases_updated_at
                ON workflow_cases(updated_at DESC)
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_cases_created_at
                ON workflow_cases(created_at DESC)
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_cases_status
                ON workflow_cases(status)
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_cases_severity
                ON workflow_cases(severity)
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_cases_source_agent
                ON workflow_cases(source_agent)
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_cases_session_id
                ON workflow_cases(session_id)
                """,
            ),
        )

    def create_case_from_session(
        self,
        session: SessionRecord,
        turn_index: int | None = None,
    ) -> WorkflowCase:
        case = _build_case_from_session(session, turn_index=turn_index)
        with self._database.transaction() as connection:
            row = connection.execute(
                """
                SELECT payload_json FROM workflow_cases
                WHERE session_id = %s AND turn_index = %s
                FOR UPDATE
                """,
                (case.session_id, case.turn_index),
            ).fetchone()
            existing = _case_from_row(row)
            if existing is not None:
                return existing
            connection.execute(
                """
                INSERT INTO workflow_cases(
                    case_id, session_id, turn_index, status, severity,
                    source_agent, intent, created_at, updated_at, payload_json,
                    revision
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, 0)
                """,
                _case_row_values(case),
            )
        return case

    def get_case(self, case_id: str) -> WorkflowCase | None:
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT payload_json FROM workflow_cases WHERE case_id = %s",
                (case_id,),
            ).fetchone()
        return _case_from_row(row)

    def list_cases(
        self,
        *,
        status: str | None = None,
        source_agent: str | None = None,
        intent: str | None = None,
        session_id: str | None = None,
        severity: str | None = None,
        action_queue: str | None = None,
        action_status: str | None = None,
        assigned_to: str | None = None,
        action_overdue: bool | None = None,
        updated_after: str | None = None,
        updated_before: str | None = None,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
        limit: int | None = None,
        offset: int = 0,
    ) -> list[WorkflowCase]:
        where_sql, params = _build_case_where(
            status=status,
            source_agent=source_agent,
            intent=intent,
            session_id=session_id,
            severity=severity,
            updated_after=updated_after,
            updated_before=updated_before,
            placeholder="%s",
        )
        if _requires_action_plan_filter(
            action_queue=action_queue,
            action_status=action_status,
            assigned_to=assigned_to,
            action_overdue=action_overdue,
        ):
            with self._database.connection() as connection:
                rows = connection.execute(
                    f"SELECT payload_json FROM workflow_cases {where_sql}",
                    params,
                ).fetchall()
            return _filter_cases(
                [_case_from_row(row) for row in rows],
                action_queue=action_queue,
                action_status=action_status,
                assigned_to=assigned_to,
                action_overdue=action_overdue,
                sort_by=sort_by,
                sort_order=sort_order,
                limit=limit,
                offset=offset,
            )
        sort_column = self._SORT_COLUMNS.get(sort_by, "updated_at")
        direction = "ASC" if sort_order.lower() == "asc" else "DESC"
        pagination_sql = ""
        if limit is not None:
            pagination_sql = " LIMIT %s OFFSET %s"
            params.extend((limit, offset))
        elif offset:
            pagination_sql = " OFFSET %s"
            params.append(offset)
        with self._database.connection() as connection:
            rows = connection.execute(
                f"""
                SELECT payload_json FROM workflow_cases
                {where_sql}
                ORDER BY {sort_column} {direction}, case_id {direction}
                {pagination_sql}
                """,
                params,
            ).fetchall()
        return [_case_from_row(row) for row in rows]

    def count_cases(
        self,
        *,
        status: str | None = None,
        source_agent: str | None = None,
        intent: str | None = None,
        session_id: str | None = None,
        severity: str | None = None,
        action_queue: str | None = None,
        action_status: str | None = None,
        assigned_to: str | None = None,
        action_overdue: bool | None = None,
        updated_after: str | None = None,
        updated_before: str | None = None,
    ) -> int:
        where_sql, params = _build_case_where(
            status=status,
            source_agent=source_agent,
            intent=intent,
            session_id=session_id,
            severity=severity,
            updated_after=updated_after,
            updated_before=updated_before,
            placeholder="%s",
        )
        if _requires_action_plan_filter(
            action_queue=action_queue,
            action_status=action_status,
            assigned_to=assigned_to,
            action_overdue=action_overdue,
        ):
            with self._database.connection() as connection:
                rows = connection.execute(
                    f"SELECT payload_json FROM workflow_cases {where_sql}",
                    params,
                ).fetchall()
            return len(
                _filter_cases(
                    [_case_from_row(row) for row in rows],
                    action_queue=action_queue,
                    action_status=action_status,
                    assigned_to=assigned_to,
                    action_overdue=action_overdue,
                    limit=None,
                    offset=0,
                )
            )
        with self._database.connection() as connection:
            row = connection.execute(
                f"SELECT COUNT(*) AS total FROM workflow_cases {where_sql}",
                params,
            ).fetchone()
        return int(row["total"])

    def update_case_status(
        self,
        case_id: str,
        status: str,
        note: str | None = None,
        assigned_to: str | None = None,
        action_outcome: str | None = None,
    ) -> WorkflowCase | None:
        if status not in ALLOWED_CASE_STATUSES:
            raise ValueError(f"Unsupported case status: {status}")
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT payload_json FROM workflow_cases WHERE case_id = %s FOR UPDATE",
                (case_id,),
            ).fetchone()
            case = _case_from_row(row)
            if case is None:
                return None
            _append_case_status_update(
                case,
                status,
                note,
                assigned_to=assigned_to,
                action_outcome=action_outcome,
            )
            connection.execute(
                """
                UPDATE workflow_cases
                SET status = %s, updated_at = %s, payload_json = %s::jsonb,
                    revision = revision + 1
                WHERE case_id = %s
                """,
                (
                    case.status,
                    case.updated_at,
                    _case_json(case),
                    case.case_id,
                ),
            )
        return case

    def append_case_note(
        self,
        case_id: str,
        note: str,
        *,
        assigned_to: str | None = None,
    ) -> WorkflowCase | None:
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT payload_json FROM workflow_cases WHERE case_id = %s FOR UPDATE",
                (case_id,),
            ).fetchone()
            case = _case_from_row(row)
            if case is None:
                return None
            _append_case_note(case, note, assigned_to=assigned_to)
            connection.execute(
                """
                UPDATE workflow_cases
                SET updated_at = %s, payload_json = %s::jsonb,
                    revision = revision + 1
                WHERE case_id = %s
                """,
                (
                    case.updated_at,
                    _case_json(case),
                    case.case_id,
                ),
            )
        return case

    def publish_case_handoff(
        self,
        case_id: str,
        *,
        destination_type: str,
        destination_key: str,
        note: str | None = None,
    ) -> WorkflowCase | None:
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT payload_json FROM workflow_cases WHERE case_id = %s FOR UPDATE",
                (case_id,),
            ).fetchone()
            case = _case_from_row(row)
            if case is None:
                return None
            _append_case_handoff_publication(
                case,
                destination_type=destination_type,
                destination_key=destination_key,
                note=note,
            )
            connection.execute(
                """
                UPDATE workflow_cases
                SET updated_at = %s, payload_json = %s::jsonb,
                    revision = revision + 1
                WHERE case_id = %s
                """,
                (
                    case.updated_at,
                    _case_json(case),
                    case.case_id,
                ),
            )
        return case

    def record_case_handoff_delivery(
        self,
        case_id: str,
        *,
        export_id: str,
        destination_type: str,
        destination_key: str,
        publisher_type: str,
        target_ref: str,
        status: str,
        summary: str,
        created_at: str,
        published_at: str | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> WorkflowCase | None:
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT payload_json FROM workflow_cases WHERE case_id = %s FOR UPDATE",
                (case_id,),
            ).fetchone()
            case = _case_from_row(row)
            if case is None:
                return None
            _append_case_handoff_delivery(
                case,
                export_id=export_id,
                destination_type=destination_type,
                destination_key=destination_key,
                publisher_type=publisher_type,
                target_ref=target_ref,
                status=status,
                summary=summary,
                created_at=created_at,
                published_at=published_at,
                error_type=error_type,
                error_message=error_message,
                metadata=metadata,
            )
            connection.execute(
                """
                UPDATE workflow_cases
                SET updated_at = %s, payload_json = %s::jsonb,
                    revision = revision + 1
                WHERE case_id = %s
                """,
                (
                    case.updated_at,
                    _case_json(case),
                    case.case_id,
                ),
            )
        return case


def _build_case_from_session(
    session: SessionRecord,
    *,
    turn_index: int | None = None,
) -> WorkflowCase:
    if not session.turns:
        raise ValueError("Session has no turns")
    resolved_turn_index = turn_index or len(session.turns)
    if resolved_turn_index < 1 or resolved_turn_index > len(session.turns):
        raise IndexError("Turn index out of range")
    turn = session.turns[resolved_turn_index - 1]
    recommendation = _extract_strategy_recommendation(turn.artifacts)
    risk_decision = _extract_risk_decision(turn.artifacts)
    root_cause_decision = _build_root_cause_risk_decision(turn.artifacts)
    if root_cause_decision is not None and (
        risk_decision is None or risk_decision.recommended_action == "monitor"
    ):
        risk_decision = root_cause_decision
    status = _initial_status(
        turn.agent_name,
        turn.intent,
        recommendation,
        risk_decision,
    )
    timestamp = _current_timestamp()
    _schedule_risk_action_plan(
        risk_decision,
        created_at=timestamp,
        case_status=status,
    )
    case = WorkflowCase(
        case_id=f"CASE-{uuid4().hex[:8].upper()}",
        session_id=session.session_id,
        turn_index=resolved_turn_index,
        title=build_turn_title(turn.agent_name),
        summary=turn.summary,
        status=status,
        severity=build_severity(turn.agent_name, turn.intent),
        source_agent=turn.agent_name,
        intent=turn.intent,
        context=dict(turn.context),
        suggested_actions=list(turn.suggested_actions),
        evidence_panel=_extract_evidence_panel(turn),
        strategy_recommendation=recommendation,
        risk_decision=risk_decision,
        history=[
            WorkflowCaseHistoryEntry(
                event_type="case_created",
                status=status,
                summary=f"基于 session {session.session_id} 的第 {resolved_turn_index} 个 turn 创建 case。",
            )
        ],
        created_at=timestamp,
        updated_at=timestamp,
    )
    _record_case_operation(
        case,
        operation_type="case_created",
        status_before=None,
        status_after=status,
        summary=case.history[-1].summary,
        metadata={
            "session_id": session.session_id,
            "turn_index": resolved_turn_index,
            "source_agent": turn.agent_name,
            "intent": turn.intent,
        },
    )
    _refresh_case_handoff_artifact(case, trigger="case_created")
    return case


def _filter_cases(
    cases,
    *,
    status: str | None = None,
    source_agent: str | None = None,
    intent: str | None = None,
    session_id: str | None = None,
    severity: str | None = None,
    action_queue: str | None = None,
    action_status: str | None = None,
    assigned_to: str | None = None,
    action_overdue: bool | None = None,
    updated_after: str | None = None,
    updated_before: str | None = None,
    sort_by: str = "updated_at",
    sort_order: str = "desc",
    limit: int | None = None,
    offset: int = 0,
) -> list[WorkflowCase]:
    filtered = list(cases)
    if status is not None:
        filtered = [case for case in filtered if case.status == status]
    if source_agent is not None:
        filtered = [case for case in filtered if case.source_agent == source_agent]
    if intent is not None:
        filtered = [case for case in filtered if case.intent == intent]
    if session_id is not None:
        filtered = [case for case in filtered if case.session_id == session_id]
    if severity is not None:
        filtered = [case for case in filtered if case.severity == severity]
    if action_queue is not None:
        filtered = [
            case
            for case in filtered
            if _case_action_plan(case) is not None
            and _case_action_plan(case).queue == action_queue
        ]
    if action_status is not None:
        filtered = [
            case
            for case in filtered
            if _case_action_plan(case) is not None
            and _case_action_plan(case).status == action_status
        ]
    if assigned_to is not None:
        filtered = [
            case
            for case in filtered
            if _case_action_plan(case) is not None
            and _case_action_plan(case).assigned_to == assigned_to
        ]
    if action_overdue is not None:
        filtered = [
            case
            for case in filtered
            if _case_action_plan(case) is not None
            and is_risk_action_plan_overdue(_case_action_plan(case)) is action_overdue
        ]
    if updated_after is not None:
        updated_after_dt = _parse_timestamp(updated_after)
        filtered = [
            case
            for case in filtered
            if case.updated_at and _parse_timestamp(case.updated_at) >= updated_after_dt
        ]
    if updated_before is not None:
        updated_before_dt = _parse_timestamp(updated_before)
        filtered = [
            case
            for case in filtered
            if case.updated_at and _parse_timestamp(case.updated_at) <= updated_before_dt
        ]
    filtered.sort(
        key=lambda case: _case_sort_key(case, sort_by),
        reverse=sort_order.lower() != "asc",
    )
    if offset:
        filtered = filtered[offset:]
    if limit is not None:
        filtered = filtered[:limit]
    return filtered


def _requires_action_plan_filter(
    *,
    action_queue: str | None,
    action_status: str | None,
    assigned_to: str | None,
    action_overdue: bool | None,
) -> bool:
    return any(
        value is not None
        for value in (action_queue, action_status, assigned_to, action_overdue)
    )


def _case_action_plan(case: WorkflowCase) -> RiskActionPlanRecord | None:
    if case.risk_decision is None:
        return None
    return case.risk_decision.action_plan


def is_risk_action_plan_overdue(
    action_plan: RiskActionPlanRecord,
    *,
    now: datetime | None = None,
) -> bool:
    if action_plan.status == "completed" or action_plan.due_at is None:
        return False
    now_dt = now or datetime.now(timezone.utc)
    return _parse_timestamp(action_plan.due_at) < now_dt


def _append_case_status_update(
    case: WorkflowCase,
    status: str,
    note: str | None,
    *,
    assigned_to: str | None = None,
    action_outcome: str | None = None,
) -> None:
    previous_status = case.status
    case.status = status
    updated_at = _current_timestamp()
    case.updated_at = updated_at
    _sync_risk_action_plan_status(
        case,
        status=status,
        timestamp=updated_at,
        assigned_to=assigned_to,
        action_outcome=action_outcome,
    )
    case.history.append(
        WorkflowCaseHistoryEntry(
            event_type="status_updated",
            status=status,
            summary=note or f"Case 状态更新为 {status}。",
        )
    )
    _record_case_operation(
        case,
        operation_type="status_updated",
        status_before=previous_status,
        status_after=status,
        summary=case.history[-1].summary,
        assigned_to=assigned_to,
        action_outcome=action_outcome,
        metadata={"event_type": "status_updated"},
    )
    _refresh_case_handoff_artifact(case, trigger="status_updated")


def _append_case_note(
    case: WorkflowCase,
    note: str,
    *,
    assigned_to: str | None = None,
) -> None:
    updated_at = _current_timestamp()
    case.updated_at = updated_at
    action_plan = _case_action_plan(case)
    if action_plan is not None and assigned_to is not None:
        action_plan.assigned_to = assigned_to
    summary = note
    if assigned_to is not None and assigned_to not in note:
        summary = f"{note}（负责人：{assigned_to}）"
    case.history.append(
        WorkflowCaseHistoryEntry(
            event_type="note_added",
            status=case.status,
            summary=summary,
        )
    )
    _record_case_operation(
        case,
        operation_type="note_added",
        status_before=case.status,
        status_after=case.status,
        summary=summary,
        assigned_to=assigned_to,
        metadata={"event_type": "note_added"},
    )
    _refresh_case_handoff_artifact(case, trigger="note_added")


def _append_case_handoff_publication(
    case: WorkflowCase,
    *,
    destination_type: str,
    destination_key: str,
    note: str | None,
) -> None:
    updated_at = _current_timestamp()
    case.updated_at = updated_at
    summary = note or f"案件交接已发布到 {destination_type}:{destination_key}。"
    case.history.append(
        WorkflowCaseHistoryEntry(
            event_type="handoff_published",
            status=case.status,
            summary=summary,
        )
    )
    _record_case_operation(
        case,
        operation_type="handoff_published",
        status_before=case.status,
        status_after=case.status,
        summary=summary,
        metadata={
            "event_type": "handoff_published",
            "destination_type": destination_type,
            "destination_key": destination_key,
        },
    )
    _refresh_case_handoff_artifact(case, trigger="handoff_published")


def _append_case_handoff_delivery(
    case: WorkflowCase,
    *,
    export_id: str,
    destination_type: str,
    destination_key: str,
    publisher_type: str,
    target_ref: str,
    status: str,
    summary: str,
    created_at: str,
    published_at: str | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    case.updated_at = created_at or _current_timestamp()
    case.handoff_deliveries.append(
        WorkflowCaseHandoffDeliveryEntry(
            delivery_id=f"DLV-{uuid4().hex[:10].upper()}",
            export_id=export_id,
            destination_type=destination_type,
            destination_key=destination_key,
            publisher_type=publisher_type,
            target_ref=target_ref,
            status=status,
            summary=summary,
            created_at=case.updated_at,
            published_at=published_at,
            error_type=error_type,
            error_message=error_message,
            metadata=dict(metadata or {}),
        )
    )
    operation_type = "handoff_delivery_recorded"
    event_type = "handoff_delivery_recorded"
    if status != "published":
        operation_type = "handoff_publish_failed"
        event_type = "handoff_publish_failed"
    case.history.append(
        WorkflowCaseHistoryEntry(
            event_type=event_type,
            status=case.status,
            summary=summary,
        )
    )
    _record_case_operation(
        case,
        operation_type=operation_type,
        status_before=case.status,
        status_after=case.status,
        summary=summary,
        metadata={
            "event_type": event_type,
            "delivery_status": status,
            "destination_type": destination_type,
            "destination_key": destination_key,
            "publisher_type": publisher_type,
            "target_ref": target_ref,
            "export_id": export_id,
            "error_type": error_type,
        },
    )
    _refresh_case_handoff_artifact(case, trigger=event_type)


def _record_case_operation(
    case: WorkflowCase,
    *,
    operation_type: str,
    status_before: str | None,
    status_after: str,
    summary: str,
    assigned_to: str | None = None,
    action_outcome: str | None = None,
    metadata: dict[str, Any] | None = None,
    actor: str = "platform",
) -> None:
    case.operation_log.append(
        WorkflowCaseOperationEntry(
            operation_id=f"OP-{uuid4().hex[:10].upper()}",
            operation_type=operation_type,
            actor=actor,
            status_before=status_before,
            status_after=status_after,
            summary=summary,
            created_at=case.updated_at or _current_timestamp(),
            assigned_to=assigned_to,
            action_outcome=action_outcome,
            metadata=dict(metadata or {}),
        )
    )


def _refresh_case_handoff_artifact(
    case: WorkflowCase,
    *,
    trigger: str,
) -> None:
    action_plan = _case_action_plan(case)
    evidence_summary = dict(case.evidence_panel.get("summary", {}))
    evidence_gaps = [
        dict(item)
        for item in case.evidence_panel.get("gaps", [])
        if isinstance(item, dict)
    ]
    next_actions: list[str] = []
    for item in case.suggested_actions:
        if item and item not in next_actions:
            next_actions.append(item)
    if action_plan is not None:
        for item in action_plan.next_actions:
            if item and item not in next_actions:
                next_actions.append(item)
    latest_operation = case.operation_log[-1] if case.operation_log else None
    latest_delivery = case.handoff_deliveries[-1] if case.handoff_deliveries else None
    failed_delivery_count = sum(
        1 for entry in case.handoff_deliveries if entry.status != "published"
    )
    case.handoff_artifact = {
        "version": "v1",
        "case_id": case.case_id,
        "title": case.title,
        "status": case.status,
        "severity": case.severity,
        "source_agent": case.source_agent,
        "intent": case.intent,
        "summary": case.summary,
        "decision": (
            case.risk_decision.decision if case.risk_decision is not None else None
        ),
        "recommended_action": (
            case.risk_decision.recommended_action if case.risk_decision is not None else None
        ),
        "action_queue": action_plan.queue if action_plan is not None else None,
        "owner_role": action_plan.owner_role if action_plan is not None else None,
        "assigned_to": action_plan.assigned_to if action_plan is not None else None,
        "due_at": action_plan.due_at if action_plan is not None else None,
        "evidence_summary": evidence_summary,
        "evidence_gaps": evidence_gaps,
        "top_evidence": (
            list(case.risk_decision.evidence[:3])
            if case.risk_decision is not None
            else []
        ),
        "handoff_delivery_summary": {
            "total_attempts": len(case.handoff_deliveries),
            "failed_attempts": failed_delivery_count,
            "last_status": (
                latest_delivery.status if latest_delivery is not None else None
            ),
            "last_destination_type": (
                latest_delivery.destination_type if latest_delivery is not None else None
            ),
            "last_destination_key": (
                latest_delivery.destination_key if latest_delivery is not None else None
            ),
            "last_publisher_type": (
                latest_delivery.publisher_type if latest_delivery is not None else None
            ),
            "last_published_at": (
                latest_delivery.published_at if latest_delivery is not None else None
            ),
        },
        "next_actions": next_actions,
        "operation_context": {
            "trigger": trigger,
            "operation_count": len(case.operation_log),
            "latest_operation_id": (
                latest_operation.operation_id if latest_operation is not None else None
            ),
            "latest_operation_type": (
                latest_operation.operation_type if latest_operation is not None else None
            ),
        },
        "updated_at": case.updated_at,
    }


def _extract_strategy_recommendation(
    artifacts: dict[str, object],
) -> StrategyRecommendationRecord | None:
    payload = artifacts.get("strategy_recommendation")
    if not isinstance(payload, dict):
        return None
    return StrategyRecommendationRecord(
        strategy_id=str(payload["strategy_id"]),
        current_threshold=float(payload["current_threshold"]),
        recommended_threshold=float(payload["recommended_threshold"]),
        validation_window=str(payload["validation_window"]),
        rationale=str(payload["rationale"]),
    )


def _extract_risk_decision(
    artifacts: dict[str, object],
) -> RiskDecisionRecord | None:
    payload = artifacts.get("risk_decision")
    if not isinstance(payload, dict):
        return None
    return RiskDecisionRecord(
        decision=str(payload["decision"]),
        risk_level=str(payload["risk_level"]),
        recommended_action=str(payload["recommended_action"]),
        evidence_strength=str(payload["evidence_strength"]),
        confidence=float(payload["confidence"]),
        rationale=str(payload["rationale"]),
        escalation_reason=(
            str(payload["escalation_reason"])
            if payload.get("escalation_reason") is not None
            else None
        ),
        evidence=[str(item) for item in payload.get("evidence", [])],
        policy_controls=[str(item) for item in payload.get("policy_controls", [])],
        action_plan=_extract_risk_action_plan(payload.get("action_plan")),
    )


def _build_root_cause_risk_decision(
    artifacts: dict[str, object],
) -> RiskDecisionRecord | None:
    readiness = artifacts.get("root_cause_readiness")
    if not isinstance(readiness, dict) or readiness.get("version") != "v4d":
        return None
    status = str(readiness.get("status") or "")
    if status not in {"ready_for_handoff", "requires_review", "blocked"}:
        return None
    analysis = artifacts.get("root_cause_analysis")
    top_root_cause: dict[str, Any] = {}
    if isinstance(analysis, dict) and isinstance(analysis.get("top_root_cause"), dict):
        top_root_cause = dict(analysis["top_root_cause"])
    actionability_score = float(readiness.get("actionability_score", 0.0) or 0.0)
    top_confidence = float(readiness.get("top_confidence", 0.0) or 0.0)
    confidence = round(max(actionability_score, top_confidence), 3)
    allowed_actions = [
        str(item)
        for item in readiness.get("allowed_actions", [])
        if item is not None
    ]
    required_controls = [
        str(item)
        for item in readiness.get("required_controls", [])
        if item is not None
    ]
    reasons = [
        str(item)
        for item in readiness.get("reasons", [])
        if item is not None
    ]
    blockers = [
        str(item)
        for item in readiness.get("blockers", [])
        if item is not None
    ]
    top_label = str(top_root_cause.get("label") or top_root_cause.get("id") or "unknown")
    top_id = str(top_root_cause.get("id") or "unknown")
    evidence = [f"Top1 根因为 {top_label}({top_id})，置信度 {top_confidence:.2f}。"]
    evidence.extend(reasons)
    if blockers:
        evidence.append(f"阻塞项：{', '.join(blockers)}。")

    if status == "ready_for_handoff":
        decision = "root_cause_handoff"
        risk_level = "medium"
        recommended_action = "start_shadow_evaluation"
        evidence_strength = "strong"
        escalation_reason = None
        action_plan = RiskActionPlanRecord(
            queue="strategy_shadow_queue",
            priority="medium",
            sla_hours=24,
            owner_role="strategy_owner",
            next_actions=[
                "基于 Top1 根因创建 shadow evaluation 实验",
                "绑定根因证据矩阵并监控异常指标回落",
            ],
        )
    elif status == "requires_review":
        decision = "root_cause_review"
        risk_level = "medium"
        recommended_action = "queue_root_cause_review"
        evidence_strength = "medium"
        escalation_reason = "根因质量或控制项未完全满足交接阈值，需要人工复核。"
        action_plan = RiskActionPlanRecord(
            queue="root_cause_review_queue",
            priority="medium",
            sla_hours=12,
            owner_role="risk_analyst",
            next_actions=[
                "复核根因候选排序和反证覆盖",
                "补充验证样本后确认是否进入 shadow evaluation",
            ],
        )
    else:
        decision = "root_cause_blocked"
        risk_level = "medium"
        recommended_action = "collect_missing_evidence"
        evidence_strength = "weak"
        escalation_reason = "根因分析存在阻塞证据缺口，暂不能交接执行。"
        action_plan = RiskActionPlanRecord(
            queue="risk_investigation_queue",
            priority="high",
            sla_hours=8,
            owner_role="risk_ops",
            next_actions=[
                "补齐根因分析缺失的工具证据",
                "证据恢复后重新运行根因 readiness gate",
            ],
        )

    policy_controls = list(dict.fromkeys(required_controls))
    if "start_shadow_evaluation" in allowed_actions and "shadow_evaluation" not in policy_controls:
        policy_controls.append("shadow_evaluation")
    if recommended_action == "queue_root_cause_review" and "root_cause_review" not in policy_controls:
        policy_controls.append("root_cause_review")
    if recommended_action == "collect_missing_evidence" and "evidence_gap_review" not in policy_controls:
        policy_controls.append("evidence_gap_review")

    return RiskDecisionRecord(
        decision=decision,
        risk_level=risk_level,
        recommended_action=recommended_action,
        evidence_strength=evidence_strength,
        confidence=confidence,
        rationale="；".join(evidence),
        escalation_reason=escalation_reason,
        evidence=evidence,
        policy_controls=policy_controls,
        action_plan=action_plan,
    )


def _extract_risk_action_plan(payload: object) -> RiskActionPlanRecord | None:
    if not isinstance(payload, dict):
        return None
    return RiskActionPlanRecord(
        queue=str(payload["queue"]),
        priority=str(payload["priority"]),
        sla_hours=int(payload["sla_hours"]),
        owner_role=str(payload["owner_role"]),
        next_actions=[str(item) for item in payload.get("next_actions", [])],
        status=str(payload.get("status", "queued")),
        due_at=str(payload["due_at"]) if payload.get("due_at") is not None else None,
        assigned_to=(
            str(payload["assigned_to"])
            if payload.get("assigned_to") is not None
            else None
        ),
        completed_at=(
            str(payload["completed_at"])
            if payload.get("completed_at") is not None
            else None
        ),
        outcome=str(payload["outcome"]) if payload.get("outcome") is not None else None,
    )


def _initial_status(
    agent_name: str,
    intent: str | None,
    recommendation: StrategyRecommendationRecord | None,
    risk_decision: RiskDecisionRecord | None = None,
) -> str:
    if recommendation is not None:
        return "strategy_pending"
    if risk_decision is not None:
        if risk_decision.recommended_action in {"start_shadow_evaluation", "shadow_evaluation"}:
            return "strategy_pending"
        if risk_decision.recommended_action in {"manual_review", "queue_root_cause_review"}:
            return "in_review"
    if agent_name == "copilot" or intent in {"fraud_ring", "order_case", "composite"}:
        return "in_review"
    return "open"


def _serialize_case(case: WorkflowCase) -> dict[str, object]:
    return {
        "case_id": case.case_id,
        "session_id": case.session_id,
        "turn_index": case.turn_index,
        "title": case.title,
        "summary": case.summary,
        "status": case.status,
        "severity": case.severity,
        "source_agent": case.source_agent,
        "intent": case.intent,
        "context": case.context,
        "suggested_actions": case.suggested_actions,
        "evidence_panel": case.evidence_panel,
        "handoff_artifact": case.handoff_artifact,
        "created_at": case.created_at,
        "updated_at": case.updated_at,
        "strategy_recommendation": (
            {
                "strategy_id": case.strategy_recommendation.strategy_id,
                "current_threshold": case.strategy_recommendation.current_threshold,
                "recommended_threshold": case.strategy_recommendation.recommended_threshold,
                "validation_window": case.strategy_recommendation.validation_window,
                "rationale": case.strategy_recommendation.rationale,
            }
            if case.strategy_recommendation is not None
            else None
        ),
        "risk_decision": (
            {
                "decision": case.risk_decision.decision,
                "risk_level": case.risk_decision.risk_level,
                "recommended_action": case.risk_decision.recommended_action,
                "evidence_strength": case.risk_decision.evidence_strength,
                "confidence": case.risk_decision.confidence,
                "rationale": case.risk_decision.rationale,
                "escalation_reason": case.risk_decision.escalation_reason,
                "evidence": case.risk_decision.evidence,
                "policy_controls": case.risk_decision.policy_controls,
                "action_plan": _serialize_risk_action_plan(
                    case.risk_decision.action_plan
                ),
            }
            if case.risk_decision is not None
            else None
        ),
        "history": [
            {
                "event_type": item.event_type,
                "status": item.status,
                "summary": item.summary,
            }
            for item in case.history
        ],
        "operation_log": [
            {
                "operation_id": item.operation_id,
                "operation_type": item.operation_type,
                "actor": item.actor,
                "status_before": item.status_before,
                "status_after": item.status_after,
                "summary": item.summary,
                "created_at": item.created_at,
                "assigned_to": item.assigned_to,
                "action_outcome": item.action_outcome,
                "metadata": item.metadata,
            }
            for item in case.operation_log
        ],
        "handoff_deliveries": [
            {
                "delivery_id": item.delivery_id,
                "export_id": item.export_id,
                "destination_type": item.destination_type,
                "destination_key": item.destination_key,
                "publisher_type": item.publisher_type,
                "target_ref": item.target_ref,
                "status": item.status,
                "summary": item.summary,
                "created_at": item.created_at,
                "published_at": item.published_at,
                "error_type": item.error_type,
                "error_message": item.error_message,
                "metadata": item.metadata,
            }
            for item in case.handoff_deliveries
        ],
    }


def _deserialize_case(payload: dict[str, object]) -> WorkflowCase:
    item = dict(payload)
    recommendation_payload = item.get("strategy_recommendation")
    if isinstance(recommendation_payload, dict):
        recommendation = StrategyRecommendationRecord(
            strategy_id=str(recommendation_payload["strategy_id"]),
            current_threshold=float(recommendation_payload["current_threshold"]),
            recommended_threshold=float(recommendation_payload["recommended_threshold"]),
            validation_window=str(recommendation_payload["validation_window"]),
            rationale=str(recommendation_payload["rationale"]),
        )
    else:
        recommendation = None
    risk_decision_payload = item.get("risk_decision")
    if isinstance(risk_decision_payload, dict):
        risk_decision = RiskDecisionRecord(
            decision=str(risk_decision_payload["decision"]),
            risk_level=str(risk_decision_payload["risk_level"]),
            recommended_action=str(risk_decision_payload["recommended_action"]),
            evidence_strength=str(risk_decision_payload["evidence_strength"]),
            confidence=float(risk_decision_payload["confidence"]),
            rationale=str(risk_decision_payload["rationale"]),
            escalation_reason=(
                str(risk_decision_payload["escalation_reason"])
                if risk_decision_payload.get("escalation_reason") is not None
                else None
            ),
            evidence=[str(value) for value in risk_decision_payload.get("evidence", [])],
            policy_controls=[
                str(value)
                for value in risk_decision_payload.get("policy_controls", [])
            ],
            action_plan=_extract_risk_action_plan(
                risk_decision_payload.get("action_plan")
            ),
        )
    else:
        risk_decision = None
    history = [
        WorkflowCaseHistoryEntry(
            event_type=str(entry["event_type"]),
            status=str(entry["status"]),
            summary=str(entry["summary"]),
        )
        for entry in item.get("history", [])
    ]
    operation_log = [
        WorkflowCaseOperationEntry(
            operation_id=str(entry["operation_id"]),
            operation_type=str(entry["operation_type"]),
            actor=str(entry.get("actor", "platform")),
            status_before=(
                str(entry["status_before"])
                if entry.get("status_before") is not None
                else None
            ),
            status_after=str(entry.get("status_after", item.get("status", ""))),
            summary=str(entry.get("summary", "")),
            created_at=str(entry.get("created_at", item.get("updated_at", ""))),
            assigned_to=(
                str(entry["assigned_to"])
                if entry.get("assigned_to") is not None
                else None
            ),
            action_outcome=(
                str(entry["action_outcome"])
                if entry.get("action_outcome") is not None
                else None
            ),
            metadata=dict(entry.get("metadata", {})),
        )
        for entry in item.get("operation_log", [])
        if isinstance(entry, dict)
    ]
    handoff_deliveries = [
        WorkflowCaseHandoffDeliveryEntry(
            delivery_id=str(entry["delivery_id"]),
            export_id=str(entry["export_id"]),
            destination_type=str(entry["destination_type"]),
            destination_key=str(entry["destination_key"]),
            publisher_type=str(entry.get("publisher_type", "unknown")),
            target_ref=str(entry.get("target_ref", "")),
            status=str(entry.get("status", "published")),
            summary=str(entry.get("summary", "")),
            created_at=str(entry.get("created_at", item.get("updated_at", ""))),
            published_at=(
                str(entry["published_at"])
                if entry.get("published_at") is not None
                else None
            ),
            error_type=(
                str(entry["error_type"])
                if entry.get("error_type") is not None
                else None
            ),
            error_message=(
                str(entry["error_message"])
                if entry.get("error_message") is not None
                else None
            ),
            metadata=dict(entry.get("metadata", {})),
        )
        for entry in item.get("handoff_deliveries", [])
        if isinstance(entry, dict)
    ]
    case = WorkflowCase(
        case_id=str(item["case_id"]),
        session_id=str(item["session_id"]),
        turn_index=int(item["turn_index"]),
        title=str(item["title"]),
        summary=str(item["summary"]),
        status=str(item["status"]),
        severity=str(item["severity"]),
        source_agent=str(item["source_agent"]),
        intent=str(item["intent"]) if item.get("intent") is not None else None,
        context=dict(item.get("context", {})),
        suggested_actions=list(item.get("suggested_actions", [])),
        evidence_panel=dict(item.get("evidence_panel", {})),
        handoff_artifact=dict(item.get("handoff_artifact", {})),
        strategy_recommendation=recommendation,
        risk_decision=risk_decision,
        history=history,
        operation_log=operation_log,
        handoff_deliveries=handoff_deliveries,
        created_at=str(item.get("created_at", "")),
        updated_at=str(item.get("updated_at", "")),
    )
    if not case.operation_log:
        for history_entry in case.history:
            case.operation_log.append(
                WorkflowCaseOperationEntry(
                    operation_id=f"OP-{uuid4().hex[:10].upper()}",
                    operation_type=history_entry.event_type,
                    actor="platform",
                    status_before=None,
                    status_after=history_entry.status,
                    summary=history_entry.summary,
                    created_at=case.updated_at,
                    metadata={"legacy_history": True},
                )
            )
    if not case.handoff_artifact:
        _refresh_case_handoff_artifact(case, trigger="legacy_rebuild")
    return case


def _extract_evidence_panel(turn) -> dict[str, object]:
    panel = turn.artifacts.get("evidence_panel")
    if isinstance(panel, dict):
        return dict(panel)
    return build_session_turn_evidence_panel(turn, scope="case")


def _serialize_risk_action_plan(
    action_plan: RiskActionPlanRecord | None,
) -> dict[str, object] | None:
    if action_plan is None:
        return None
    return {
        "queue": action_plan.queue,
        "priority": action_plan.priority,
        "sla_hours": action_plan.sla_hours,
        "owner_role": action_plan.owner_role,
        "next_actions": action_plan.next_actions,
        "status": action_plan.status,
        "due_at": action_plan.due_at,
        "assigned_to": action_plan.assigned_to,
        "completed_at": action_plan.completed_at,
        "outcome": action_plan.outcome,
    }


def _schedule_risk_action_plan(
    risk_decision: RiskDecisionRecord | None,
    *,
    created_at: str,
    case_status: str,
) -> None:
    if risk_decision is None or risk_decision.action_plan is None:
        return
    action_plan = risk_decision.action_plan
    if case_status == "in_review":
        action_plan.status = "in_progress"
    elif case_status in {"open", "strategy_pending"}:
        action_plan.status = "queued"
    if action_plan.due_at is None:
        created_at_dt = _parse_timestamp(created_at)
        action_plan.due_at = _format_timestamp(
            created_at_dt + timedelta(hours=action_plan.sla_hours)
        )


def _sync_risk_action_plan_status(
    case: WorkflowCase,
    *,
    status: str,
    timestamp: str,
    assigned_to: str | None,
    action_outcome: str | None,
) -> None:
    if case.risk_decision is None or case.risk_decision.action_plan is None:
        return
    action_plan = case.risk_decision.action_plan
    if assigned_to is not None:
        action_plan.assigned_to = assigned_to
    if status in {"open", "strategy_pending"}:
        action_plan.status = "queued"
        action_plan.completed_at = None
        action_plan.outcome = action_outcome
    elif status == "in_review":
        action_plan.status = "in_progress"
        action_plan.completed_at = None
        action_plan.outcome = action_outcome
    elif status == "closed":
        action_plan.status = "completed"
        action_plan.completed_at = timestamp
        action_plan.outcome = action_outcome


def _case_sort_key(case: WorkflowCase, sort_by: str) -> str:
    if sort_by == "created_at":
        return case.created_at
    if sort_by == "status":
        return case.status
    if sort_by == "severity":
        return case.severity
    return case.updated_at


def _current_timestamp() -> str:
    return _format_timestamp(datetime.now(timezone.utc))


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _format_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00",
        "Z",
    )


def _case_json(case: WorkflowCase) -> str:
    return json.dumps(
        _serialize_case(case),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _case_row_values(case: WorkflowCase) -> tuple[object, ...]:
    return (
        case.case_id,
        case.session_id,
        case.turn_index,
        case.status,
        case.severity,
        case.source_agent,
        case.intent,
        case.created_at,
        case.updated_at,
        _case_json(case),
    )


def _case_from_row(row) -> WorkflowCase | None:
    if row is None:
        return None
    payload = row["payload_json"]
    if isinstance(payload, str):
        return _deserialize_case(json.loads(payload))
    if isinstance(payload, dict):
        return _deserialize_case(payload)
    raise TypeError("Unsupported case payload type")


def _find_case_for_session_turn(
    cases,
    session_id: str,
    turn_index: int,
) -> WorkflowCase | None:
    return next(
        (
            case
            for case in cases
            if case.session_id == session_id and case.turn_index == turn_index
        ),
        None,
    )


def _build_case_where(
    *,
    status: str | None,
    source_agent: str | None,
    intent: str | None,
    session_id: str | None,
    severity: str | None,
    updated_after: str | None,
    updated_before: str | None,
    placeholder: str = "?",
) -> tuple[str, list[object]]:
    clauses: list[str] = []
    params: list[object] = []
    for column, value in (
        ("status", status),
        ("source_agent", source_agent),
        ("intent", intent),
        ("session_id", session_id),
        ("severity", severity),
    ):
        if value is not None:
            clauses.append(f"{column} = {placeholder}")
            params.append(value)
    if updated_after is not None:
        clauses.append(f"updated_at >= {placeholder}")
        params.append(_normalize_timestamp(updated_after))
    if updated_before is not None:
        clauses.append(f"updated_at <= {placeholder}")
        params.append(_normalize_timestamp(updated_before))
    if not clauses:
        return "", params
    return f"WHERE {' AND '.join(clauses)}", params


def _normalize_timestamp(value: str) -> str:
    return _parse_timestamp(value).astimezone(timezone.utc).isoformat(
        timespec="microseconds"
    ).replace("+00:00", "Z")
