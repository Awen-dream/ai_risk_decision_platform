from __future__ import annotations

from agents.investigation import InvestigationAgent
from agents.knowledge import KnowledgeAgent
from core.runtime import AgentRuntime
from core.session_store import InMemorySessionStore
from retrieval.knowledge_base import RetrievalService
from sample_data import (
    build_case_records,
    build_knowledge_documents,
    build_metric_snapshots,
    build_order_profiles,
)
from tools.registry import ToolRegistry


def build_demo_runtime() -> AgentRuntime:
    """Create a demo runtime with in-memory data and two risk agents."""

    retrieval = RetrievalService()
    retrieval.add_documents(build_knowledge_documents())

    tools = ToolRegistry()
    tools.register("metric_snapshot", build_metric_snapshots())
    tools.register("case_lookup", build_case_records())
    tools.register("order_profile", build_order_profiles())

    runtime = AgentRuntime(session_store=InMemorySessionStore())
    runtime.register_agent(KnowledgeAgent(retrieval))
    runtime.register_agent(InvestigationAgent(tools, retrieval))
    return runtime
