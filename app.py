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
from clients.file import JsonCaseRecordClient, JsonMetricSnapshotSqlClient, JsonOrderProfileClient
from core.runtime import AgentRuntime
from core.session_store import InMemorySessionStore
from providers.in_memory import (
    InMemoryCaseRecordProvider,
    InMemoryMetricSnapshotProvider,
    InMemoryOrderProfileProvider,
)
from retrieval.knowledge_base import RetrievalService
from retrieval.file_source import DirectoryKnowledgeSource
from settings import AppConfig
from tools.registry import ToolRegistry


def build_knowledge_sources(config: AppConfig) -> list[KnowledgeSource]:
    if config.knowledge_backend == "file":
        return [DirectoryKnowledgeSource(config.knowledge_dir)]
    return [InMemoryKnowledgeSource()]


def build_tool_adapters(config: AppConfig) -> list[ToolAdapter]:
    if config.tool_backend == "file":
        metric_provider = InMemoryMetricSnapshotProvider(
            client=JsonMetricSnapshotSqlClient(config.metric_snapshot_path)
        )
        case_provider = InMemoryCaseRecordProvider(
            client=JsonCaseRecordClient(config.case_record_path)
        )
        order_provider = InMemoryOrderProfileProvider(
            client=JsonOrderProfileClient(config.order_profile_path)
        )
        return [
            InMemoryMetricSnapshotAdapter(provider=metric_provider),
            InMemoryCaseLookupAdapter(provider=case_provider),
            InMemoryOrderProfileAdapter(provider=order_provider),
        ]
    return [
        InMemoryMetricSnapshotAdapter(),
        InMemoryCaseLookupAdapter(),
        InMemoryOrderProfileAdapter(),
    ]


def build_runtime(config: AppConfig | None = None) -> AgentRuntime:
    """Create a runtime using the configured knowledge and tool backends."""
    config = config or AppConfig.from_env()

    retrieval = RetrievalService()
    for source in build_knowledge_sources(config):
        retrieval.add_source(source)

    tools = ToolRegistry()
    for adapter in build_tool_adapters(config):
        tools.register_adapter(adapter)

    runtime = AgentRuntime(session_store=InMemorySessionStore())
    runtime.register_agent(KnowledgeAgent(retrieval))
    runtime.register_agent(InvestigationAgent(tools, retrieval))
    return runtime


def build_demo_runtime() -> AgentRuntime:
    """Backward-compatible helper that builds the default runtime."""

    return build_runtime()
