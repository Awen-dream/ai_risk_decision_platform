from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from validation.signoff_manifest import build_signoff_manifest


class SignoffManifestTests(unittest.TestCase):
    def test_manifest_records_hashes_and_missing_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            report_dir = Path(tmp_dir)
            (report_dir / "postgres-smoke.json").write_text("postgres\n", encoding="utf-8")
            (report_dir / "readiness.json").write_text("readiness\n", encoding="utf-8")

            manifest = build_signoff_manifest(report_dir)

        files = {entry["path"]: entry for entry in manifest["files"]}
        self.assertIn("postgres-smoke.json", files)
        self.assertIn("readiness.json", files)
        self.assertEqual(files["postgres-smoke.json"]["bytes"], len("postgres\n"))
        self.assertIn("staging-validation.json", manifest["missing_files"])
        self.assertIn("git_commit", manifest["provenance"])

    def test_manifest_can_require_planner_eval_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            report_dir = Path(tmp_dir)
            (report_dir / "planner-eval.json").write_text("planner\n", encoding="utf-8")

            manifest = build_signoff_manifest(
                report_dir,
                files=("planner-eval.json",),
            )

        files = {entry["path"]: entry for entry in manifest["files"]}
        self.assertEqual(manifest["missing_files"], [])
        self.assertIn("planner-eval.json", files)
        self.assertEqual(files["planner-eval.json"]["bytes"], len("planner\n"))


if __name__ == "__main__":
    unittest.main()
