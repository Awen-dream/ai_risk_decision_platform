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

