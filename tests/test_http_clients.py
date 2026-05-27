from __future__ import annotations

import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from clients.http import HttpCaseRecordClient, HttpMetricSnapshotClient, HttpOrderProfileClient


class _FakeResponse:
    def __init__(self, payload) -> None:
        self._buffer = io.BytesIO(json.dumps(payload).encode("utf-8"))

    def __enter__(self):
        return self._buffer

    def __exit__(self, exc_type, exc, tb) -> None:
        self._buffer.close()


class HttpClientTests(unittest.TestCase):
    def test_metric_snapshot_http_client(self) -> None:
        client = HttpMetricSnapshotClient("http://risk-service.local")

        with patch(
            "clients.http.urlopen",
            return_value=_FakeResponse(
                {
                    "country": "BR",
                    "channel": "credit_card",
                    "metric_name": "payment_failure_rate",
                }
            ),
        ) as mocked:
            snapshot = client.fetch_metric_snapshot("BR", "credit_card")

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot["metric_name"], "payment_failure_rate")
        self.assertIn("metric-snapshots?country=BR&channel=credit_card", mocked.call_args[0][0])

    def test_case_record_http_client(self) -> None:
        client = HttpCaseRecordClient("http://risk-service.local")

        with patch(
            "clients.http.urlopen",
            return_value=_FakeResponse([{"case_id": "BR-1", "title": "巴西案例"}]),
        ) as mocked:
            records = client.fetch_case_records("BR", "credit_card")

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["case_id"], "BR-1")
        self.assertIn("case-records?country=BR&channel=credit_card", mocked.call_args[0][0])

    def test_order_profile_http_client(self) -> None:
        client = HttpOrderProfileClient("http://risk-service.local")

        with patch(
            "clients.http.urlopen",
            return_value=_FakeResponse({"order_id": "O10001", "country": "BR"}),
        ) as mocked:
            order = client.fetch_order_profile("O10001")

        self.assertIsNotNone(order)
        self.assertEqual(order["country"], "BR")
        self.assertIn("order-profiles/O10001", mocked.call_args[0][0])

    def test_http_clients_handle_404(self) -> None:
        metric_client = HttpMetricSnapshotClient("http://risk-service.local")
        order_client = HttpOrderProfileClient("http://risk-service.local")

        http_error = HTTPError(
            url="http://risk-service.local/order-profiles/missing",
            code=404,
            msg="not found",
            hdrs=None,
            fp=None,
        )
        with patch("clients.http.urlopen", side_effect=http_error):
            self.assertIsNone(metric_client.fetch_metric_snapshot("BR", "wallet"))
            self.assertIsNone(order_client.fetch_order_profile("missing"))


if __name__ == "__main__":
    unittest.main()
