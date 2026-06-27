from __future__ import annotations

import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from risk_service import create_risk_service_app
from settings import AppConfig


class RiskServiceApiTests(unittest.TestCase):
    def setUp(self) -> None:
        app = create_risk_service_app(
            AppConfig(
                metric_snapshot_path=Path("data/risk/metric_snapshots.json"),
                case_record_path=Path("data/risk/case_records.json"),
                order_profile_path=Path("data/risk/order_profiles.json"),
                strategy_profile_path=Path("data/risk/strategy_profiles.json"),
                strategy_simulation_path=Path("data/risk/strategy_simulations.json"),
                graph_relation_path=Path("data/risk/graph_relations.json"),
            )
        )
        self.client = TestClient(app)

    def test_healthz(self) -> None:
        response = self.client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_metric_snapshot_endpoint(self) -> None:
        response = self.client.get(
            "/metric-snapshots",
            params={"country": "BR", "channel": "credit_card", "time_range": "recent_7d"},
        )

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["metric_name"], "payment_failure_rate")
        self.assertEqual(payload["time_range"], "recent_7d")
        self.assertEqual(payload["current_value"], "9.8%")

    def test_case_records_endpoint(self) -> None:
        response = self.client.get(
            "/case-records",
            params={"country": "ID", "channel": "wallet"},
        )

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(payload), 1)
        self.assertIn("印尼钱包", payload[0]["title"])

    def test_order_profile_endpoint(self) -> None:
        response = self.client.get("/order-profiles/O10001")

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["country"], "BR")

    def test_strategy_endpoints(self) -> None:
        profile_response = self.client.get("/strategy-profiles/STRAT-001")
        simulation_response = self.client.get("/strategy-simulations/STRAT-001")

        self.assertEqual(profile_response.status_code, 200)
        self.assertEqual(simulation_response.status_code, 200)
        self.assertEqual(profile_response.json()["name"], "Brazil Credit Card Velocity Guard")
        self.assertEqual(profile_response.json()["top_impacted_entities"], ["O10001", "U10001"])
        self.assertEqual(simulation_response.json()["recommended_threshold"], 0.66)

    def test_graph_relation_endpoint(self) -> None:
        response = self.client.get("/graph-relations/U10001")

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["risk_level"], "high")
        self.assertEqual(payload["community_size"], 5)

    def test_sql_query_endpoint(self) -> None:
        response = self.client.get(
            "/sql-queries/metric_breakdown",
            params={
                "country": "BR",
                "channel": "credit_card",
                "time_range": "recent_24h",
                "limit": 2,
            },
        )

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["query_name"], "metric_breakdown")
        self.assertEqual(payload["row_count"], 2)
        self.assertEqual(payload["limit"], 2)
        self.assertEqual(len(payload["rows"]), 2)

    def test_dashboard_snapshot_endpoint(self) -> None:
        response = self.client.get(
            "/dashboard-snapshots/risk_overview",
            params={"country": "BR", "channel": "credit_card", "time_range": "recent_24h"},
        )

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["dashboard_id"], "risk_overview")
        self.assertEqual(payload["trend"], "up")
        self.assertIn("device_risk", payload["recommended_drilldowns"])

    def test_rule_explanations_endpoint(self) -> None:
        response = self.client.get(
            "/rule-explanations",
            params={"strategy_id": "STRAT-001"},
        )

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["subject_id"], "STRAT-001")
        self.assertEqual(payload["subject_type"], "strategy")
        self.assertEqual(payload["strategy_id"], "STRAT-001")
        self.assertTrue(payload["hit_rules"])

    def test_not_found_cases(self) -> None:
        metric_response = self.client.get(
            "/metric-snapshots",
            params={"country": "JP", "channel": "wallet"},
        )
        case_response = self.client.get(
            "/case-records",
            params={"country": "JP", "channel": "wallet"},
        )
        order_response = self.client.get("/order-profiles/MISSING")
        graph_response = self.client.get("/graph-relations/MISSING")
        sql_response = self.client.get(
            "/sql-queries/metric_breakdown",
            params={"country": "JP", "channel": "wallet", "time_range": "recent_24h"},
        )
        dashboard_response = self.client.get(
            "/dashboard-snapshots/risk_overview",
            params={"country": "JP", "channel": "wallet", "time_range": "recent_24h"},
        )
        rule_response = self.client.get(
            "/rule-explanations",
            params={"strategy_id": "MISSING"},
        )

        self.assertEqual(metric_response.status_code, 404)
        self.assertEqual(case_response.status_code, 404)
        self.assertEqual(order_response.status_code, 404)
        self.assertEqual(graph_response.status_code, 404)
        self.assertEqual(sql_response.status_code, 404)
        self.assertEqual(dashboard_response.status_code, 404)
        self.assertEqual(rule_response.status_code, 404)

    def test_rule_explanations_requires_lookup_key(self) -> None:
        response = self.client.get("/rule-explanations")

        self.assertEqual(response.status_code, 400)

    def test_fault_control_endpoint_is_disabled_by_default(self) -> None:
        response = self.client.get("/admin/faults")

        self.assertEqual(response.status_code, 404)

    def test_enabled_fault_rule_is_finite_and_clearable(self) -> None:
        client = TestClient(
            create_risk_service_app(
                AppConfig(
                    risk_service_fault_injection_enabled=True,
                    metric_snapshot_path=Path("data/risk/metric_snapshots.json"),
                    case_record_path=Path("data/risk/case_records.json"),
                    order_profile_path=Path("data/risk/order_profiles.json"),
                    strategy_profile_path=Path("data/risk/strategy_profiles.json"),
                    strategy_simulation_path=Path("data/risk/strategy_simulations.json"),
                    graph_relation_path=Path("data/risk/graph_relations.json"),
                )
            )
        )
        configured = client.post(
            "/admin/faults",
            json={
                "target_path": "/metric-snapshots",
                "status_code": 503,
                "remaining": 1,
            },
        )

        injected = client.get(
            "/metric-snapshots",
            params={"country": "BR", "channel": "credit_card"},
        )
        recovered = client.get(
            "/metric-snapshots",
            params={"country": "BR", "channel": "credit_card"},
        )
        cleared = client.delete("/admin/faults")

        self.assertEqual(configured.status_code, 200)
        self.assertEqual(injected.status_code, 503)
        self.assertEqual(injected.headers["X-Fault-Injected"], "true")
        self.assertEqual(recovered.status_code, 200)
        self.assertEqual(cleared.json(), {"status": "cleared"})


if __name__ == "__main__":
    unittest.main()
