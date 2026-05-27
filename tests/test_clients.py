from __future__ import annotations

import unittest

from clients.mock import (
    MockCaseRecordClient,
    MockMetricSnapshotClient,
    MockOrderProfileClient,
)


class MockClientTests(unittest.TestCase):
    def test_metric_snapshot_client_returns_snapshot(self) -> None:
        client = MockMetricSnapshotClient()

        snapshot = client.fetch_metric_snapshot("BR", "credit_card")

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot["metric_name"], "payment_failure_rate")

    def test_case_record_client_returns_records(self) -> None:
        client = MockCaseRecordClient()

        records = client.fetch_case_records("BR", "credit_card")

        self.assertEqual(len(records), 1)
        self.assertIn("阈值过严", records[0]["title"])

    def test_order_profile_client_returns_none_for_missing_order(self) -> None:
        client = MockOrderProfileClient()

        order = client.fetch_order_profile("missing")

        self.assertIsNone(order)


if __name__ == "__main__":
    unittest.main()
