from __future__ import annotations

import json
from pathlib import Path
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


class JsonMetricSnapshotSqlClient(MetricSnapshotClient):
    """Pseudo-SQL client backed by a JSON table."""

    def __init__(self, file_path: Path) -> None:
        self._file_path = file_path

    def fetch_metric_snapshot(
        self,
        country: str,
        channel: str,
        time_range: str = "recent_24h",
    ) -> Optional[Dict[str, Any]]:
        rows = self.query(
            table="metric_snapshots",
            filters={
                "country": country.upper(),
                "channel": channel.lower(),
                "time_range": time_range,
            },
        )
        if not rows:
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


class JsonStrategyProfileClient(StrategyProfileClient):
    def __init__(self, file_path: Path) -> None:
        self._file_path = file_path

    def fetch_strategy_profile(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        rows = self._load_rows()
        return rows.get(strategy_id)

    def _load_rows(self) -> Dict[str, Dict[str, Any]]:
        with self._file_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return dict(data)


class JsonStrategySimulationClient(StrategySimulationClient):
    def __init__(self, file_path: Path) -> None:
        self._file_path = file_path

    def fetch_strategy_simulation(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        rows = self._load_rows()
        return rows.get(strategy_id)

    def _load_rows(self) -> Dict[str, Dict[str, Any]]:
        with self._file_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return dict(data)


class JsonGraphRelationClient(GraphRelationClient):
    def __init__(self, file_path: Path) -> None:
        self._file_path = file_path

    def fetch_graph_relation(self, entity_id: str) -> Optional[Dict[str, Any]]:
        rows = self._load_rows()
        return rows.get(entity_id)

    def _load_rows(self) -> Dict[str, Dict[str, Any]]:
        with self._file_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return dict(data)


class JsonSqlQueryClient(SqlQueryClient):
    def __init__(self, file_path: Path) -> None:
        self._file_path = file_path

    def fetch_sql_query(
        self,
        query_name: str,
        parameters: Dict[str, Any],
        limit: int = 50,
    ) -> Optional[Dict[str, Any]]:
        rows = self._load_rows()
        country = str(parameters.get("country", "")).upper()
        channel = str(parameters.get("channel", "")).lower()
        time_range = str(parameters.get("time_range", "recent_24h"))
        for item in rows:
            if (
                item.get("query_name") == query_name
                and item.get("country") == country
                and item.get("channel") == channel
                and item.get("time_range") == time_range
            ):
                payload = dict(item)
                payload["rows"] = list(item.get("rows", []))[:limit]
                payload["row_count"] = len(payload["rows"])
                payload["limit"] = limit
                return payload
        return None

    def _load_rows(self) -> List[Dict[str, Any]]:
        with self._file_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return list(data)


class JsonDashboardSnapshotClient(DashboardSnapshotClient):
    def __init__(self, file_path: Path) -> None:
        self._file_path = file_path

    def fetch_dashboard_snapshot(
        self,
        dashboard_id: str,
        country: str,
        channel: str,
        time_range: str = "recent_24h",
    ) -> Optional[Dict[str, Any]]:
        for item in self._load_rows():
            if (
                item.get("dashboard_id") == dashboard_id
                and item.get("country") == country.upper()
                and item.get("channel") == channel.lower()
                and item.get("time_range") == time_range
            ):
                return item
        return None

    def _load_rows(self) -> List[Dict[str, Any]]:
        with self._file_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return list(data)


class JsonRuleExplainClient(RuleExplainClient):
    def __init__(self, file_path: Path) -> None:
        self._file_path = file_path

    def fetch_rule_explanation(
        self,
        *,
        rule_id: str | None = None,
        order_id: str | None = None,
        strategy_id: str | None = None,
    ) -> Optional[Dict[str, Any]]:
        rows = self._load_rows()
        if order_id is not None:
            return rows.get(f"order:{order_id}")
        if strategy_id is not None:
            return rows.get(f"strategy:{strategy_id}")
        if rule_id is not None:
            return rows.get(f"rule:{rule_id}")
        return None

    def _load_rows(self) -> Dict[str, Dict[str, Any]]:
        with self._file_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return dict(data)
