from __future__ import annotations

from typing import Any, Dict, List, Optional

from clients.base import (
    CaseRecordClient,
    MetricSnapshotClient,
    OrderProfileClient,
    StrategyProfileClient,
    StrategySimulationClient,
)
from clients.mock import (
    MockCaseRecordClient,
    MockMetricSnapshotClient,
    MockOrderProfileClient,
    MockStrategyProfileClient,
    MockStrategySimulationClient,
)
from providers.base import (
    CaseRecordProvider,
    MetricSnapshotProvider,
    OrderProfileProvider,
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
        del time_range
        return self._client.fetch_metric_snapshot(country=country, channel=channel)


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
