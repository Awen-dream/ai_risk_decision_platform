from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from clients.base import CaseRecordClient, MetricSnapshotClient, OrderProfileClient


class JsonMetricSnapshotSqlClient(MetricSnapshotClient):
    """Pseudo-SQL client backed by a JSON table."""

    def __init__(self, file_path: Path) -> None:
        self._file_path = file_path

    def fetch_metric_snapshot(
        self,
        country: str,
        channel: str,
    ) -> Optional[Dict[str, Any]]:
        rows = self.query(
            table="metric_snapshots",
            filters={"country": country.upper(), "channel": channel.lower()},
        )
        return rows[0] if rows else None

    def query(self, table: str, filters: Dict[str, Any]) -> List[Dict[str, Any]]:
        if table != "metric_snapshots":
            return []
        rows = self._load_rows()
        result: List[Dict[str, Any]] = []
        for row in rows:
            if all(row.get(key) == value for key, value in filters.items()):
                result.append(row)
        return result

    def _load_rows(self) -> List[Dict[str, Any]]:
        with self._file_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return list(data)


class JsonCaseRecordClient(CaseRecordClient):
    def __init__(self, file_path: Path) -> None:
        self._file_path = file_path

    def fetch_case_records(self, country: str, channel: str) -> List[Dict[str, Any]]:
        rows = self._load_rows()
        return [
            row
            for row in rows
            if row.get("country") == country.upper()
            and row.get("channel") == channel.lower()
        ]

    def _load_rows(self) -> List[Dict[str, Any]]:
        with self._file_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return list(data)


class JsonOrderProfileClient(OrderProfileClient):
    def __init__(self, file_path: Path) -> None:
        self._file_path = file_path

    def fetch_order_profile(self, order_id: str) -> Optional[Dict[str, Any]]:
        rows = self._load_rows()
        return rows.get(order_id)

    def _load_rows(self) -> Dict[str, Dict[str, Any]]:
        with self._file_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return dict(data)

