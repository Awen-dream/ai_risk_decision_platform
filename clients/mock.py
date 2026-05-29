from __future__ import annotations

from typing import Any, Dict, List, Optional

from clients.base import (
    CaseRecordClient,
    GraphRelationClient,
    MetricSnapshotClient,
    OrderProfileClient,
    StrategyProfileClient,
    StrategySimulationClient,
)
from sample_data import (
    build_case_records,
    build_metric_snapshots,
    build_order_profiles,
    build_graph_relations,
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
    ) -> Optional[Dict[str, Any]]:
        return self._snapshots.get((country.upper(), channel.lower()))


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
