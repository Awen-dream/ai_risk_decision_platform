from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ARCHIVE_FILES = (
    "signoff-preflight.json",
    "postgres-smoke.json",
    "readiness.json",
    "staging-validation.json",
    "signoff-summary.json",
    "signoff-manifest.json",
    "signoff-evidence.json",
)


def build_signoff_archive(
    report_dir: Path,
    *,
    output_path: Path | None = None,
    checksum_path: Path | None = None,
) -> dict[str, Any]:
    output_path = output_path or report_dir / "signoff-archive.tar.gz"
    checksum_path = checksum_path or report_dir / "signoff-archive.sha256"
    missing_files = [filename for filename in ARCHIVE_FILES if not (report_dir / filename).exists()]
    if missing_files:
        return _archive_report(
            status="failed",
            report_dir=report_dir,
            output_path=output_path,
            checksum_path=checksum_path,
            files=[],
            missing_files=missing_files,
            archive_sha256="",
            archive_bytes=0,
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as raw_file:
        with gzip.GzipFile(fileobj=raw_file, mode="wb", mtime=0) as gzip_file:
            with tarfile.open(fileobj=gzip_file, mode="w") as archive:
                for filename in ARCHIVE_FILES:
                    _add_file(archive, report_dir / filename, filename)

    payload = output_path.read_bytes()
    archive_sha256 = hashlib.sha256(payload).hexdigest()
    checksum_path.parent.mkdir(parents=True, exist_ok=True)
    checksum_path.write_text(f"{archive_sha256}  {output_path.name}\n", encoding="utf-8")
    return _archive_report(
        status="passed",
        report_dir=report_dir,
        output_path=output_path,
        checksum_path=checksum_path,
        files=list(ARCHIVE_FILES),
        missing_files=[],
        archive_sha256=archive_sha256,
        archive_bytes=len(payload),
    )


def _add_file(archive: tarfile.TarFile, path: Path, arcname: str) -> None:
    payload = path.read_bytes()
    info = tarfile.TarInfo(arcname)
    info.size = len(payload)
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mode = 0o644
    archive.addfile(info, io.BytesIO(payload))


def _archive_report(
    *,
    status: str,
    report_dir: Path,
    output_path: Path,
    checksum_path: Path,
    files: list[str],
    missing_files: list[str],
    archive_sha256: str,
    archive_bytes: int,
) -> dict[str, Any]:
    return {
        "status": status,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "report_dir": str(report_dir),
        "archive_path": str(output_path),
        "checksum_path": str(checksum_path),
        "archive_sha256": archive_sha256,
        "archive_bytes": archive_bytes,
        "files": files,
        "missing_files": missing_files,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a staging signoff archive.")
    parser.add_argument("--report-dir", required=True)
    parser.add_argument("--output")
    parser.add_argument("--checksum-output")
    args = parser.parse_args(argv)

    report = build_signoff_archive(
        Path(args.report_dir),
        output_path=Path(args.output) if args.output else None,
        checksum_path=Path(args.checksum_output) if args.checksum_output else None,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
