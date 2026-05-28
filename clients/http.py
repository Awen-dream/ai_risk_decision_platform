from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from clients.base import (
    CaseRecordClient,
    MetricSnapshotClient,
    OrderProfileClient,
    StrategyProfileClient,
    StrategySimulationClient,
)


class BaseHttpJsonClient:
    """Small configurable JSON-over-HTTP client."""

    def __init__(
        self,
        base_url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        timeout_sec: float = 5.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = headers or {}
        self._timeout_sec = timeout_sec

    def _join_url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self._base_url}{path}"

    def _get_json(self, path: str) -> Any:
        request = Request(
            self._join_url(path),
            headers=self._headers,
            method="GET",
        )
        with urlopen(request, timeout=self._timeout_sec) as response:
            return json.load(response)


class HttpMetricSnapshotClient(BaseHttpJsonClient, MetricSnapshotClient):
    def __init__(
        self,
        base_url: str,
        *,
        path: str = "/metric-snapshots",
        country_param: str = "country",
        channel_param: str = "channel",
        headers: Optional[Dict[str, str]] = None,
        timeout_sec: float = 5.0,
    ) -> None:
        super().__init__(base_url, headers=headers, timeout_sec=timeout_sec)
        self._path = path
        self._country_param = country_param
        self._channel_param = channel_param

    def fetch_metric_snapshot(
        self,
        country: str,
        channel: str,
    ) -> Optional[Dict[str, Any]]:
        query = urlencode(
            {
                self._country_param: country.upper(),
                self._channel_param: channel.lower(),
            }
        )
        try:
            return self._get_json(f"{self._path}?{query}")
        except HTTPError as exc:
            if exc.code == 404:
                return None
            raise

class HttpCaseRecordClient(BaseHttpJsonClient, CaseRecordClient):
    def __init__(
        self,
        base_url: str,
        *,
        path: str = "/case-records",
        country_param: str = "country",
        channel_param: str = "channel",
        headers: Optional[Dict[str, str]] = None,
        timeout_sec: float = 5.0,
    ) -> None:
        super().__init__(base_url, headers=headers, timeout_sec=timeout_sec)
        self._path = path
        self._country_param = country_param
        self._channel_param = channel_param

    def fetch_case_records(self, country: str, channel: str) -> List[Dict[str, Any]]:
        query = urlencode(
            {
                self._country_param: country.upper(),
                self._channel_param: channel.lower(),
            }
        )
        try:
            payload = self._get_json(f"{self._path}?{query}")
        except HTTPError as exc:
            if exc.code == 404:
                return []
            raise
        return list(payload)

class HttpOrderProfileClient(BaseHttpJsonClient, OrderProfileClient):
    def __init__(
        self,
        base_url: str,
        *,
        path_template: str = "/order-profiles/{order_id}",
        headers: Optional[Dict[str, str]] = None,
        timeout_sec: float = 5.0,
    ) -> None:
        super().__init__(base_url, headers=headers, timeout_sec=timeout_sec)
        self._path_template = path_template

    def fetch_order_profile(self, order_id: str) -> Optional[Dict[str, Any]]:
        try:
            return self._get_json(self._path_template.format(order_id=order_id))
        except HTTPError as exc:
            if exc.code == 404:
                return None
            raise


class HttpStrategyProfileClient(BaseHttpJsonClient, StrategyProfileClient):
    def __init__(
        self,
        base_url: str,
        *,
        path_template: str = "/strategy-profiles/{strategy_id}",
        headers: Optional[Dict[str, str]] = None,
        timeout_sec: float = 5.0,
    ) -> None:
        super().__init__(base_url, headers=headers, timeout_sec=timeout_sec)
        self._path_template = path_template

    def fetch_strategy_profile(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        try:
            return self._get_json(self._path_template.format(strategy_id=strategy_id))
        except HTTPError as exc:
            if exc.code == 404:
                return None
            raise


class HttpStrategySimulationClient(BaseHttpJsonClient, StrategySimulationClient):
    def __init__(
        self,
        base_url: str,
        *,
        path_template: str = "/strategy-simulations/{strategy_id}",
        headers: Optional[Dict[str, str]] = None,
        timeout_sec: float = 5.0,
    ) -> None:
        super().__init__(base_url, headers=headers, timeout_sec=timeout_sec)
        self._path_template = path_template

    def fetch_strategy_simulation(self, strategy_id: str) -> Optional[Dict[str, Any]]:
        try:
            return self._get_json(self._path_template.format(strategy_id=strategy_id))
        except HTTPError as exc:
            if exc.code == 404:
                return None
            raise
