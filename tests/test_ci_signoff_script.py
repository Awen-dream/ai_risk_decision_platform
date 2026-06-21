from __future__ import annotations

import unittest
from pathlib import Path


class CiSignoffScriptTests(unittest.TestCase):
    def test_makefile_exposes_ci_signoff_target(self) -> None:
        payload = Path("Makefile").read_text(encoding="utf-8")

        self.assertIn("ci-signoff:", payload)
        self.assertIn("bash scripts/run_ci_signoff.sh", payload)

    def test_ci_signoff_runs_required_gates(self) -> None:
        payload = Path("scripts/run_ci_signoff.sh").read_text(encoding="utf-8")

        for marker in (
            "unittest discover -v",
            "AI_RISK_SIGNOFF_REQUIRE_RELEASE_METADATA=true",
            "AI_RISK_SIGNOFF_RELEASE_ID",
            "signoff-local",
            "ci-signoff-summary.json",
            "failed_gate",
            "signoff-archive.tar.gz",
            "signoff-archive.sha256",
        ):
            self.assertIn(marker, payload)

    def test_github_workflow_runs_ci_signoff_and_uploads_artifacts(self) -> None:
        payload = Path(".github/workflows/ci-signoff.yml").read_text(encoding="utf-8")

        for marker in (
            "pull_request:",
            "push:",
            "workflow_dispatch:",
            "actions/checkout@v4",
            "actions/setup-python@v5",
            "python -m pip install -r requirements.txt",
            "make ci-signoff",
            "actions/upload-artifact@v4",
            "if: always()",
            "if-no-files-found: error",
            "AI_RISK_CI_SIGNOFF_REPORT_DIR",
        ):
            self.assertIn(marker, payload)


if __name__ == "__main__":
    unittest.main()
