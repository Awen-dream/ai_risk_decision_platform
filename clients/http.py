from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen

from clients.base import CaseRecordClient, MetricSnapshotClient, OrderProfileClient


class HttpMetricSnapshotClient(MetricSnapshotClient):
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    def fetch_metric_snapshot(
        self,
        country: str,
        channel: str,
    ) -> Optional[Dict[str, Any]]:
        query = urlencode({"country": country.upper(), "channel": channel.lower()})
        try:
            return self._get_json(f"{self._base_url}/metric-snapshots?{query}")
        except HTTPError as exc:
            if exc.code == 404:
                return None
            raise

    @staticmethod
    def _get_json(url: str) -> Dict[str, Any]:
        with urlopen(url) as response:
            return json.load(response)


class HttpCaseRecordClient(CaseRecordClient):
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    def fetch_case_records(self, country: str, channel: str) -> List[Dict[str, Any]]:
        query = urlencode({"country": country.upper(), "channel": channel.lower()})
        try:
            payload = self._get_json(f"{self._base_url}/case-records?{query}")
        except HTTPError as exc:
            if exc.code == 404:
                return []
            raise
        return list(payload)

    @staticmethod
    def _get_json(url: str) -> List[Dict[str, Any]]:
        with urlopen(url) as response:
            return json.load(response)


class HttpOrderProfileClient(OrderProfileClient):
    def __init__(self, base_url: str) -> None:
        self._base_url = base_url.rstrip("/")

    def fetch_order_profile(self, order_id: str) -> Optional[Dict[str, Any]]:
        try:
            return self._get_json(f"{self._base_url}/order-profiles/{order_id}")
        except HTTPError as exc:
            if exc.code == 404:
                return None
            raise

    @staticmethod
    def _get_json(url: str) -> Dict[str, Any]:
        with urlopen(url) as response:
            return json.load(response)
