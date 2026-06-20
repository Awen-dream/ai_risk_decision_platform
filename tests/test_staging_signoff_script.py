from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


class StagingSignoffScriptTests(unittest.TestCase):
    def test_signoff_script_runs_required_gates(self) -> None:
        payload = Path("scripts/run_real_staging_signoff.sh").read_text(encoding="utf-8")

        for marker in (
            "validation.signoff_preflight",
            "validation.postgres_smoke",
            "validation.readiness",
            "validation.staging",
            "validation.signoff_manifest",
            "validation.signoff_evidence",
            "validation.signoff_archive",
            "signoff-preflight.json",
            "signoff-summary.json",
            "signoff-manifest.json",
            "signoff-evidence.json",
            "signoff-archive.tar.gz",
            "signoff-archive.sha256",
            "verify-signoff-archive",
        ):
            self.assertIn(marker, payload)

    def test_local_signoff_runs_real_signoff_with_expected_overrides(self) -> None:
        payload = Path("scripts/run_local_signoff.sh").read_text(encoding="utf-8")

        for marker in (
            "bash scripts/run_real_staging_signoff.sh",
            "AI_RISK_SIGNOFF_REQUIRE_POSTGRES=false",
            "AI_RISK_SIGNOFF_REQUIRE_CENTRAL_AUDIT=true",
            "AI_RISK_SIGNOFF_CENTRAL_AUDIT_BASE_URL",
            "AI_RISK_AUDIT_CENTRAL_AUTH_TOKEN_FILE",
        ):
            self.assertIn(marker, payload)

    def test_missing_required_inputs_still_produces_failure_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            report_dir = Path(tmp_dir) / "missing-input-signoff"
            env = os.environ.copy()
            for name in (
                "RISK_BASE_URL",
                "AGENT_BASE_URL",
                "AI_RISK_SIGNOFF_RISK_BASE_URL",
                "AI_RISK_SIGNOFF_AGENT_BASE_URL",
                "AI_RISK_ADMIN_AUTH_TOKEN_FILE",
                "AI_RISK_POSTGRES_DSN_FILE",
                "AI_RISK_SIGNOFF_CENTRAL_AUDIT_BASE_URL",
                "AI_RISK_AUDIT_CENTRAL_QUERY_URL",
            ):
                env.pop(name, None)
            env["AI_RISK_SIGNOFF_REPORT_DIR"] = str(report_dir)

            result = subprocess.run(
                ["bash", "scripts/run_real_staging_signoff.sh"],
                check=False,
                capture_output=True,
                env=env,
                text=True,
                timeout=10,
            )

            summary = json.loads((report_dir / "signoff-summary.json").read_text())
            preflight = json.loads((report_dir / "signoff-preflight.json").read_text())
            archive_exists = (report_dir / "signoff-archive.tar.gz").exists()
            checksum_exists = (report_dir / "signoff-archive.sha256").exists()

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(preflight["status"], "failed")
        self.assertTrue(archive_exists)
        self.assertTrue(checksum_exists)
        self.assertIn("verify-signoff-archive", result.stdout)


if __name__ == "__main__":
    unittest.main()
