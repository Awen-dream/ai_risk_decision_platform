from __future__ import annotations

import unittest

from providers.in_memory import (
    InMemoryCaseRecordProvider,
    InMemoryMetricSnapshotProvider,
    InMemoryOrderProfileProvider,
)


class ProviderTests(unittest.TestCase):
    def test_metric_snapshot_provider_returns_snapshot(self) -> None:
        provider = InMemoryMetricSnapshotProvider()

        snapshot = provider.get_snapshot("BR", "credit_card", "recent_24h")

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot["country"], "BR")

    def test_case_record_provider_returns_list(self) -> None:
        provider = InMemoryCaseRecordProvider()

        cases = provider.get_cases("ID", "wallet")

        self.assertEqual(len(cases), 1)
        self.assertIn("印尼钱包", cases[0]["title"])

    def test_order_profile_provider_returns_none_for_unknown_order(self) -> None:
        provider = InMemoryOrderProfileProvider()

        order = provider.get_order("MISSING")

        self.assertIsNone(order)


if __name__ == "__main__":
    unittest.main()
