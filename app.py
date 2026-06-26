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
from agents.copilot import CopilotAgent
from agents.copilot_planner import CopilotPlanner, RuleBasedCopilotPlanner
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
    HttpResiliencePolicy,
    HttpStrategyProfileClient,
    HttpStrategySimulationClient,
)
from core.runtime import AgentRuntime
from core.session_store import (
    FileSessionStore,
    InMemorySessionStore,
    PostgresSessionStore,
    SessionStore,
    SQLiteSessionStore,
)
from providers.in_memory import (
    InMemoryCaseRecordProvider,
    InMemoryGraphRelationProvider,
    InMemoryMetricSnapshotProvider,
    InMemoryOrderProfileProvider,
    InMemoryStrategyProfileProvider,
    InMemoryStrategySimulationProvider,
)
from retrieval.knowledge_base import RetrievalService
from services.case_service import (
    CaseService,
    FileCaseService,
    InMemoryCaseService,
    PostgresCaseService,
    SQLiteCaseService,
)
from services.audit import (
    AuditLog,
    CompositeAuditLog,
    HttpAuditSink,
    JsonLinesAuditLog,
    NoopAuditLog,
)
from retrieval.file_source import DirectoryKnowledgeSource
from services.knowledge_sync import KnowledgeSyncService
from services.risk_decision import RiskDecisionPolicy
from settings import AppConfig
from tools.registry import ToolRegistry


@dataclass
class AppContainer:
    config: AppConfig
    runtime: AgentRuntime
    retrieval: RetrievalService
    tools: ToolRegistry
    knowledge_sync_service: KnowledgeSyncService
    case_service: CaseService
    audit_log: AuditLog


def build_knowledge_sources(config: AppConfig) -> list[KnowledgeSource]:
    if config.knowledge_backend == "file":
        return [DirectoryKnowledgeSource(config.knowledge_dir)]
    return [InMemoryKnowledgeSource()]


def build_tool_adapters(
    config: AppConfig,
    audit_log: AuditLog | None = None,
) -> list[ToolAdapter]:
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
        http_resilience = HttpResiliencePolicy(
            retry_attempts=config.tool_http_retry_attempts,
            retry_backoff_sec=config.tool_http_retry_backoff_sec,
            circuit_breaker_failure_threshold=(
                config.tool_http_circuit_breaker_failure_threshold
            ),
            circuit_breaker_reset_sec=config.tool_http_circuit_breaker_reset_sec,
        )
        metric_provider = InMemoryMetricSnapshotProvider(
            client=HttpMetricSnapshotClient(
                config.tool_http_base_url,
                path=config.tool_http_metric_path,
                country_param=config.tool_http_country_param,
                channel_param=config.tool_http_channel_param,
                headers=http_headers,
                timeout_sec=config.tool_http_timeout_sec,
                resilience=http_resilience,
                audit_log=audit_log,
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
                resilience=http_resilience,
                audit_log=audit_log,
            )
        )
        order_provider = InMemoryOrderProfileProvider(
            client=HttpOrderProfileClient(
                config.tool_http_base_url,
                path_template=config.tool_http_order_path_template,
                headers=http_headers,
                timeout_sec=config.tool_http_timeout_sec,
                resilience=http_resilience,
                audit_log=audit_log,
            )
        )
        strategy_provider = InMemoryStrategyProfileProvider(
            client=HttpStrategyProfileClient(
                config.tool_http_base_url,
                path_template=config.tool_http_strategy_profile_path_template,
                headers=http_headers,
                timeout_sec=config.tool_http_timeout_sec,
                resilience=http_resilience,
                audit_log=audit_log,
            )
        )
        simulation_provider = InMemoryStrategySimulationProvider(
            client=HttpStrategySimulationClient(
                config.tool_http_base_url,
                path_template=config.tool_http_strategy_simulation_path_template,
                headers=http_headers,
                timeout_sec=config.tool_http_timeout_sec,
                resilience=http_resilience,
                audit_log=audit_log,
            )
        )
        graph_provider = InMemoryGraphRelationProvider(
            client=HttpGraphRelationClient(
                config.tool_http_base_url,
                path_template=config.tool_http_graph_relation_path_template,
                headers=http_headers,
                timeout_sec=config.tool_http_timeout_sec,
                resilience=http_resilience,
                audit_log=audit_log,
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


def build_session_store(config: AppConfig) -> SessionStore:
    if config.session_store_backend == "postgres":
        return PostgresSessionStore(config.postgres_dsn)
    if config.session_store_backend == "sqlite":
        return SQLiteSessionStore(config.database_path)
    if config.session_store_backend == "file":
        return FileSessionStore(config.session_store_path)
    return InMemorySessionStore()


def build_copilot_planner(config: AppConfig) -> CopilotPlanner:
    if config.planner_backend == "rule":
        return RuleBasedCopilotPlanner()
    raise ValueError(f"Unsupported planner backend: {config.planner_backend}")


def build_case_service(config: AppConfig) -> CaseService:
    if config.case_store_backend == "postgres":
        return PostgresCaseService(config.postgres_dsn)
    if config.case_store_backend == "sqlite":
        return SQLiteCaseService(config.database_path)
    if config.case_store_backend == "file":
        return FileCaseService(config.case_store_path)
    return InMemoryCaseService()


def build_audit_log(config: AppConfig) -> AuditLog:
    if config.tool_http_audit_enabled:
        local_audit = JsonLinesAuditLog(
            config.tool_http_audit_path,
            max_bytes=config.tool_http_audit_max_bytes,
            max_files=config.tool_http_audit_max_files,
            integrity_enabled=config.tool_http_audit_integrity_enabled,
        )
        mirrors: list[AuditLog] = []
        if config.audit_central_enabled and config.audit_central_url:
            mirrors.append(
                HttpAuditSink(
                    config.audit_central_url,
                    headers=config.audit_central_headers(),
                    timeout_sec=config.audit_central_timeout_sec,
                )
            )
        if mirrors:
            return CompositeAuditLog(local_audit, mirrors)
        return local_audit
    return NoopAuditLog()


def build_app_container(config: AppConfig | None = None) -> AppContainer:
    """Create the application container using the configured backends."""
    config = config or AppConfig.from_env()

    retrieval = RetrievalService()
    knowledge_sources = build_knowledge_sources(config)
    for source in knowledge_sources:
        retrieval.add_source(source)

    audit_log = build_audit_log(config)
    tools = ToolRegistry()
    for adapter in build_tool_adapters(config, audit_log=audit_log):
        tools.register_adapter(adapter)

    runtime = AgentRuntime(session_store=build_session_store(config))
    knowledge_agent = KnowledgeAgent(retrieval)
    investigation_agent = InvestigationAgent(tools, retrieval)
    strategy_agent = StrategyAgent(tools, retrieval)
    graph_agent = GraphAgent(tools, retrieval)
    risk_decision_policy = (
        RiskDecisionPolicy.from_file(config.risk_decision_policy_path)
        if config.risk_decision_policy_path is not None
        else RiskDecisionPolicy.default()
    )
    copilot_agent = CopilotAgent(
        investigation_agent=investigation_agent,
        strategy_agent=strategy_agent,
        graph_agent=graph_agent,
        risk_decision_policy=risk_decision_policy,
        planner=build_copilot_planner(config),
    )
    runtime.register_agent(knowledge_agent)
    runtime.register_agent(investigation_agent)
    runtime.register_agent(strategy_agent)
    runtime.register_agent(graph_agent)
    runtime.register_agent(copilot_agent)
    return AppContainer(
        config=config,
        runtime=runtime,
        retrieval=retrieval,
        tools=tools,
        knowledge_sync_service=KnowledgeSyncService(retrieval, knowledge_sources),
        case_service=build_case_service(config),
        audit_log=audit_log,
    )


def build_runtime(config: AppConfig | None = None) -> AgentRuntime:
    """Create a runtime using the configured knowledge and tool backends."""

    return build_app_container(config).runtime


def build_demo_runtime() -> AgentRuntime:
    """Backward-compatible helper that builds the default runtime."""

    return build_runtime()
