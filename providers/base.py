from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class MetricSnapshotProvider(ABC):
    """Provides raw metric snapshot data for investigation flows."""

    @abstractmethod
    def get_snapshot(
        self,
        country: str,
        channel: str,
        time_range: str,
    ) -> Optional[Dict[str, Any]]:
        """Return the metric snapshot for the given dimensions."""


class CaseRecordProvider(ABC):
    """Provides raw historical case records."""

    @abstractmethod
    def get_cases(self, country: str, channel: str) -> List[Dict[str, Any]]:
        """Return matching historical cases."""


class OrderProfileProvider(ABC):
    """Provides raw order profile data."""

    @abstractmethod
    def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Return the order profile for the given identifier."""


class StrategyProfileProvider(ABC):
    """Provides raw strategy profile data."""

    @abstractmethod
    def get_strategy(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        """Return the strategy profile for the given identifier."""


class StrategySimulationProvider(ABC):
    """Provides strategy simulation outputs."""

    @abstractmethod
    def get_simulation(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        """Return the simulation output for the given strategy."""


class GraphRelationProvider(ABC):
    """Provides graph relation analysis data."""

    @abstractmethod
    def get_graph_relation(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """Return graph relation data for the given entity."""
