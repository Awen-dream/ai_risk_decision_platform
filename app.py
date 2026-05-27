from __future__ import annotations

from adapters.base import KnowledgeSource, ToolAdapter
from adapters.in_memory import (
    InMemoryCaseLookupAdapter,
    InMemoryKnowledgeSource,
    InMemoryMetricSnapshotAdapter,
    InMemoryOrderProfileAdapter,
)
from agents.investigation import InvestigationAgent
from agents.knowledge import KnowledgeAgent
from core.runtime import AgentRuntime
from core.session_store import InMemorySessionStore
from retrieval.knowledge_base import RetrievalService
from tools.registry import ToolRegistry


def build_demo_knowledge_sources() -> list[KnowledgeSource]:
    return [InMemoryKnowledgeSource()]


def build_demo_tool_adapters() -> list[ToolAdapter]:
    return [
        InMemoryMetricSnapshotAdapter(),
        InMemoryCaseLookupAdapter(),
        InMemoryOrderProfileAdapter(),
    ]


def build_demo_runtime() -> AgentRuntime:
    """Create a demo runtime with in-memory data and two risk agents."""

    retrieval = RetrievalService()
    for source in build_demo_knowledge_sources():
        retrieval.add_source(source)

    tools = ToolRegistry()
    for adapter in build_demo_tool_adapters():
        tools.register_adapter(adapter)

    runtime = AgentRuntime(session_store=InMemorySessionStore())
    runtime.register_agent(KnowledgeAgent(retrieval))
    runtime.register_agent(InvestigationAgent(tools, retrieval))
    return runtime
