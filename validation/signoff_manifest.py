from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MANIFEST_VERSION = 1
DEFAULT_MANIFEST_FILES = (
    "postgres-smoke.json",
    "readiness.json",
    "staging-validation.json",
    "signoff-summary.json",
)


def build_signoff_manifest(
    report_dir: Path,
    *,
    files: tuple[str, ...] = DEFAULT_MANIFEST_FILES,
) -> dict[str, Any]:
    entries = []
    missing = []
    for filename in files:
        path = report_dir / filename
        if not path.exists():
            missing.append(filename)
            continue
        payload = path.read_bytes()
        entries.append(
            {
                "path": filename,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "bytes": len(payload),
            }
        )
    return {
        "version": MANIFEST_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "report_dir": str(report_dir),
        "files": entries,
        "missing_files": missing,
        "provenance": _git_provenance(),
    }


def _git_provenance() -> dict[str, Any]:
    commit = _git_output("rev-parse", "HEAD")
    branch = _git_output("rev-parse", "--abbrev-ref", "HEAD")
    status = _git_output("status", "--short")
    return {
        "git_commit": commit or "unknown",
        "git_branch": branch or "unknown",
        "git_dirty": bool(status),
    }


def _git_output(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a staging signoff manifest.")
    parser.add_argument("--report-dir", required=True)
    parser.add_argument("--output")
    args = parser.parse_args(argv)

    report_dir = Path(args.report_dir)
    manifest = build_signoff_manifest(report_dir)
    rendered = json.dumps(manifest, ensure_ascii=False, indent=2)
    output_path = Path(args.output) if args.output else report_dir / "signoff-manifest.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if not manifest["missing_files"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
