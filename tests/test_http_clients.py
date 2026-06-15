from __future__ import annotations

import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request

from app import build_tool_adapters
from clients.http import (
    CircuitBreakerOpenError,
    HttpCaseRecordClient,
    HttpGraphRelationClient,
    HttpMetricSnapshotClient,
    HttpOrderProfileClient,
    HttpResiliencePolicy,
    HttpStrategyProfileClient,
    HttpStrategySimulationClient,
)
from services.observability import bind_context, get_gauges_snapshot
from settings import AppConfig


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

        with bind_context(request_id="req-123", trace_id="trace-456"):
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
                snapshot = client.fetch_metric_snapshot("BR", "credit_card", "recent_7d")

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot["metric_name"], "payment_failure_rate")
        request = mocked.call_args[0][0]
        self.assertIsInstance(request, Request)
        self.assertIn("metric-snapshots?country=BR&channel=credit_card&time_range=recent_7d", request.full_url)
        self.assertEqual(request.headers["X-request-id"], "req-123")
        self.assertEqual(request.headers["X-trace-id"], "trace-456")

    def test_case_record_http_client(self) -> None:
        client = HttpCaseRecordClient("http://risk-service.local")

        with patch(
            "clients.http.urlopen",
            return_value=_FakeResponse([{"case_id": "BR-1", "title": "巴西案例"}]),
        ) as mocked:
            records = client.fetch_case_records("BR", "credit_card")

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["case_id"], "BR-1")
        request = mocked.call_args[0][0]
        self.assertIn("case-records?country=BR&channel=credit_card", request.full_url)

    def test_order_profile_http_client(self) -> None:
        client = HttpOrderProfileClient("http://risk-service.local")

        with patch(
            "clients.http.urlopen",
            return_value=_FakeResponse({"order_id": "O10001", "country": "BR"}),
        ) as mocked:
            order = client.fetch_order_profile("O10001")

        self.assertIsNotNone(order)
        self.assertEqual(order["country"], "BR")
        request = mocked.call_args[0][0]
        self.assertIn("order-profiles/O10001", request.full_url)

    def test_http_clients_handle_404(self) -> None:
        metric_client = HttpMetricSnapshotClient("http://risk-service.local")
        order_client = HttpOrderProfileClient("http://risk-service.local")
        strategy_client = HttpStrategyProfileClient("http://risk-service.local")

        http_error = HTTPError(
            url="http://risk-service.local/order-profiles/missing",
            code=404,
            msg="not found",
            hdrs=None,
            fp=None,
        )
        with patch("clients.http.urlopen", side_effect=http_error) as mocked:
            self.assertIsNone(metric_client.fetch_metric_snapshot("BR", "wallet"))
            self.assertIsNone(order_client.fetch_order_profile("missing"))
            self.assertIsNone(strategy_client.fetch_strategy_profile("missing"))
        self.assertEqual(mocked.call_count, 3)

    def test_metric_snapshot_http_client_raises_non_404_http_error(self) -> None:
        client = HttpMetricSnapshotClient(
            "http://risk-service.local",
            resilience=HttpResiliencePolicy(retry_backoff_sec=0),
        )
        http_error = HTTPError(
            url="http://risk-service.local/metric-snapshots",
            code=503,
            msg="service unavailable",
            hdrs=None,
            fp=None,
        )

        with patch("clients.http.urlopen", side_effect=http_error):
            with self.assertRaises(HTTPError):
                client.fetch_metric_snapshot("BR", "credit_card", "recent_24h")

    def test_metric_snapshot_http_client_propagates_network_error(self) -> None:
        client = HttpMetricSnapshotClient(
            "http://risk-service.local",
            resilience=HttpResiliencePolicy(retry_backoff_sec=0),
        )

        with patch("clients.http.urlopen", side_effect=URLError("timeout")):
            with self.assertRaises(URLError):
                client.fetch_metric_snapshot("BR", "credit_card", "recent_24h")

    def test_http_client_retries_transient_failure_then_succeeds(self) -> None:
        client = HttpMetricSnapshotClient(
            "http://risk-service.local",
            resilience=HttpResiliencePolicy(
                retry_attempts=2,
                retry_backoff_sec=0,
            ),
        )
        http_error = HTTPError(
            url="http://risk-service.local/metric-snapshots",
            code=503,
            msg="service unavailable",
            hdrs=None,
            fp=None,
        )

        with patch(
            "clients.http.urlopen",
            side_effect=[
                http_error,
                _FakeResponse({"metric_name": "payment_failure_rate"}),
            ],
        ) as mocked:
            snapshot = client.fetch_metric_snapshot("BR", "credit_card")

        self.assertEqual(snapshot["metric_name"], "payment_failure_rate")
        self.assertEqual(mocked.call_count, 2)

    def test_http_client_opens_circuit_after_repeated_failures(self) -> None:
        client = HttpMetricSnapshotClient(
            "http://risk-service.local",
            resilience=HttpResiliencePolicy(
                retry_attempts=0,
                circuit_breaker_failure_threshold=2,
                circuit_breaker_reset_sec=30,
            ),
        )

        with patch("clients.http.urlopen", side_effect=URLError("timeout")) as mocked:
            with self.assertRaises(URLError):
                client.fetch_metric_snapshot("BR", "credit_card")
            with self.assertRaises(URLError):
                client.fetch_metric_snapshot("BR", "credit_card")
            with self.assertRaises(CircuitBreakerOpenError):
                client.fetch_metric_snapshot("BR", "credit_card")

        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(
            get_gauges_snapshot()[
                "upstream.circuit.HttpMetricSnapshotClient.open"
            ],
            1.0,
        )

    def test_http_client_allows_half_open_probe_after_reset(self) -> None:
        client = HttpMetricSnapshotClient(
            "http://risk-service.local",
            resilience=HttpResiliencePolicy(
                retry_attempts=0,
                circuit_breaker_failure_threshold=1,
                circuit_breaker_reset_sec=30,
            ),
        )

        with patch("clients.http.time.monotonic", side_effect=[100.0, 131.0]):
            with patch(
                "clients.http.urlopen",
                side_effect=[
                    URLError("timeout"),
                    _FakeResponse({"metric_name": "payment_failure_rate"}),
                ],
            ) as mocked:
                with self.assertRaises(URLError):
                    client.fetch_metric_snapshot("BR", "credit_card")
                snapshot = client.fetch_metric_snapshot("BR", "credit_card")

        self.assertEqual(snapshot["metric_name"], "payment_failure_rate")
        self.assertEqual(mocked.call_count, 2)

    def test_non_retryable_half_open_response_closes_circuit(self) -> None:
        client = HttpMetricSnapshotClient(
            "http://risk-service.local",
            resilience=HttpResiliencePolicy(
                retry_attempts=0,
                circuit_breaker_failure_threshold=1,
                circuit_breaker_reset_sec=30,
            ),
        )
        http_error = HTTPError(
            url="http://risk-service.local/metric-snapshots",
            code=404,
            msg="not found",
            hdrs=None,
            fp=None,
        )

        with patch("clients.http.time.monotonic", side_effect=[100.0, 131.0]):
            with patch(
                "clients.http.urlopen",
                side_effect=[
                    URLError("timeout"),
                    http_error,
                    _FakeResponse({"metric_name": "payment_failure_rate"}),
                ],
            ) as mocked:
                with self.assertRaises(URLError):
                    client.fetch_metric_snapshot("BR", "credit_card")
                self.assertIsNone(client.fetch_metric_snapshot("BR", "credit_card"))
                snapshot = client.fetch_metric_snapshot("BR", "credit_card")

        self.assertEqual(snapshot["metric_name"], "payment_failure_rate")
        self.assertEqual(mocked.call_count, 3)

    def test_http_adapter_build_uses_configured_resilience_policy(self) -> None:
        adapters = build_tool_adapters(
            AppConfig(
                tool_backend="http",
                tool_http_retry_attempts=0,
                tool_http_circuit_breaker_failure_threshold=1,
                tool_http_circuit_breaker_reset_sec=60,
            )
        )

        with patch("clients.http.urlopen", side_effect=URLError("timeout")) as mocked:
            with self.assertRaises(URLError):
                adapters[0].invoke(
                    country="BR",
                    channel="credit_card",
                    time_range="recent_24h",
                )
            with self.assertRaises(CircuitBreakerOpenError):
                adapters[0].invoke(
                    country="BR",
                    channel="credit_card",
                    time_range="recent_24h",
                )

        self.assertEqual(mocked.call_count, 1)

    def test_http_clients_support_custom_paths_and_headers(self) -> None:
        metric_client = HttpMetricSnapshotClient(
            "http://risk-service.local",
            path="/v2/metrics",
            country_param="market",
            channel_param="payment_channel",
            headers={"X-API-Key": "secret"},
            timeout_sec=9.0,
        )
        case_client = HttpCaseRecordClient(
            "http://risk-service.local",
            path="/v2/cases/search",
            country_param="market",
            channel_param="payment_channel",
            headers={"X-API-Key": "secret"},
            timeout_sec=9.0,
        )
        order_client = HttpOrderProfileClient(
            "http://risk-service.local",
            path_template="/v2/orders/{order_id}/profile",
            headers={"X-API-Key": "secret"},
            timeout_sec=9.0,
        )

        with patch(
            "clients.http.urlopen",
            return_value=_FakeResponse({"country": "BR", "channel": "credit_card"}),
        ) as mocked_metric:
            metric_client.fetch_metric_snapshot("BR", "credit_card", "recent_24h")
        with patch(
            "clients.http.urlopen",
            return_value=_FakeResponse([{"case_id": "BR-1", "title": "巴西案例"}]),
        ) as mocked_case:
            case_client.fetch_case_records("BR", "credit_card")
        with patch(
            "clients.http.urlopen",
            return_value=_FakeResponse({"order_id": "O10001", "country": "BR"}),
        ) as mocked_order:
            order_client.fetch_order_profile("O10001")

        metric_request = mocked_metric.call_args[0][0]
        metric_timeout = mocked_metric.call_args[1]["timeout"]
        case_request = mocked_case.call_args[0][0]
        order_request = mocked_order.call_args[0][0]

        self.assertIn("/v2/metrics?market=BR&payment_channel=credit_card&time_range=recent_24h", metric_request.full_url)
        self.assertEqual(metric_request.headers["X-api-key"], "secret")
        self.assertEqual(metric_timeout, 9.0)
        self.assertIn("/v2/cases/search?market=BR&payment_channel=credit_card", case_request.full_url)
        self.assertIn("/v2/orders/O10001/profile", order_request.full_url)

    def test_strategy_http_clients_support_custom_paths(self) -> None:
        profile_client = HttpStrategyProfileClient(
            "http://risk-service.local",
            path_template="/v3/strategies/{strategy_id}",
            headers={"X-API-Key": "secret"},
        )
        simulation_client = HttpStrategySimulationClient(
            "http://risk-service.local",
            path_template="/v3/strategies/{strategy_id}/simulation",
        )

        with patch(
            "clients.http.urlopen",
            return_value=_FakeResponse({"strategy_id": "STRAT-001", "status": "active"}),
        ) as mocked_profile:
            profile = profile_client.fetch_strategy_profile("STRAT-001")
        with patch(
            "clients.http.urlopen",
            return_value=_FakeResponse({"strategy_id": "STRAT-001", "recommended_threshold": 0.66}),
        ) as mocked_simulation:
            simulation = simulation_client.fetch_strategy_simulation("STRAT-001")

        self.assertEqual(profile["strategy_id"], "STRAT-001")
        self.assertEqual(simulation["recommended_threshold"], 0.66)
        self.assertIn("/v3/strategies/STRAT-001", mocked_profile.call_args[0][0].full_url)
        self.assertIn("/v3/strategies/STRAT-001/simulation", mocked_simulation.call_args[0][0].full_url)

    def test_graph_http_client_supports_custom_path(self) -> None:
        client = HttpGraphRelationClient(
            "http://risk-service.local",
            path_template="/v3/graph/{entity_id}",
            headers={"Authorization": "Bearer token"},
        )

        with patch(
            "clients.http.urlopen",
            return_value=_FakeResponse({"entity_id": "U10001", "risk_level": "high"}),
        ) as mocked:
            relation = client.fetch_graph_relation("U10001")

        self.assertEqual(relation["entity_id"], "U10001")
        self.assertIn("/v3/graph/U10001", mocked.call_args[0][0].full_url)

    def test_graph_http_client_handles_404(self) -> None:
        client = HttpGraphRelationClient("http://risk-service.local")
        http_error = HTTPError(
            url="http://risk-service.local/graph-relations/missing",
            code=404,
            msg="not found",
            hdrs=None,
            fp=None,
        )

        with patch("clients.http.urlopen", side_effect=http_error):
            self.assertIsNone(client.fetch_graph_relation("missing"))


if __name__ == "__main__":
    unittest.main()
