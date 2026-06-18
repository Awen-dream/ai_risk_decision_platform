from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from validation.signoff_preflight import run_signoff_preflight


class SignoffPreflightTests(unittest.TestCase):
    def test_valid_preflight_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            admin_token = Path(tmp_dir) / "admin-token"
            postgres_dsn = Path(tmp_dir) / "postgres-dsn"
            audit_token = Path(tmp_dir) / "audit-token"
            admin_token.write_text("admin-secret\n", encoding="utf-8")
            postgres_dsn.write_text("postgresql://risk:secret@db/risk\n", encoding="utf-8")
            audit_token.write_text("audit-secret\n", encoding="utf-8")

            report = run_signoff_preflight(
                risk_base_url="https://risk-staging.example.com",
                agent_base_url="https://agent-staging.example.com",
                admin_token_file=str(admin_token),
                postgres_dsn_file=str(postgres_dsn),
                postgres_required=True,
                central_audit_base_url="https://audit-staging.example.com",
                central_audit_token_file=str(audit_token),
                central_audit_required=True,
            )

        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["summary"]["total"], 4)

    def test_missing_admin_token_file_fails(self) -> None:
        report = run_signoff_preflight(
            risk_base_url="https://risk-staging.example.com",
            agent_base_url="https://agent-staging.example.com",
            admin_token_file="/tmp/missing-admin-token",
            postgres_required=False,
        )

        self.assertEqual(report["status"], "failed")
        self.assertIn("admin token", _failed_details(report))

    def test_rejects_inline_url_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            admin_token = Path(tmp_dir) / "admin-token"
            admin_token.write_text("admin-secret\n", encoding="utf-8")

            report = run_signoff_preflight(
                risk_base_url="https://user:pass@risk-staging.example.com",
                agent_base_url="https://agent-staging.example.com",
                admin_token_file=str(admin_token),
                postgres_required=False,
            )

        self.assertEqual(report["status"], "failed")
        self.assertIn("inline credentials", _failed_details(report))


def _failed_details(report: dict[str, object]) -> str:
    checks = report["checks"]
    assert isinstance(checks, list)
    return "\n".join(
        str(check["detail"])
        for check in checks
        if isinstance(check, dict) and check.get("status") == "failed"
    )


if __name__ == "__main__":
    unittest.main()
