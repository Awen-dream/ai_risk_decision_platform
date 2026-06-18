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
            "signoff-summary.json",
        ):
            self.assertIn(marker, payload)


if __name__ == "__main__":
    unittest.main()
