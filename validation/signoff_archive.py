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


def verify_signoff_archive(
    report_dir: Path | None = None,
    *,
    archive_path: Path | None = None,
    checksum_path: Path | None = None,
) -> dict[str, Any]:
    if report_dir is None and archive_path is None:
        raise ValueError("report_dir or archive_path is required")
    archive_path = archive_path or report_dir / "signoff-archive.tar.gz"  # type: ignore[operator]
    checksum_path = checksum_path or archive_path.with_name("signoff-archive.sha256")
    source_report_dir = report_dir
    display_report_dir = report_dir or archive_path.parent
    failures: list[str] = []
    verified_files: list[str] = []

    if not archive_path.is_file():
        failures.append(f"archive missing: {archive_path}")
    if not checksum_path.is_file():
        failures.append(f"checksum missing: {checksum_path}")
    if failures:
        return _verification_report(
            status="failed",
            report_dir=display_report_dir,
            archive_path=archive_path,
            checksum_path=checksum_path,
            archive_sha256="",
            verified_files=verified_files,
            failures=failures,
            source_comparison="required" if source_report_dir else "skipped",
        )

    archive_payload = archive_path.read_bytes()
    archive_sha256 = hashlib.sha256(archive_payload).hexdigest()
    checksum_parts = checksum_path.read_text(encoding="utf-8").strip().split()
    expected_sha256 = checksum_parts[0] if checksum_parts else ""
    expected_name = checksum_parts[1] if len(checksum_parts) > 1 else ""
    if expected_sha256 != archive_sha256:
        failures.append("archive checksum does not match signoff-archive.sha256")
    if expected_name and expected_name != archive_path.name:
        failures.append(f"checksum filename mismatch: {expected_name}")

    try:
        with tarfile.open(archive_path, mode="r:gz") as archive:
            members = archive.getmembers()
            names = [member.name for member in members]
            if names != list(ARCHIVE_FILES):
                failures.append(f"archive file list mismatch: {names}")
            for member in members:
                if not member.isfile():
                    failures.append(f"archive member is not a file: {member.name}")
                    continue
                if member.name.startswith("/") or ".." in Path(member.name).parts:
                    failures.append(f"unsafe archive member path: {member.name}")
                    continue
                if member.name not in ARCHIVE_FILES:
                    failures.append(f"unexpected archive member: {member.name}")
                    continue
                extracted = archive.extractfile(member)
                if extracted is None:
                    failures.append(f"archive member could not be read: {member.name}")
                    continue
                extracted_payload = extracted.read()
                try:
                    json.loads(extracted_payload.decode("utf-8"))
                except json.JSONDecodeError as exc:
                    failures.append(f"archive member is not valid JSON: {member.name}: {exc}")
                    continue
                if source_report_dir is not None:
                    source_path = source_report_dir / member.name
                    if not source_path.is_file():
                        failures.append(f"source report missing: {member.name}")
                        continue
                    if extracted_payload != source_path.read_bytes():
                        failures.append(f"archive member differs from source report: {member.name}")
                        continue
                verified_files.append(member.name)
    except tarfile.TarError as exc:
        failures.append(f"archive could not be read: {exc}")

    return _verification_report(
        status="passed" if not failures else "failed",
        report_dir=display_report_dir,
        archive_path=archive_path,
        checksum_path=checksum_path,
        archive_sha256=archive_sha256,
        verified_files=verified_files,
        failures=failures,
        source_comparison=(
            "skipped"
            if source_report_dir is None
            else ("passed" if not failures else "failed")
        ),
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


def _verification_report(
    *,
    status: str,
    report_dir: Path,
    archive_path: Path,
    checksum_path: Path,
    archive_sha256: str,
    verified_files: list[str],
    failures: list[str],
    source_comparison: str,
) -> dict[str, Any]:
    return {
        "status": status,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "report_dir": str(report_dir),
        "archive_path": str(archive_path),
        "checksum_path": str(checksum_path),
        "archive_sha256": archive_sha256,
        "verified_files": verified_files,
        "failures": failures,
        "source_comparison": source_comparison,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create or verify a staging signoff archive.")
    parser.add_argument("--report-dir")
    parser.add_argument("--output")
    parser.add_argument("--checksum-output")
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--archive")
    parser.add_argument("--checksum")
    args = parser.parse_args(argv)

    if args.verify:
        if not args.report_dir and not args.archive:
            parser.error("--verify requires --report-dir or --archive")
        report = verify_signoff_archive(
            Path(args.report_dir) if args.report_dir else None,
            archive_path=Path(args.archive) if args.archive else None,
            checksum_path=Path(args.checksum) if args.checksum else None,
        )
    else:
        if not args.report_dir:
            parser.error("--report-dir is required when creating an archive")
        report = build_signoff_archive(
            Path(args.report_dir),
            output_path=Path(args.output) if args.output else None,
            checksum_path=Path(args.checksum_output) if args.checksum_output else None,
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
