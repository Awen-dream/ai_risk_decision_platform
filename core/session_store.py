from __future__ import annotations

import json
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path

from core.models import (
    AgentRequest,
    AgentResponse,
    EvidenceGap,
    EvidenceRecord,
    PlannerTraceStep,
    SessionRecord,
    SessionTurn,
    ToolSelectionReason,
)
from persistence.postgres import PostgresDatabase
from persistence.sqlite import SQLiteDatabase


class SessionStore(ABC):
    @abstractmethod
    def create_session(self) -> SessionRecord:
        """Create and persist a new session record."""

    @abstractmethod
    def get_session(self, session_id: str) -> SessionRecord | None:
        """Return the session record by id if it exists."""

    @abstractmethod
    def ensure_session(self, session_id: str | None) -> SessionRecord:
        """Return an existing session or create a new one."""

    @abstractmethod
    def append_turn(
        self,
        session_id: str,
        request: AgentRequest,
        response: AgentResponse,
    ) -> SessionRecord:
        """Append one turn to the session and persist it."""


class InMemorySessionStore(SessionStore):
    """Stores agent conversations in memory for demo and local development."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionRecord] = {}

    def create_session(self) -> SessionRecord:
        session_id = str(uuid.uuid4())
        session = SessionRecord(session_id=session_id)
        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> SessionRecord | None:
        return self._sessions.get(session_id)

    def ensure_session(self, session_id: str | None) -> SessionRecord:
        if session_id:
            existing = self.get_session(session_id)
            if existing:
                return existing
        return self.create_session()

    def append_turn(
        self,
        session_id: str,
        request: AgentRequest,
        response: AgentResponse,
    ) -> SessionRecord:
        session = self.ensure_session(session_id)
        session.turns.append(build_session_turn(request, response))
        return session


class FileSessionStore(SessionStore):
    """Stores session records in a local JSON file for lightweight persistence."""

    def __init__(self, file_path: Path) -> None:
        self._file_path = file_path
        self._file_path.parent.mkdir(parents=True, exist_ok=True)

    def create_session(self) -> SessionRecord:
        sessions = self._load_sessions()
        session_id = str(uuid.uuid4())
        session = SessionRecord(session_id=session_id)
        sessions[session_id] = session
        self._save_sessions(sessions)
        return session

    def get_session(self, session_id: str) -> SessionRecord | None:
        sessions = self._load_sessions()
        return sessions.get(session_id)

    def ensure_session(self, session_id: str | None) -> SessionRecord:
        if session_id:
            existing = self.get_session(session_id)
            if existing:
                return existing
        return self.create_session()

    def append_turn(
        self,
        session_id: str,
        request: AgentRequest,
        response: AgentResponse,
    ) -> SessionRecord:
        sessions = self._load_sessions()
        if session_id and session_id in sessions:
            session = sessions[session_id]
        else:
            session = SessionRecord(session_id=session_id or str(uuid.uuid4()))
            sessions[session.session_id] = session
        session.turns.append(build_session_turn(request, response))
        self._save_sessions(sessions)
        return session

    def _load_sessions(self) -> dict[str, SessionRecord]:
        if not self._file_path.exists():
            return {}
        payload = json.loads(self._file_path.read_text(encoding="utf-8"))
        sessions: dict[str, SessionRecord] = {}
        for item in payload.get("sessions", []):
            session = _deserialize_session_record(item)
            sessions[session.session_id] = session
        return sessions

    def _save_sessions(self, sessions: dict[str, SessionRecord]) -> None:
        payload = {
            "sessions": [
                _serialize_session_record(session)
                for session in sessions.values()
            ]
        }
        self._file_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


class SQLiteSessionStore(SessionStore):
    """Stores session records transactionally in SQLite."""

    def __init__(self, database_path: Path) -> None:
        self._database = SQLiteDatabase(database_path)
        self._database.migrate(
            1,
            "create_sessions",
            (
                """
                CREATE TABLE sessions (
                    session_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """,
                "CREATE INDEX idx_sessions_updated_at ON sessions(updated_at DESC)",
            ),
        )

    def create_session(self) -> SessionRecord:
        session = SessionRecord(session_id=str(uuid.uuid4()))
        timestamp = _current_timestamp()
        with self._database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO sessions(
                    session_id, payload_json, revision, created_at, updated_at
                ) VALUES (?, ?, 0, ?, ?)
                """,
                (
                    session.session_id,
                    _session_json(session),
                    timestamp,
                    timestamp,
                ),
            )
        return session

    def get_session(self, session_id: str) -> SessionRecord | None:
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT payload_json FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return _deserialize_session_record(json.loads(row["payload_json"]))

    def ensure_session(self, session_id: str | None) -> SessionRecord:
        if session_id:
            existing = self.get_session(session_id)
            if existing:
                return existing
        return self.create_session()

    def append_turn(
        self,
        session_id: str,
        request: AgentRequest,
        response: AgentResponse,
    ) -> SessionRecord:
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT payload_json FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                session = SessionRecord(session_id=session_id or str(uuid.uuid4()))
                timestamp = _current_timestamp()
                connection.execute(
                    """
                    INSERT INTO sessions(
                        session_id, payload_json, revision, created_at, updated_at
                    ) VALUES (?, ?, 0, ?, ?)
                    """,
                    (
                        session.session_id,
                        _session_json(session),
                        timestamp,
                        timestamp,
                    ),
                )
            else:
                session = _deserialize_session_record(json.loads(row["payload_json"]))
            session.turns.append(build_session_turn(request, response))
            connection.execute(
                """
                UPDATE sessions
                SET payload_json = ?, revision = revision + 1, updated_at = ?
                WHERE session_id = ?
                """,
                (
                    _session_json(session),
                    _current_timestamp(),
                    session.session_id,
                ),
            )
        return session


class PostgresSessionStore(SessionStore):
    """Stores session records transactionally in PostgreSQL."""

    def __init__(
        self,
        dsn: str,
        *,
        database: PostgresDatabase | None = None,
    ) -> None:
        self._database = database or PostgresDatabase(dsn)
        self._database.migrate(
            101,
            "create_postgres_sessions",
            (
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    payload_json JSONB NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """,
                """
                CREATE INDEX IF NOT EXISTS idx_sessions_updated_at
                ON sessions(updated_at DESC)
                """,
            ),
        )

    def create_session(self) -> SessionRecord:
        session = SessionRecord(session_id=str(uuid.uuid4()))
        timestamp = _current_timestamp()
        with self._database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO sessions(
                    session_id, payload_json, revision, created_at, updated_at
                ) VALUES (%s, %s::jsonb, 0, %s, %s)
                """,
                (
                    session.session_id,
                    _session_json(session),
                    timestamp,
                    timestamp,
                ),
            )
        return session

    def get_session(self, session_id: str) -> SessionRecord | None:
        with self._database.connection() as connection:
            row = connection.execute(
                "SELECT payload_json FROM sessions WHERE session_id = %s",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return _deserialize_session_payload(row["payload_json"])

    def ensure_session(self, session_id: str | None) -> SessionRecord:
        if session_id:
            existing = self.get_session(session_id)
            if existing:
                return existing
        return self.create_session()

    def append_turn(
        self,
        session_id: str,
        request: AgentRequest,
        response: AgentResponse,
    ) -> SessionRecord:
        with self._database.transaction() as connection:
            row = connection.execute(
                "SELECT payload_json FROM sessions WHERE session_id = %s FOR UPDATE",
                (session_id,),
            ).fetchone()
            if row is None:
                session = SessionRecord(session_id=session_id or str(uuid.uuid4()))
                timestamp = _current_timestamp()
                connection.execute(
                    """
                    INSERT INTO sessions(
                        session_id, payload_json, revision, created_at, updated_at
                    ) VALUES (%s, %s::jsonb, 0, %s, %s)
                    """,
                    (
                        session.session_id,
                        _session_json(session),
                        timestamp,
                        timestamp,
                    ),
                )
            else:
                session = _deserialize_session_payload(row["payload_json"])
            session.turns.append(build_session_turn(request, response))
            connection.execute(
                """
                UPDATE sessions
                SET payload_json = %s::jsonb, revision = revision + 1, updated_at = %s
                WHERE session_id = %s
                """,
                (
                    _session_json(session),
                    _current_timestamp(),
                    session.session_id,
                ),
            )
        return session


def build_session_turn(request: AgentRequest, response: AgentResponse) -> SessionTurn:
    return SessionTurn(
        agent_name=response.agent_name,
        query=request.query,
        context=request.context,
        summary=response.summary,
        intent=response.intent,
        thought_summary=response.thought_summary,
        plan_steps=response.plan_steps,
        planner_trace=[
            PlannerTraceStep(
                step=trace.step,
                selected=trace.selected,
                reason=trace.reason,
            )
            for trace in response.planner_trace
        ],
        tool_selection_reason=[
            ToolSelectionReason(
                tool=reason.tool,
                selected=reason.selected,
                reason=reason.reason,
            )
            for reason in response.tool_selection_reason
        ],
        evidence_gap=[
            EvidenceGap(
                gap=gap.gap,
                source=gap.source,
                severity=gap.severity,
                next_action=gap.next_action,
                blocking=gap.blocking,
            )
            for gap in response.evidence_gap
        ],
        confidence=response.confidence,
        suggested_actions=list(response.suggested_actions),
        evidence=[
            EvidenceRecord(
                evidence_id=evidence.evidence_id,
                evidence_type=evidence.evidence_type,
                source=evidence.source,
                source_type=evidence.source_type,
                source_label=evidence.source_label,
                source_agent=evidence.source_agent,
                source_tool=evidence.source_tool,
                summary=evidence.summary,
                payload=evidence.payload,
                confidence=evidence.confidence,
                status=evidence.status,
                tags=list(evidence.tags),
                observed_at=evidence.observed_at,
            )
            for evidence in response.evidence
        ],
        artifacts=dict(response.artifacts),
    )


def _serialize_session_record(session: SessionRecord) -> dict[str, object]:
    return {
        "session_id": session.session_id,
        "turns": [
            {
                "agent_name": turn.agent_name,
                "query": turn.query,
                "context": turn.context,
                "summary": turn.summary,
                "confidence": turn.confidence,
                "intent": turn.intent,
                "thought_summary": turn.thought_summary,
                "plan_steps": turn.plan_steps,
                "suggested_actions": turn.suggested_actions,
                "evidence": [
                    {
                        "evidence_id": evidence.evidence_id,
                        "evidence_type": evidence.evidence_type,
                        "source": evidence.source,
                        "source_type": evidence.source_type,
                        "source_label": evidence.source_label,
                        "source_agent": evidence.source_agent,
                        "source_tool": evidence.source_tool,
                        "summary": evidence.summary,
                        "payload": evidence.payload,
                        "confidence": evidence.confidence,
                        "status": evidence.status,
                        "tags": list(evidence.tags),
                        "observed_at": evidence.observed_at,
                    }
                    for evidence in turn.evidence
                ],
                "artifacts": turn.artifacts,
                "planner_trace": [
                    {
                        "step": trace.step,
                        "selected": trace.selected,
                        "reason": trace.reason,
                    }
                    for trace in turn.planner_trace
                ],
                "tool_selection_reason": [
                    {
                        "tool": reason.tool,
                        "selected": reason.selected,
                        "reason": reason.reason,
                    }
                    for reason in turn.tool_selection_reason
                ],
                "evidence_gap": [
                    {
                        "gap": gap.gap,
                        "source": gap.source,
                        "severity": gap.severity,
                        "next_action": gap.next_action,
                        "blocking": gap.blocking,
                    }
                    for gap in turn.evidence_gap
                ],
            }
            for turn in session.turns
        ],
    }


def _deserialize_session_record(payload: dict[str, object]) -> SessionRecord:
    turns = []
    for turn_payload in payload.get("turns", []):
        item = dict(turn_payload)
        turns.append(
            SessionTurn(
                agent_name=str(item["agent_name"]),
                query=str(item["query"]),
                context=dict(item.get("context", {})),
                summary=str(item["summary"]),
                confidence=float(item.get("confidence", 0.0)),
                intent=str(item["intent"]) if item.get("intent") is not None else None,
                thought_summary=str(item.get("thought_summary", "")),
                plan_steps=list(item.get("plan_steps", [])),
                suggested_actions=list(item.get("suggested_actions", [])),
                evidence=[
                    EvidenceRecord(
                        evidence_id=str(evidence.get("evidence_id", uuid.uuid4())),
                        evidence_type=str(evidence.get("evidence_type", "tool_result")),
                        source=str(evidence["source"]),
                        source_type=str(evidence["source_type"]),
                        source_label=str(evidence.get("source_label", evidence["source"])),
                        source_agent=(
                            str(evidence["source_agent"])
                            if evidence.get("source_agent") is not None
                            else None
                        ),
                        source_tool=(
                            str(evidence["source_tool"])
                            if evidence.get("source_tool") is not None
                            else None
                        ),
                        summary=str(evidence["summary"]),
                        payload=evidence.get("payload"),
                        confidence=float(evidence.get("confidence", 0.0)),
                        status=str(evidence.get("status", "active")),
                        tags=[str(tag) for tag in evidence.get("tags", [])],
                        observed_at=(
                            str(evidence["observed_at"])
                            if evidence.get("observed_at") is not None
                            else None
                        ),
                    )
                    for evidence in item.get("evidence", [])
                ],
                artifacts=dict(item.get("artifacts", {})),
                planner_trace=[
                    PlannerTraceStep(
                        step=str(trace["step"]),
                        selected=bool(trace["selected"]),
                        reason=str(trace["reason"]),
                    )
                    for trace in item.get("planner_trace", [])
                ],
                tool_selection_reason=[
                    ToolSelectionReason(
                        tool=str(reason["tool"]),
                        selected=bool(reason["selected"]),
                        reason=str(reason["reason"]),
                    )
                    for reason in item.get("tool_selection_reason", [])
                ],
                evidence_gap=[
                    EvidenceGap(
                        gap=str(gap["gap"]),
                        source=str(gap["source"]),
                        severity=str(gap.get("severity", "medium")),
                        next_action=str(gap.get("next_action", "")),
                        blocking=bool(gap.get("blocking", False)),
                    )
                    for gap in item.get("evidence_gap", [])
                ],
            )
        )
    return SessionRecord(session_id=str(payload["session_id"]), turns=turns)


def _deserialize_session_payload(payload: object) -> SessionRecord:
    if isinstance(payload, str):
        return _deserialize_session_record(json.loads(payload))
    if isinstance(payload, dict):
        return _deserialize_session_record(payload)
    raise TypeError("Unsupported session payload type")


def _session_json(session: SessionRecord) -> str:
    return json.dumps(
        _serialize_session_record(session),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _current_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00",
        "Z",
    )
