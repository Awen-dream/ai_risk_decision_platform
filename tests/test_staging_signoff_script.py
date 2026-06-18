from __future__ import annotations

import unittest
from pathlib import Path


class StagingSignoffScriptTests(unittest.TestCase):
    def test_signoff_script_runs_required_gates(self) -> None:
        payload = Path("scripts/run_real_staging_signoff.sh").read_text(encoding="utf-8")

        for marker in (
            "validation.postgres_smoke",
            "validation.readiness",
            "validation.staging",
            "validation.signoff_evidence",
            "signoff-summary.json",
            "signoff-evidence.json",
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


if __name__ == "__main__":
    unittest.main()
