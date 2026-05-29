from __future__ import annotations

from dataclasses import dataclass

from adapters.base import KnowledgeSource, ToolAdapter
from adapters.in_memory import (
    InMemoryCaseLookupAdapter,
    InMemoryGraphRelationAdapter,
    InMemoryKnowledgeSource,
    InMemoryMetricSnapshotAdapter,
    InMemoryOrderProfileAdapter,
    InMemoryStrategyProfileAdapter,
    InMemoryStrategySimulationAdapter,
)
from agents.graph import GraphAgent
from agents.investigation import InvestigationAgent
from agents.knowledge import KnowledgeAgent
from agents.strategy import StrategyAgent
from clients.file import (
    JsonCaseRecordClient,
    JsonGraphRelationClient,
    JsonMetricSnapshotSqlClient,
    JsonOrderProfileClient,
    JsonStrategyProfileClient,
    JsonStrategySimulationClient,
)
from clients.http import (
    HttpCaseRecordClient,
    HttpGraphRelationClient,
    HttpMetricSnapshotClient,
    HttpOrderProfileClient,
    HttpStrategyProfileClient,
    HttpStrategySimulationClient,
)
from core.runtime import AgentRuntime
from core.session_store import InMemorySessionStore
from providers.in_memory import (
    InMemoryCaseRecordProvider,
    InMemoryGraphRelationProvider,
    InMemoryMetricSnapshotProvider,
    InMemoryOrderProfileProvider,
    InMemoryStrategyProfileProvider,
    InMemoryStrategySimulationProvider,
)
from retrieval.knowledge_base import RetrievalService
from retrieval.file_source import DirectoryKnowledgeSource
from services.knowledge_sync import KnowledgeSyncService
from settings import AppConfig
from tools.registry import ToolRegistry


@dataclass
class AppContainer:
    config: AppConfig
    runtime: AgentRuntime
    retrieval: RetrievalService
    tools: ToolRegistry
    knowledge_sync_service: KnowledgeSyncService


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
        strategy_provider = InMemoryStrategyProfileProvider(
            client=JsonStrategyProfileClient(config.strategy_profile_path)
        )
        simulation_provider = InMemoryStrategySimulationProvider(
            client=JsonStrategySimulationClient(config.strategy_simulation_path)
        )
        graph_provider = InMemoryGraphRelationProvider(
            client=JsonGraphRelationClient(config.graph_relation_path)
        )
        return [
            InMemoryMetricSnapshotAdapter(provider=metric_provider),
            InMemoryCaseLookupAdapter(provider=case_provider),
            InMemoryOrderProfileAdapter(provider=order_provider),
            InMemoryStrategyProfileAdapter(provider=strategy_provider),
            InMemoryStrategySimulationAdapter(provider=simulation_provider),
            InMemoryGraphRelationAdapter(provider=graph_provider),
        ]
    if config.tool_backend == "http":
        http_headers = config.tool_http_headers()
        metric_provider = InMemoryMetricSnapshotProvider(
            client=HttpMetricSnapshotClient(
                config.tool_http_base_url,
                path=config.tool_http_metric_path,
                country_param=config.tool_http_country_param,
                channel_param=config.tool_http_channel_param,
                headers=http_headers,
                timeout_sec=config.tool_http_timeout_sec,
            )
        )
        case_provider = InMemoryCaseRecordProvider(
            client=HttpCaseRecordClient(
                config.tool_http_base_url,
                path=config.tool_http_case_path,
                country_param=config.tool_http_country_param,
                channel_param=config.tool_http_channel_param,
                headers=http_headers,
                timeout_sec=config.tool_http_timeout_sec,
            )
        )
        order_provider = InMemoryOrderProfileProvider(
            client=HttpOrderProfileClient(
                config.tool_http_base_url,
                path_template=config.tool_http_order_path_template,
                headers=http_headers,
                timeout_sec=config.tool_http_timeout_sec,
            )
        )
        strategy_provider = InMemoryStrategyProfileProvider(
            client=HttpStrategyProfileClient(
                config.tool_http_base_url,
                path_template=config.tool_http_strategy_profile_path_template,
                headers=http_headers,
                timeout_sec=config.tool_http_timeout_sec,
            )
        )
        simulation_provider = InMemoryStrategySimulationProvider(
            client=HttpStrategySimulationClient(
                config.tool_http_base_url,
                path_template=config.tool_http_strategy_simulation_path_template,
                headers=http_headers,
                timeout_sec=config.tool_http_timeout_sec,
            )
        )
        graph_provider = InMemoryGraphRelationProvider(
            client=HttpGraphRelationClient(
                config.tool_http_base_url,
                path_template=config.tool_http_graph_relation_path_template,
                headers=http_headers,
                timeout_sec=config.tool_http_timeout_sec,
            )
        )
        return [
            InMemoryMetricSnapshotAdapter(provider=metric_provider),
            InMemoryCaseLookupAdapter(provider=case_provider),
            InMemoryOrderProfileAdapter(provider=order_provider),
            InMemoryStrategyProfileAdapter(provider=strategy_provider),
            InMemoryStrategySimulationAdapter(provider=simulation_provider),
            InMemoryGraphRelationAdapter(provider=graph_provider),
        ]
    return [
        InMemoryMetricSnapshotAdapter(),
        InMemoryCaseLookupAdapter(),
        InMemoryOrderProfileAdapter(),
        InMemoryStrategyProfileAdapter(),
        InMemoryStrategySimulationAdapter(),
        InMemoryGraphRelationAdapter(),
    ]


def build_app_container(config: AppConfig | None = None) -> AppContainer:
    """Create the application container using the configured backends."""
    config = config or AppConfig.from_env()

    retrieval = RetrievalService()
    knowledge_sources = build_knowledge_sources(config)
    for source in knowledge_sources:
        retrieval.add_source(source)

    tools = ToolRegistry()
    for adapter in build_tool_adapters(config):
        tools.register_adapter(adapter)

    runtime = AgentRuntime(session_store=InMemorySessionStore())
    runtime.register_agent(KnowledgeAgent(retrieval))
    runtime.register_agent(InvestigationAgent(tools, retrieval))
    runtime.register_agent(StrategyAgent(tools, retrieval))
    runtime.register_agent(GraphAgent(tools, retrieval))
    return AppContainer(
        config=config,
        runtime=runtime,
        retrieval=retrieval,
        tools=tools,
        knowledge_sync_service=KnowledgeSyncService(retrieval, knowledge_sources),
    )


def build_runtime(config: AppConfig | None = None) -> AgentRuntime:
    """Create a runtime using the configured knowledge and tool backends."""

    return build_app_container(config).runtime


def build_demo_runtime() -> AgentRuntime:
    """Backward-compatible helper that builds the default runtime."""

    return build_runtime()
