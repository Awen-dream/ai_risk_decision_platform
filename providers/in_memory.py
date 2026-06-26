from __future__ import annotations

from typing import Any, Dict, List, Optional

from clients.base import (
    CaseRecordClient,
    DashboardSnapshotClient,
    GraphRelationClient,
    MetricSnapshotClient,
    OrderProfileClient,
    RuleExplainClient,
    SqlQueryClient,
    StrategyProfileClient,
    StrategySimulationClient,
)
from clients.mock import (
    MockCaseRecordClient,
    MockDashboardSnapshotClient,
    MockGraphRelationClient,
    MockMetricSnapshotClient,
    MockOrderProfileClient,
    MockRuleExplainClient,
    MockSqlQueryClient,
    MockStrategyProfileClient,
    MockStrategySimulationClient,
)
from providers.base import (
    CaseRecordProvider,
    DashboardSnapshotProvider,
    GraphRelationProvider,
    MetricSnapshotProvider,
    OrderProfileProvider,
    RuleExplainProvider,
    SqlQueryProvider,
    StrategyProfileProvider,
    StrategySimulationProvider,
)


class InMemoryMetricSnapshotProvider(MetricSnapshotProvider):
    def __init__(self, client: MetricSnapshotClient | None = None) -> None:
        self._client = client or MockMetricSnapshotClient()

    def get_snapshot(
        self,
        country: str,
        channel: str,
        time_range: str,
    ) -> Optional[Dict[str, Any]]:
        return self._client.fetch_metric_snapshot(
            country=country,
            channel=channel,
            time_range=time_range,
        )


class InMemoryCaseRecordProvider(CaseRecordProvider):
    def __init__(self, client: CaseRecordClient | None = None) -> None:
        self._client = client or MockCaseRecordClient()

    def get_cases(self, country: str, channel: str) -> List[Dict[str, Any]]:
        return self._client.fetch_case_records(country=country, channel=channel)


class InMemoryOrderProfileProvider(OrderProfileProvider):
    def __init__(self, client: OrderProfileClient | None = None) -> None:
        self._client = client or MockOrderProfileClient()

    def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        return self._client.fetch_order_profile(order_id=order_id)


class InMemoryStrategyProfileProvider(StrategyProfileProvider):
    def __init__(self, client: StrategyProfileClient | None = None) -> None:
        self._client = client or MockStrategyProfileClient()

    def get_strategy(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        return self._client.fetch_strategy_profile(strategy_id=strategy_id)


class InMemoryStrategySimulationProvider(StrategySimulationProvider):
    def __init__(self, client: StrategySimulationClient | None = None) -> None:
        self._client = client or MockStrategySimulationClient()

    def get_simulation(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        return self._client.fetch_strategy_simulation(strategy_id=strategy_id)


class InMemoryGraphRelationProvider(GraphRelationProvider):
    def __init__(self, client: GraphRelationClient | None = None) -> None:
        self._client = client or MockGraphRelationClient()

    def get_graph_relation(self, entity_id: str) -> Optional[Dict[str, Any]]:
        return self._client.fetch_graph_relation(entity_id=entity_id)


class InMemorySqlQueryProvider(SqlQueryProvider):
    def __init__(self, client: SqlQueryClient | None = None) -> None:
        self._client = client or MockSqlQueryClient()

    def get_query_result(
        self,
        query_name: str,
        parameters: Dict[str, Any],
        limit: int = 50,
    ) -> Optional[Dict[str, Any]]:
        return self._client.fetch_sql_query(
            query_name=query_name,
            parameters=parameters,
            limit=limit,
        )


class InMemoryDashboardSnapshotProvider(DashboardSnapshotProvider):
    def __init__(self, client: DashboardSnapshotClient | None = None) -> None:
        self._client = client or MockDashboardSnapshotClient()

    def get_dashboard_snapshot(
        self,
        dashboard_id: str,
        country: str,
        channel: str,
        time_range: str,
    ) -> Optional[Dict[str, Any]]:
        return self._client.fetch_dashboard_snapshot(
            dashboard_id=dashboard_id,
            country=country,
            channel=channel,
            time_range=time_range,
        )


class InMemoryRuleExplainProvider(RuleExplainProvider):
    def __init__(self, client: RuleExplainClient | None = None) -> None:
        self._client = client or MockRuleExplainClient()

    def get_rule_explanation(
        self,
        *,
        rule_id: str | None = None,
        order_id: str | None = None,
        strategy_id: str | None = None,
    ) -> Optional[Dict[str, Any]]:
        return self._client.fetch_rule_explanation(
            rule_id=rule_id,
            order_id=order_id,
            strategy_id=strategy_id,
        )
