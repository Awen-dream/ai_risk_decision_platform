from __future__ import annotations

import json
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

from core.models import AgentRequest, AgentResponse, PlannerTraceStep, SessionRecord, SessionTurn


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


def build_session_turn(request: AgentRequest, response: AgentResponse) -> SessionTurn:
    return SessionTurn(
        agent_name=response.agent_name,
        query=request.query,
        context=request.context,
        summary=response.summary,
        intent=response.intent,
        plan_steps=response.plan_steps,
        planner_trace=[
            PlannerTraceStep(
                step=trace.step,
                selected=trace.selected,
                reason=trace.reason,
            )
            for trace in response.planner_trace
        ],
        confidence=response.confidence,
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
                "plan_steps": turn.plan_steps,
                "planner_trace": [
                    {
                        "step": trace.step,
                        "selected": trace.selected,
                        "reason": trace.reason,
                    }
                    for trace in turn.planner_trace
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
                plan_steps=list(item.get("plan_steps", [])),
                planner_trace=[
                    PlannerTraceStep(
                        step=str(trace["step"]),
                        selected=bool(trace["selected"]),
                        reason=str(trace["reason"]),
                    )
                    for trace in item.get("planner_trace", [])
                ],
            )
        )
    return SessionRecord(session_id=str(payload["session_id"]), turns=turns)
