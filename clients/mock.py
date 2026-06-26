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
from sample_data import (
    build_case_records,
    build_dashboard_snapshots,
    build_metric_snapshots,
    build_order_profiles,
    build_graph_relations,
    build_rule_explanations,
    build_sql_query_results,
    build_strategy_profiles,
    build_strategy_simulations,
)


class MockMetricSnapshotClient(MetricSnapshotClient):
    """Mock client backed by local sample data."""

    def __init__(self) -> None:
        self._snapshots = build_metric_snapshots()

    def fetch_metric_snapshot(
        self,
        country: str,
        channel: str,
        time_range: str = "recent_24h",
    ) -> Optional[Dict[str, Any]]:
        return self._snapshots.get((country.upper(), channel.lower(), time_range))


class MockCaseRecordClient(CaseRecordClient):
    """Mock client backed by local sample data."""

    def __init__(self) -> None:
        self._records = build_case_records()

    def fetch_case_records(self, country: str, channel: str) -> List[Dict[str, Any]]:
        return list(self._records.get((country.upper(), channel.lower()), []))


class MockOrderProfileClient(OrderProfileClient):
    """Mock client backed by local sample data."""

    def __init__(self) -> None:
        self._orders = build_order_profiles()

    def fetch_order_profile(self, order_id: str) -> Optional[Dict[str, Any]]:
        return self._orders.get(order_id)


class MockStrategyProfileClient(StrategyProfileClient):
    """Mock client backed by local sample data."""

    def __init__(self) -> None:
        self._strategies = build_strategy_profiles()

    def fetch_strategy_profile(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        return self._strategies.get(strategy_id)


class MockStrategySimulationClient(StrategySimulationClient):
    """Mock client backed by local sample data."""

    def __init__(self) -> None:
        self._simulations = build_strategy_simulations()

    def fetch_strategy_simulation(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        return self._simulations.get(strategy_id)


class MockGraphRelationClient(GraphRelationClient):
    """Mock client backed by local sample data."""

    def __init__(self) -> None:
        self._relations = build_graph_relations()

    def fetch_graph_relation(self, entity_id: str) -> Optional[Dict[str, Any]]:
        return self._relations.get(entity_id)


class MockSqlQueryClient(SqlQueryClient):
    """Mock client backed by local sample data."""

    def __init__(self) -> None:
        self._results = build_sql_query_results()

    def fetch_sql_query(
        self,
        query_name: str,
        parameters: Dict[str, Any],
        limit: int = 50,
    ) -> Optional[Dict[str, Any]]:
        key = (
            query_name,
            str(parameters.get("country", "")).upper(),
            str(parameters.get("channel", "")).lower(),
            str(parameters.get("time_range", "recent_24h")),
        )
        payload = self._results.get(key)
        if payload is None:
            return None
        result = dict(payload)
        result["rows"] = list(payload.get("rows", []))[:limit]
        result["row_count"] = len(result["rows"])
        result["limit"] = limit
        return result


class MockDashboardSnapshotClient(DashboardSnapshotClient):
    """Mock client backed by local sample data."""

    def __init__(self) -> None:
        self._snapshots = build_dashboard_snapshots()

    def fetch_dashboard_snapshot(
        self,
        dashboard_id: str,
        country: str,
        channel: str,
        time_range: str = "recent_24h",
    ) -> Optional[Dict[str, Any]]:
        return self._snapshots.get(
            (dashboard_id, country.upper(), channel.lower(), time_range)
        )


class MockRuleExplainClient(RuleExplainClient):
    """Mock client backed by local sample data."""

    def __init__(self) -> None:
        self._explanations = build_rule_explanations()

    def fetch_rule_explanation(
        self,
        *,
        rule_id: str | None = None,
        order_id: str | None = None,
        strategy_id: str | None = None,
    ) -> Optional[Dict[str, Any]]:
        if order_id:
            return self._explanations.get(f"order:{order_id}")
        if strategy_id:
            return self._explanations.get(f"strategy:{strategy_id}")
        if rule_id:
            return self._explanations.get(f"rule:{rule_id}")
        return None
