from __future__ import annotations

import unittest

from settings import AppConfig


class SettingsTests(unittest.TestCase):
    def test_bearer_auth_headers(self) -> None:
        config = AppConfig(
            tool_http_auth_mode="bearer",
            tool_http_auth_token="secret-token",
            tool_http_auth_header="Authorization",
        )

        self.assertEqual(
            config.tool_http_headers(),
            {"Authorization": "Bearer secret-token"},
        )

    def test_api_key_auth_headers(self) -> None:
        config = AppConfig(
            tool_http_auth_mode="api_key",
            tool_http_auth_token="secret-key",
            tool_http_auth_header="X-API-Key",
        )

        self.assertEqual(
            config.tool_http_headers(),
            {"X-API-Key": "secret-key"},
        )

    def test_local_http_stack_profile(self) -> None:
        config = AppConfig.local_http_stack()

        self.assertEqual(config.knowledge_backend, "file")
        self.assertEqual(config.tool_backend, "http")
        self.assertEqual(config.tool_http_base_url, "http://127.0.0.1:8090")
        self.assertEqual(config.session_store_backend, "memory")

    def test_supported_capabilities_cover_phase1_surface(self) -> None:
        config = AppConfig.local_http_stack()

        self.assertEqual(
            config.supported_agent_capabilities(),
            ["knowledge", "investigation", "strategy", "graph", "copilot"],
        )
        capability_contract = config.capability_contract()
        self.assertEqual(
            [item["name"] for item in capability_contract],
            ["knowledge", "investigation", "strategy", "graph", "copilot"],
        )
        self.assertEqual(capability_contract[1]["required_tools"], ["metric_snapshot", "case_lookup", "order_profile"])
        self.assertEqual(capability_contract[4]["composed_agents"], ["investigation", "strategy", "graph"])

    def test_http_endpoint_contract_covers_phase1_tools(self) -> None:
        config = AppConfig.local_http_stack()

        endpoint_contract = config.http_endpoint_contract()
        self.assertEqual(
            [item["tool_name"] for item in endpoint_contract],
            [
                "metric_snapshot",
                "case_lookup",
                "order_profile",
                "strategy_profile",
                "strategy_simulation",
                "graph_relation",
            ],
        )
        self.assertEqual(
            endpoint_contract[0]["query_params"],
            {
                "country_env_var": "AI_RISK_TOOL_HTTP_COUNTRY_PARAM",
                "country_name": "country",
                "channel_env_var": "AI_RISK_TOOL_HTTP_CHANNEL_PARAM",
                "channel_name": "channel",
            },
        )
        self.assertEqual(
            endpoint_contract[-1]["supports_capabilities"],
            ["strategy", "graph", "copilot"],
        )


if __name__ == "__main__":
    unittest.main()
