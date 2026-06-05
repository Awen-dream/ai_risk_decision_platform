from __future__ import annotations

from typing import Any, Iterable

from adapters.base import KnowledgeSource, ToolAdapter
from core.models import KnowledgeDocument, ToolResult
from providers.base import (
    CaseRecordProvider,
    GraphRelationProvider,
    MetricSnapshotProvider,
    OrderProfileProvider,
    StrategyProfileProvider,
    StrategySimulationProvider,
)
from providers.in_memory import (
    InMemoryCaseRecordProvider,
    InMemoryGraphRelationProvider,
    InMemoryMetricSnapshotProvider,
    InMemoryOrderProfileProvider,
    InMemoryStrategyProfileProvider,
    InMemoryStrategySimulationProvider,
)
from sample_data import (
    build_knowledge_documents,
)


def _missing_fields(payload: dict[str, Any], required_fields: tuple[str, ...]) -> list[str]:
    return [field for field in required_fields if field not in payload]


def _invalid_payload_result(
    tool_name: str,
    payload: Any,
    *,
    missing_fields: list[str],
) -> ToolResult:
    field_list = ", ".join(missing_fields)
    return ToolResult.failed_result(
        name=tool_name,
        payload=payload,
        summary="上游返回字段不完整",
        error=f"Invalid payload for {tool_name}, missing fields: {field_list}",
        error_type="invalid_payload",
    )


class InMemoryKnowledgeSource(KnowledgeSource):
    """Knowledge source backed by local demo documents."""

    def load(self) -> Iterable[KnowledgeDocument]:
        return build_knowledge_documents()


class InMemoryMetricSnapshotAdapter(ToolAdapter):
    name = "metric_snapshot"

    def __init__(self, provider: MetricSnapshotProvider | None = None) -> None:
        self._provider = provider or InMemoryMetricSnapshotProvider()

    def invoke(self, **kwargs: Any) -> ToolResult:
        country = str(kwargs["country"])
        channel = str(kwargs["channel"])
        time_range = str(kwargs["time_range"])
        payload = self._provider.get_snapshot(
            country=country,
            channel=channel,
            time_range=time_range,
        )
        if payload is None:
            return ToolResult.degraded_result(
                name=self.name,
                payload={},
                summary="未找到对应指标快照",
                error=f"No snapshot for {country}/{channel} in {time_range}",
                error_type="not_found",
            )
        missing_fields = _missing_fields(
            payload,
            (
                "country",
                "channel",
                "metric_name",
                "anomaly_started_at",
                "current_value",
                "baseline_value",
                "recent_change",
                "suspected_driver",
            ),
        )
        if missing_fields:
            return _invalid_payload_result(
                self.name,
                payload,
                missing_fields=missing_fields,
            )
        return ToolResult.success_result(
            name=self.name,
            payload=payload,
            summary=f"已返回 {payload['country']} {payload['channel']} {time_range} 的指标快照",
        )


class InMemoryCaseLookupAdapter(ToolAdapter):
    name = "case_lookup"

    def __init__(self, provider: CaseRecordProvider | None = None) -> None:
        self._provider = provider or InMemoryCaseRecordProvider()

    def invoke(self, **kwargs: Any) -> ToolResult:
        payload = self._provider.get_cases(
            country=str(kwargs["country"]),
            channel=str(kwargs["channel"]),
        )
        if not payload:
            return ToolResult.degraded_result(
                name=self.name,
                payload=[],
                summary="未找到历史相似案例",
                error="No historical cases matched the current dimensions",
                error_type="not_found",
            )
        required_fields = ("case_id", "country", "channel", "title")
        for row in payload:
            missing_fields = _missing_fields(row, required_fields)
            if missing_fields:
                return _invalid_payload_result(
                    self.name,
                    payload,
                    missing_fields=missing_fields,
                )
        return ToolResult.success_result(
            name=self.name,
            payload=payload,
            summary=f"返回 {len(payload)} 条历史相似案例",
        )


class InMemoryOrderProfileAdapter(ToolAdapter):
    name = "order_profile"

    def __init__(self, provider: OrderProfileProvider | None = None) -> None:
        self._provider = provider or InMemoryOrderProfileProvider()

    def invoke(self, **kwargs: Any) -> ToolResult:
        order_id = str(kwargs["order_id"])
        payload = self._provider.get_order(order_id)
        if payload is None:
            return ToolResult.degraded_result(
                name=self.name,
                payload={},
                summary="未找到订单画像",
                error=f"Unknown order: {order_id}",
                error_type="not_found",
            )
        missing_fields = _missing_fields(
            payload,
            (
                "order_id",
                "country",
                "channel",
                "recent_attempts",
                "triggered_rules",
                "risk_labels",
                "recommended_action",
            ),
        )
        if missing_fields:
            return _invalid_payload_result(
                self.name,
                payload,
                missing_fields=missing_fields,
            )
        return ToolResult.success_result(
            name=self.name,
            payload=payload,
            summary=f"已返回订单 {order_id} 的风险画像",
        )


class InMemoryStrategyProfileAdapter(ToolAdapter):
    name = "strategy_profile"

    def __init__(self, provider: StrategyProfileProvider | None = None) -> None:
        self._provider = provider or InMemoryStrategyProfileProvider()

    def invoke(self, **kwargs: Any) -> ToolResult:
        strategy_id = str(kwargs["strategy_id"])
        payload = self._provider.get_strategy(strategy_id)
        if payload is None:
            return ToolResult.degraded_result(
                name=self.name,
                payload={},
                summary="未找到策略画像",
                error=f"Unknown strategy: {strategy_id}",
                error_type="not_found",
            )
        missing_fields = _missing_fields(
            payload,
            (
                "strategy_id",
                "name",
                "country",
                "channel",
                "status",
                "current_threshold",
                "hit_rate",
                "risk_capture_rate",
                "false_positive_rate",
                "recent_issue",
                "top_impacted_entities",
            ),
        )
        if missing_fields:
            return _invalid_payload_result(
                self.name,
                payload,
                missing_fields=missing_fields,
            )
        return ToolResult.success_result(
            name=self.name,
            payload=payload,
            summary=f"已返回策略 {strategy_id} 的画像",
        )


class InMemoryStrategySimulationAdapter(ToolAdapter):
    name = "strategy_simulation"

    def __init__(self, provider: StrategySimulationProvider | None = None) -> None:
        self._provider = provider or InMemoryStrategySimulationProvider()

    def invoke(self, **kwargs: Any) -> ToolResult:
        strategy_id = str(kwargs["strategy_id"])
        payload = self._provider.get_simulation(strategy_id)
        if payload is None:
            return ToolResult.degraded_result(
                name=self.name,
                payload={},
                summary="未找到策略仿真结果",
                error=f"Unknown strategy simulation: {strategy_id}",
                error_type="not_found",
            )
        missing_fields = _missing_fields(
            payload,
            (
                "strategy_id",
                "recommended_threshold",
                "delta_intercepts",
                "delta_false_positives",
                "estimated_risk_reduction",
                "estimated_revenue_impact",
                "simulation_window",
                "recommendation_reason",
            ),
        )
        if missing_fields:
            return _invalid_payload_result(
                self.name,
                payload,
                missing_fields=missing_fields,
            )
        return ToolResult.success_result(
            name=self.name,
            payload=payload,
            summary=f"已返回策略 {strategy_id} 的仿真结果",
        )


class InMemoryGraphRelationAdapter(ToolAdapter):
    name = "graph_relation"

    def __init__(self, provider: GraphRelationProvider | None = None) -> None:
        self._provider = provider or InMemoryGraphRelationProvider()

    def invoke(self, **kwargs: Any) -> ToolResult:
        entity_id = str(kwargs["entity_id"])
        payload = self._provider.get_graph_relation(entity_id)
        if payload is None:
            return ToolResult.degraded_result(
                name=self.name,
                payload={},
                summary="未找到图关系结果",
                error=f"Unknown graph relation: {entity_id}",
                error_type="not_found",
            )
        missing_fields = _missing_fields(
            payload,
            (
                "entity_id",
                "entity_type",
                "risk_level",
                "shared_devices",
                "shared_ips",
                "linked_accounts",
                "linked_orders",
                "community_size",
                "key_path",
                "risk_reason",
            ),
        )
        if missing_fields:
            return _invalid_payload_result(
                self.name,
                payload,
                missing_fields=missing_fields,
            )
        return ToolResult.success_result(
            name=self.name,
            payload=payload,
            summary=f"已返回实体 {entity_id} 的图关系结果",
        )
