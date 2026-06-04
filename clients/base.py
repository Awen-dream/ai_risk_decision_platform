from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple


class MetricSnapshotClient(ABC):
    """Client for fetching metric snapshots from a backing store."""

    @abstractmethod
    def fetch_metric_snapshot(
        self,
        country: str,
        channel: str,
        time_range: str = "recent_24h",
    ) -> Optional[Dict[str, Any]]:
        """Return the matching metric snapshot."""


class CaseRecordClient(ABC):
    """Client for fetching historical case records from a backing store."""

    @abstractmethod
    def fetch_case_records(self, country: str, channel: str) -> List[Dict[str, Any]]:
        """Return the case records for the given dimensions."""


class OrderProfileClient(ABC):
    """Client for fetching order profiles from a backing store."""

    @abstractmethod
    def fetch_order_profile(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Return the order profile for the given identifier."""


class StrategyProfileClient(ABC):
    """Client for fetching strategy profile data."""

    @abstractmethod
    def fetch_strategy_profile(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        """Return the strategy profile for the given identifier."""


class StrategySimulationClient(ABC):
    """Client for fetching strategy simulation results."""

    @abstractmethod
    def fetch_strategy_simulation(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        """Return the simulation output for the given strategy."""


class GraphRelationClient(ABC):
    """Client for fetching graph relation summaries."""

    @abstractmethod
    def fetch_graph_relation(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """Return graph relation data for the given entity."""
