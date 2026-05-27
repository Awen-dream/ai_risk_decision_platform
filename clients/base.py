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

