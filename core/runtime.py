from __future__ import annotations

from agents.base import Agent
from core.models import AgentRequest, AgentResponse


class AgentRuntime:
    """Simple runtime for registering and executing agents by name."""

    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}

    def register_agent(self, agent: Agent) -> None:
        self._agents[agent.name] = agent

    def execute(self, agent_name: str, request: AgentRequest) -> AgentResponse:
        if agent_name not in self._agents:
            raise KeyError(f"Unknown agent: {agent_name}")
        return self._agents[agent_name].run(request)
