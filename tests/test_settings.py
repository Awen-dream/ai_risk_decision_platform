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


if __name__ == "__main__":
    unittest.main()
