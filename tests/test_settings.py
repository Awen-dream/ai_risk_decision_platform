from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

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

    def test_auth_tokens_can_load_from_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tool_token_path = Path(tmp_dir) / "tool-token"
            admin_token_path = Path(tmp_dir) / "admin-token"
            tool_token_path.write_text("file-tool-secret\n", encoding="utf-8")
            admin_token_path.write_text("file-admin-secret\n", encoding="utf-8")
            with patch.dict(
                "os.environ",
                {
                    "AI_RISK_TOOL_HTTP_AUTH_MODE": "api_key",
                    "AI_RISK_TOOL_HTTP_AUTH_HEADER": "X-API-Key",
                    "AI_RISK_TOOL_HTTP_AUTH_TOKEN": "env-tool-secret",
                    "AI_RISK_TOOL_HTTP_AUTH_TOKEN_FILE": str(tool_token_path),
                    "AI_RISK_ADMIN_AUTH_ENABLED": "true",
                    "AI_RISK_ADMIN_AUTH_TOKEN": "env-admin-secret",
                    "AI_RISK_ADMIN_AUTH_TOKEN_FILE": str(admin_token_path),
                },
            ):
                config = AppConfig.from_env()

        self.assertEqual(config.tool_http_headers(), {"X-API-Key": "file-tool-secret"})
        self.assertEqual(config.tool_http_auth_token_source(), "file")
        self.assertTrue(config.admin_auth_enabled)
        self.assertEqual(config.admin_auth_token, "file-admin-secret")
        self.assertEqual(config.admin_auth_token_source(), "file")

    def test_local_http_stack_profile(self) -> None:
        config = AppConfig.local_http_stack()

        self.assertEqual(config.knowledge_backend, "file")
        self.assertEqual(config.tool_backend, "http")
        self.assertEqual(config.planner_backend, "rule")
        self.assertEqual(config.investigation_backend, "rule")
        self.assertEqual(config.tool_http_base_url, "http://127.0.0.1:8090")
        self.assertEqual(config.tool_http_retry_attempts, 2)
        self.assertEqual(config.tool_http_retry_backoff_sec, 0.1)
        self.assertEqual(config.tool_http_circuit_breaker_failure_threshold, 5)
        self.assertEqual(config.tool_http_circuit_breaker_reset_sec, 30.0)
        self.assertEqual(config.session_store_backend, "memory")
        self.assertEqual(config.case_store_backend, "memory")
        self.assertEqual(config.database_path, Path(".data/platform.db"))
        self.assertIsNone(config.risk_decision_policy_path)

    def test_risk_decision_policy_path_loads_from_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            policy_path = Path(tmp_dir) / "risk-decision-policy.json"
            policy_path.write_text("{}", encoding="utf-8")
            with patch.dict(
                "os.environ",
                {"AI_RISK_DECISION_POLICY_PATH": str(policy_path)},
            ):
                config = AppConfig.from_env()

        self.assertEqual(config.risk_decision_policy_path, policy_path)

    def test_planner_backend_loads_from_environment(self) -> None:
        with patch.dict(
            "os.environ",
            {"AI_RISK_PLANNER_BACKEND": "rule"},
        ):
            config = AppConfig.from_env()

        self.assertEqual(config.planner_backend, "rule")
        self.assertEqual(config.planner_source(), "rule")

    def test_openai_planner_settings_load_secret_from_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            key_path = Path(tmp_dir) / "planner-openai-key"
            key_path.write_text("planner-secret\n", encoding="utf-8")
            with patch.dict(
                "os.environ",
                {
                    "AI_RISK_PLANNER_BACKEND": "openai",
                    "AI_RISK_PLANNER_OPENAI_BASE_URL": "https://proxy.example.com/v1",
                    "AI_RISK_PLANNER_OPENAI_MODEL": "gpt-5.5",
                    "AI_RISK_PLANNER_OPENAI_TIMEOUT_SEC": "12.5",
                    "AI_RISK_PLANNER_OPENAI_REASONING_EFFORT": "medium",
                    "AI_RISK_PLANNER_OPENAI_MAX_OUTPUT_TOKENS": "512",
                    "AI_RISK_PLANNER_OPENAI_API_KEY_FILE": str(key_path),
                },
            ):
                config = AppConfig.from_env()

        self.assertEqual(config.planner_backend, "openai")
        self.assertEqual(config.planner_openai_base_url, "https://proxy.example.com/v1")
        self.assertEqual(config.planner_openai_model, "gpt-5.5")
        self.assertEqual(config.planner_openai_timeout_sec, 12.5)
        self.assertEqual(config.planner_openai_reasoning_effort, "medium")
        self.assertEqual(config.planner_openai_max_output_tokens, 512)
        self.assertEqual(config.planner_openai_api_key, "planner-secret")
        self.assertEqual(config.planner_openai_api_key_source(), "file")

    def test_openai_investigation_settings_load_secret_from_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            key_path = Path(tmp_dir) / "investigation-openai-key"
            key_path.write_text("investigation-secret\n", encoding="utf-8")
            with patch.dict(
                "os.environ",
                {
                    "AI_RISK_INVESTIGATION_BACKEND": "openai",
                    "AI_RISK_INVESTIGATION_OPENAI_BASE_URL": "https://investigation.example.com/v1",
                    "AI_RISK_INVESTIGATION_OPENAI_MODEL": "gpt-5-mini",
                    "AI_RISK_INVESTIGATION_OPENAI_TIMEOUT_SEC": "11.0",
                    "AI_RISK_INVESTIGATION_OPENAI_REASONING_EFFORT": "medium",
                    "AI_RISK_INVESTIGATION_OPENAI_MAX_OUTPUT_TOKENS": "450",
                    "AI_RISK_INVESTIGATION_OPENAI_API_KEY_FILE": str(key_path),
                },
            ):
                config = AppConfig.from_env()

        self.assertEqual(config.investigation_backend, "openai")
        self.assertEqual(config.investigation_openai_base_url, "https://investigation.example.com/v1")
        self.assertEqual(config.investigation_openai_model, "gpt-5-mini")
        self.assertEqual(config.investigation_openai_timeout_sec, 11.0)
        self.assertEqual(config.investigation_openai_reasoning_effort, "medium")
        self.assertEqual(config.investigation_openai_max_output_tokens, 450)
        self.assertEqual(config.investigation_openai_api_key, "investigation-secret")
        self.assertEqual(config.investigation_openai_api_key_source(), "file")

    def test_http_resilience_settings_load_from_environment(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "AI_RISK_TOOL_HTTP_RETRY_ATTEMPTS": "4",
                "AI_RISK_TOOL_HTTP_RETRY_BACKOFF_SEC": "0.25",
                "AI_RISK_TOOL_HTTP_CIRCUIT_BREAKER_FAILURE_THRESHOLD": "8",
                "AI_RISK_TOOL_HTTP_CIRCUIT_BREAKER_RESET_SEC": "45",
            },
        ):
            config = AppConfig.from_env()

        self.assertEqual(config.tool_http_retry_attempts, 4)
        self.assertEqual(config.tool_http_retry_backoff_sec, 0.25)
        self.assertEqual(config.tool_http_circuit_breaker_failure_threshold, 8)
        self.assertEqual(config.tool_http_circuit_breaker_reset_sec, 45.0)

    def test_http_audit_settings_load_from_environment(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "AI_RISK_TOOL_HTTP_AUDIT_ENABLED": "false",
                "AI_RISK_TOOL_HTTP_AUDIT_PATH": "/tmp/upstream-audit.jsonl",
                "AI_RISK_TOOL_HTTP_AUDIT_MAX_BYTES": "2048",
                "AI_RISK_TOOL_HTTP_AUDIT_MAX_FILES": "7",
                "AI_RISK_TOOL_HTTP_AUDIT_INTEGRITY_ENABLED": "false",
            },
        ):
            config = AppConfig.from_env()

        self.assertFalse(config.tool_http_audit_enabled)
        self.assertEqual(config.tool_http_audit_path, Path("/tmp/upstream-audit.jsonl"))
        self.assertEqual(config.tool_http_audit_max_bytes, 2048)
        self.assertEqual(config.tool_http_audit_max_files, 7)
        self.assertFalse(config.tool_http_audit_integrity_enabled)

    def test_central_audit_settings_load_secret_from_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            token_path = Path(tmp_dir) / "central-audit-token"
            token_path.write_text("central-secret\n", encoding="utf-8")
            with patch.dict(
                "os.environ",
                {
                    "AI_RISK_AUDIT_CENTRAL_ENABLED": "true",
                    "AI_RISK_AUDIT_CENTRAL_URL": "https://audit.example.com/events",
                    "AI_RISK_AUDIT_CENTRAL_TIMEOUT_SEC": "4.5",
                    "AI_RISK_AUDIT_CENTRAL_AUTH_HEADER": "X-Audit-Token",
                    "AI_RISK_AUDIT_CENTRAL_AUTH_TOKEN_FILE": str(token_path),
                },
            ):
                config = AppConfig.from_env()

        self.assertTrue(config.audit_central_enabled)
        self.assertEqual(config.audit_central_url, "https://audit.example.com/events")
        self.assertEqual(config.audit_central_timeout_sec, 4.5)
        self.assertEqual(config.audit_central_headers(), {"X-Audit-Token": "central-secret"})
        self.assertEqual(config.audit_central_auth_token_source(), "file")

    def test_sqlite_persistence_settings_load_from_environment(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "AI_RISK_SESSION_STORE_BACKEND": "sqlite",
                "AI_RISK_CASE_STORE_BACKEND": "sqlite",
                "AI_RISK_DATABASE_PATH": "/tmp/ai-risk-platform.db",
            },
        ):
            config = AppConfig.from_env()

        self.assertEqual(config.session_store_backend, "sqlite")
        self.assertEqual(config.case_store_backend, "sqlite")
        self.assertEqual(config.database_path, Path("/tmp/ai-risk-platform.db"))

    def test_postgres_persistence_settings_load_dsn_from_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            dsn_path = Path(tmp_dir) / "postgres-dsn"
            dsn_path.write_text("postgresql://risk:secret@db/risk\n", encoding="utf-8")
            with patch.dict(
                "os.environ",
                {
                    "AI_RISK_SESSION_STORE_BACKEND": "postgres",
                    "AI_RISK_CASE_STORE_BACKEND": "postgres",
                    "AI_RISK_POSTGRES_DSN_FILE": str(dsn_path),
                },
            ):
                config = AppConfig.from_env()

        self.assertEqual(config.session_store_backend, "postgres")
        self.assertEqual(config.case_store_backend, "postgres")
        self.assertEqual(config.postgres_dsn, "postgresql://risk:secret@db/risk")
        self.assertEqual(config.postgres_dsn_source(), "file")

    def test_fault_injection_requires_explicit_environment_flag(self) -> None:
        self.assertFalse(AppConfig().risk_service_fault_injection_enabled)
        with patch.dict(
            "os.environ",
            {"AI_RISK_RISK_SERVICE_FAULT_INJECTION_ENABLED": "true"},
        ):
            config = AppConfig.from_env()

        self.assertTrue(config.risk_service_fault_injection_enabled)

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
        self.assertEqual(
            capability_contract[1]["required_tools"],
            [
                "metric_snapshot",
                "case_lookup",
                "order_profile",
                "sql_query",
                "dashboard_snapshot",
                "rule_explain",
            ],
        )
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
                "sql_query",
                "dashboard_snapshot",
                "rule_explain",
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
            ["investigation", "strategy", "copilot"],
        )


if __name__ == "__main__":
    unittest.main()
