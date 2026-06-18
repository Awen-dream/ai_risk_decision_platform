from __future__ import annotations

import hashlib
import tarfile
import tempfile
import unittest
from pathlib import Path

from validation.signoff_archive import ARCHIVE_FILES, build_signoff_archive


class SignoffArchiveTests(unittest.TestCase):
    def test_archive_contains_required_reports_and_checksum(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            report_dir = Path(tmp_dir)
            for filename in ARCHIVE_FILES:
                (report_dir / filename).write_text(f"{filename}\n", encoding="utf-8")

            report = build_signoff_archive(report_dir)

            archive_path = Path(report["archive_path"])
            checksum_path = Path(report["checksum_path"])
            with tarfile.open(archive_path, mode="r:gz") as archive:
                names = archive.getnames()
            archive_hash = hashlib.sha256(archive_path.read_bytes()).hexdigest()
            checksum_text = checksum_path.read_text(encoding="utf-8")

        self.assertEqual(report["status"], "passed")
        self.assertEqual(names, list(ARCHIVE_FILES))
        self.assertIn(archive_hash, checksum_text)
        self.assertEqual(report["archive_sha256"], archive_hash)

    def test_archive_fails_when_required_report_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            report_dir = Path(tmp_dir)
            (report_dir / "signoff-preflight.json").write_text("ok\n", encoding="utf-8")

            report = build_signoff_archive(report_dir)

        self.assertEqual(report["status"], "failed")
        self.assertIn("signoff-evidence.json", report["missing_files"])


if __name__ == "__main__":
    unittest.main()
