from __future__ import annotations

import unittest
from pathlib import Path

from clients.file import (
    JsonCaseRecordClient,
    JsonGraphRelationClient,
    JsonMetricSnapshotSqlClient,
    JsonOrderProfileClient,
    JsonStrategyProfileClient,
    JsonStrategySimulationClient,
)
from clients.mock import (
    MockCaseRecordClient,
    MockGraphRelationClient,
    MockMetricSnapshotClient,
    MockOrderProfileClient,
    MockStrategyProfileClient,
    MockStrategySimulationClient,
)


class MockClientTests(unittest.TestCase):
    def test_metric_snapshot_client_returns_snapshot(self) -> None:
        client = MockMetricSnapshotClient()

        snapshot = client.fetch_metric_snapshot("BR", "credit_card")

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot["metric_name"], "payment_failure_rate")

    def test_metric_snapshot_client_supports_time_range(self) -> None:
        client = MockMetricSnapshotClient()

        snapshot = client.fetch_metric_snapshot("BR", "credit_card", "recent_7d")

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot["time_range"], "recent_7d")
        self.assertEqual(snapshot["current_value"], "9.8%")

    def test_case_record_client_returns_records(self) -> None:
        client = MockCaseRecordClient()

        records = client.fetch_case_records("BR", "credit_card")

        self.assertEqual(len(records), 1)
        self.assertIn("阈值过严", records[0]["title"])

    def test_order_profile_client_returns_none_for_missing_order(self) -> None:
        client = MockOrderProfileClient()

        order = client.fetch_order_profile("missing")

        self.assertIsNone(order)

    def test_json_metric_snapshot_sql_client_filters_rows(self) -> None:
        client = JsonMetricSnapshotSqlClient(Path("data/risk/metric_snapshots.json"))

        rows = client.query(
            table="metric_snapshots",
            filters={"country": "BR", "channel": "credit_card", "time_range": "recent_7d"},
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["metric_name"], "payment_failure_rate")
        self.assertEqual(rows[0]["time_range"], "recent_7d")

    def test_json_case_record_client_loads_cases(self) -> None:
        client = JsonCaseRecordClient(Path("data/risk/case_records.json"))

        rows = client.fetch_case_records("ID", "wallet")

        self.assertEqual(len(rows), 1)
        self.assertIn("印尼钱包", rows[0]["title"])

    def test_json_order_profile_client_loads_order(self) -> None:
        client = JsonOrderProfileClient(Path("data/risk/order_profiles.json"))

        row = client.fetch_order_profile("O20001")

        self.assertIsNotNone(row)
        self.assertEqual(row["country"], "US")

    def test_mock_strategy_clients_return_payloads(self) -> None:
        profile_client = MockStrategyProfileClient()
        simulation_client = MockStrategySimulationClient()

        profile = profile_client.fetch_strategy_profile("STRAT-001")
        simulation = simulation_client.fetch_strategy_simulation("STRAT-001")

        self.assertIsNotNone(profile)
        self.assertEqual(profile["country"], "BR")
        self.assertIsNotNone(simulation)
        self.assertEqual(simulation["recommended_threshold"], 0.66)

    def test_json_strategy_clients_load_strategy_data(self) -> None:
        profile_client = JsonStrategyProfileClient(Path("data/risk/strategy_profiles.json"))
        simulation_client = JsonStrategySimulationClient(Path("data/risk/strategy_simulations.json"))

        profile = profile_client.fetch_strategy_profile("STRAT-002")
        simulation = simulation_client.fetch_strategy_simulation("STRAT-002")

        self.assertIsNotNone(profile)
        self.assertEqual(profile["channel"], "wallet")
        self.assertEqual(profile["top_impacted_entities"], ["U10001"])
        self.assertIsNotNone(simulation)
        self.assertEqual(simulation["strategy_id"], "STRAT-002")

    def test_mock_graph_relation_client_returns_payload(self) -> None:
        client = MockGraphRelationClient()

        relation = client.fetch_graph_relation("U10001")

        self.assertIsNotNone(relation)
        self.assertEqual(relation["risk_level"], "high")

    def test_json_graph_relation_client_loads_graph_data(self) -> None:
        client = JsonGraphRelationClient(Path("data/risk/graph_relations.json"))

        relation = client.fetch_graph_relation("O10001")

        self.assertIsNotNone(relation)
        self.assertEqual(relation["entity_type"], "order")


if __name__ == "__main__":
    unittest.main()
