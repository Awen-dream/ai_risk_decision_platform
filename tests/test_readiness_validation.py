from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from validation.readiness import (
    REQUIRED_ALERTS,
    _build_admin_headers,
    _validate_runtime_security,
    validate_alert_rules_file,
)


class ReadinessValidationTests(unittest.TestCase):
    def test_alert_rules_file_contains_required_alerts(self) -> None:
        detail = validate_alert_rules_file(Path("config/prometheus/ai-risk-alerts.yml"))

        self.assertIn(str(len(REQUIRED_ALERTS)), detail)

    def test_runtime_security_requires_admin_token_file(self) -> None:
        payload = {
            "admin_auth_enabled": True,
            "admin_auth_configured": True,
            "admin_auth_token_source": "env",
            "tool_http_audit_enabled": True,
            "tool_http_audit_max_bytes": 10 * 1024 * 1024,
            "tool_http_audit_max_files": 5,
            "tool_backend": "http",
            "tool_http_auth_mode": "api_key",
            "tool_http_auth_token_source": "file",
        }

        with self.assertRaisesRegex(AssertionError, "admin token"):
            _validate_runtime_security(payload)

    def test_runtime_security_requires_external_token_file_when_auth_enabled(self) -> None:
        payload = {
            "admin_auth_enabled": True,
            "admin_auth_configured": True,
            "admin_auth_token_source": "file",
            "tool_http_audit_enabled": True,
            "tool_http_audit_max_bytes": 10 * 1024 * 1024,
            "tool_http_audit_max_files": 5,
            "tool_backend": "http",
            "tool_http_auth_mode": "api_key",
            "tool_http_auth_token_source": "env",
        }

        with self.assertRaisesRegex(AssertionError, "external HTTP token"):
            _validate_runtime_security(payload)

    def test_build_admin_headers_reads_token_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            token_path = Path(tmp_dir) / "admin-token"
            token_path.write_text("file-admin-secret\n", encoding="utf-8")

            headers = _build_admin_headers("X-Admin-Token", "", str(token_path))

        self.assertEqual(headers, {"X-Admin-Token": "file-admin-secret"})


if __name__ == "__main__":
    unittest.main()
