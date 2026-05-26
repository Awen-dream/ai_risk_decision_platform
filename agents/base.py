from __future__ import annotations

from abc import ABC, abstractmethod

from core.models import AgentRequest, AgentResponse


class Agent(ABC):
    """Base class for all agents executed by the runtime."""

    name: str

    @abstractmethod
    def run(self, request: AgentRequest) -> AgentResponse:
        """Execute the agent for the provided request."""
