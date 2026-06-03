from __future__ import annotations

import uuid

from core.models import AgentRequest, AgentResponse, PlannerTraceStep, SessionRecord, SessionTurn


class InMemorySessionStore:
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
        session.turns.append(
            SessionTurn(
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
        )
        return session
