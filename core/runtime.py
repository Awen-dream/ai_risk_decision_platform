from __future__ import annotations

from agents.base import Agent
from core.models import AgentRequest, AgentResponse
from core.session_store import InMemorySessionStore
from services.observability import bind_context, emit_event


class AgentRuntime:
    """Simple runtime for registering and executing agents by name."""

    def __init__(self, session_store: InMemorySessionStore | None = None) -> None:
        self._agents: dict[str, Agent] = {}
        self._session_store = session_store or InMemorySessionStore()

    def register_agent(self, agent: Agent) -> None:
        self._agents[agent.name] = agent

    def list_agents(self) -> list[str]:
        return list(self._agents)

    def execute(
        self,
        agent_name: str,
        request: AgentRequest,
        session_id: str | None = None,
    ) -> tuple[str, AgentResponse]:
        if agent_name not in self._agents:
            raise KeyError(f"Unknown agent: {agent_name}")
        session = self._session_store.ensure_session(session_id)
        with bind_context(session_id=session.session_id, agent_name=agent_name):
            emit_event(
                "agent_execution_started",
                provided_session_id=bool(session_id),
            )
            response = self._agents[agent_name].run(request)
            session = self._session_store.append_turn(session.session_id, request, response)
            emit_event(
                "agent_execution_completed",
                confidence=response.confidence,
                tool_trace_count=len(response.tool_traces),
            )
        return session.session_id, response

    def create_session(self) -> str:
        session_id = self._session_store.create_session().session_id
        with bind_context(session_id=session_id):
            emit_event("session_created")
        return session_id

    def get_session(self, session_id: str):
        return self._session_store.get_session(session_id)
