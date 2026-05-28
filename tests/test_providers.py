from __future__ import annotations

import unittest

from providers.in_memory import (
    InMemoryCaseRecordProvider,
    InMemoryMetricSnapshotProvider,
    InMemoryOrderProfileProvider,
    InMemoryStrategyProfileProvider,
    InMemoryStrategySimulationProvider,
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

    def test_strategy_providers_return_strategy_data(self) -> None:
        profile_provider = InMemoryStrategyProfileProvider()
        simulation_provider = InMemoryStrategySimulationProvider()

        profile = profile_provider.get_strategy("STRAT-001")
        simulation = simulation_provider.get_simulation("STRAT-001")

        self.assertIsNotNone(profile)
        self.assertEqual(profile["status"], "active")
        self.assertIsNotNone(simulation)
        self.assertEqual(simulation["simulation_window"], "recent_14d")


if __name__ == "__main__":
    unittest.main()
