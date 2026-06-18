from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


REQUIRED_REPORTS = {
    "signoff_preflight": "signoff-preflight.json",
    "signoff_summary": "signoff-summary.json",
    "postgres_smoke": "postgres-smoke.json",
    "readiness": "readiness.json",
    "staging_validation": "staging-validation.json",
    "signoff_manifest": "signoff-manifest.json",
}
MINIMUM_CHECK_TOTALS = {
    "signoff_preflight": 4,
    "postgres_smoke": 4,
    "readiness": 7,
    "staging_validation": 17,
}
CENTRAL_AUDIT_CHECK = "central_audit.mirrored_events"
SENSITIVE_KEY_FRAGMENTS = ("token", "secret", "password", "dsn", "api_key", "apikey")
SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"postgres(?:ql)?://[^\s\"']+:[^\s\"']+@", re.IGNORECASE),
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/-]{12,}", re.IGNORECASE),
    re.compile(
        r"\b(?:api[_-]?key|token|secret|password)\s*[:=]\s*[^\s,;}]+",
        re.IGNORECASE,
    ),
)


@dataclass
class EvidenceCheck:
    name: str
    status: str
    detail: str
    duration_ms: float


class EvidenceRunner:
    def __init__(self) -> None:
        self.checks: list[EvidenceCheck] = []

    def check(self, name: str, operation: Callable[[], str]) -> None:
        started_at = time.perf_counter()
        try:
            detail = operation()
        except Exception as exc:
            self.checks.append(
                EvidenceCheck(
                    name=name,
                    status="failed",
                    detail=f"{type(exc).__name__}: {exc}",
                    duration_ms=(time.perf_counter() - started_at) * 1000,
                )
            )
            return
        self.checks.append(
            EvidenceCheck(
                name=name,
                status="passed",
                detail=detail,
                duration_ms=(time.perf_counter() - started_at) * 1000,
            )
        )

    def report(self) -> dict[str, Any]:
        passed = sum(check.status == "passed" for check in self.checks)
        failed = len(self.checks) - passed
        return {
            "status": "passed" if failed == 0 else "failed",
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "summary": {
                "total": len(self.checks),
                "passed": passed,
                "failed": failed,
            },
            "checks": [asdict(check) for check in self.checks],
        }


def validate_signoff_evidence(
    report_dir: Path,
    *,
    allow_postgres_skipped: bool = False,
    require_central_audit: bool = False,
    expected_risk_base_url: str = "",
    expected_agent_base_url: str = "",
) -> dict[str, Any]:
    payloads: dict[str, Any] = {}
    runner = EvidenceRunner()
    runner.check(
        "evidence.files",
        lambda: _load_required_reports(report_dir, payloads),
    )
    runner.check(
        "evidence.summary_status",
        lambda: _validate_summary_status(payloads),
    )
    runner.check(
        "evidence.report_statuses",
        lambda: _validate_report_statuses(
            payloads,
            allow_postgres_skipped=allow_postgres_skipped,
        ),
    )
    runner.check(
        "evidence.coverage",
        lambda: _validate_minimum_coverage(payloads),
    )
    runner.check(
        "evidence.manifest",
        lambda: _validate_manifest(report_dir, payloads),
    )
    runner.check(
        "evidence.central_audit",
        lambda: _validate_central_audit_requirement(
            payloads,
            require_central_audit=require_central_audit,
        ),
    )
    runner.check(
        "evidence.environment_binding",
        lambda: _validate_environment_binding(
            payloads,
            expected_risk_base_url=expected_risk_base_url,
            expected_agent_base_url=expected_agent_base_url,
        ),
    )
    runner.check(
        "evidence.no_secret_leakage",
        lambda: _validate_no_secret_leakage(payloads),
    )
    return runner.report()


def _load_required_reports(report_dir: Path, payloads: dict[str, Any]) -> str:
    if not report_dir.is_dir():
        raise AssertionError(f"report directory does not exist: {report_dir}")
    missing = []
    for name, filename in REQUIRED_REPORTS.items():
        path = report_dir / filename
        if not path.exists():
            missing.append(filename)
            continue
        try:
            payloads[name] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise AssertionError(f"invalid JSON in {filename}: {exc}") from exc
    if missing:
        raise AssertionError(f"missing signoff evidence files: {missing}")
    return f"loaded required evidence files: {len(REQUIRED_REPORTS)}"


def _validate_summary_status(payloads: dict[str, Any]) -> str:
    summary = _payload(payloads, "signoff_summary")
    if summary.get("status") != "passed":
        raise AssertionError(f"signoff summary is not passed: {summary.get('status')}")
    failed_reports = summary.get("failed_reports", [])
    if failed_reports:
        raise AssertionError(f"signoff summary lists failed reports: {failed_reports}")
    reports = summary.get("reports", {})
    missing = [
        name
        for name in ("signoff_preflight", "postgres_smoke", "readiness", "staging_validation")
        if name not in reports
    ]
    if missing:
        raise AssertionError(f"signoff summary missing report summaries: {missing}")
    return "signoff summary status is passed"


def _validate_report_statuses(
    payloads: dict[str, Any],
    *,
    allow_postgres_skipped: bool,
) -> str:
    failures = []
    for name in ("signoff_preflight", "postgres_smoke", "readiness", "staging_validation"):
        report = _payload(payloads, name)
        status = report.get("status")
        if name == "postgres_smoke" and status == "skipped" and allow_postgres_skipped:
            continue
        if status != "passed":
            failures.append(f"{name}={status}")
            continue
        failed = report.get("summary", {}).get("failed")
        if failed != 0:
            failures.append(f"{name}.failed={failed}")
    if failures:
        raise AssertionError(f"report status checks failed: {failures}")
    return "all required reports are passed"


def _validate_minimum_coverage(payloads: dict[str, Any]) -> str:
    failures = []
    for name, minimum_total in MINIMUM_CHECK_TOTALS.items():
        report = _payload(payloads, name)
        if report.get("status") == "skipped":
            continue
        total = report.get("summary", {}).get("total")
        if not isinstance(total, int) or total < minimum_total:
            failures.append(f"{name}.total={total} < {minimum_total}")
    if failures:
        raise AssertionError(f"minimum coverage checks failed: {failures}")
    return "minimum signoff coverage is present"


def _validate_manifest(report_dir: Path, payloads: dict[str, Any]) -> str:
    manifest = _payload(payloads, "signoff_manifest")
    if manifest.get("version") != 1:
        raise AssertionError(f"unsupported signoff manifest version: {manifest.get('version')}")
    missing_files = manifest.get("missing_files", [])
    if missing_files:
        raise AssertionError(f"signoff manifest lists missing files: {missing_files}")
    files = manifest.get("files", [])
    if not isinstance(files, list) or not files:
        raise AssertionError("signoff manifest has no file entries")
    entries = {entry.get("path"): entry for entry in files if isinstance(entry, dict)}
    expected = {
        "signoff-preflight.json",
        "postgres-smoke.json",
        "readiness.json",
        "staging-validation.json",
        "signoff-summary.json",
    }
    missing_entries = sorted(expected - set(entries))
    if missing_entries:
        raise AssertionError(f"signoff manifest missing checksum entries: {missing_entries}")
    failures = []
    for filename in sorted(expected):
        path = report_dir / filename
        if not path.exists():
            failures.append(f"{filename}: file missing")
            continue
        payload = path.read_bytes()
        entry = entries[filename]
        if entry.get("sha256") != hashlib.sha256(payload).hexdigest():
            failures.append(f"{filename}: sha256 mismatch")
        if entry.get("bytes") != len(payload):
            failures.append(f"{filename}: byte size mismatch")
    if failures:
        raise AssertionError(f"manifest checksum verification failed: {failures}")
    provenance = manifest.get("provenance", {})
    if not isinstance(provenance, dict) or "git_commit" not in provenance:
        raise AssertionError("signoff manifest missing git provenance")
    return f"manifest checksums verified: {len(expected)} files"


def _validate_central_audit_requirement(
    payloads: dict[str, Any],
    *,
    require_central_audit: bool,
) -> str:
    summary = _payload(payloads, "signoff_summary")
    inputs = summary.get("inputs", {})
    central_required = bool(inputs.get("central_audit_query_required")) or require_central_audit
    checks = _payload(payloads, "staging_validation").get("checks", [])
    check_names = {check.get("name") for check in checks}
    if central_required and CENTRAL_AUDIT_CHECK not in check_names:
        raise AssertionError("central audit evidence is required but missing")
    if CENTRAL_AUDIT_CHECK in check_names:
        return "central audit evidence is present"
    return "central audit evidence is not required"


def _validate_environment_binding(
    payloads: dict[str, Any],
    *,
    expected_risk_base_url: str,
    expected_agent_base_url: str,
) -> str:
    summary = _payload(payloads, "signoff_summary")
    inputs = summary.get("inputs", {})
    risk_base_url = inputs.get("risk_base_url")
    agent_base_url = inputs.get("agent_base_url")
    if not risk_base_url or not agent_base_url:
        raise AssertionError("signoff summary must include risk and agent base URLs")
    if expected_risk_base_url and risk_base_url.rstrip("/") != expected_risk_base_url.rstrip("/"):
        raise AssertionError(
            f"risk base URL mismatch: expected {expected_risk_base_url}, got {risk_base_url}"
        )
    if expected_agent_base_url and agent_base_url.rstrip("/") != expected_agent_base_url.rstrip("/"):
        raise AssertionError(
            f"agent base URL mismatch: expected {expected_agent_base_url}, got {agent_base_url}"
        )
    return "signoff evidence is bound to the expected environment"


def _validate_no_secret_leakage(payloads: dict[str, Any]) -> str:
    leaks: list[str] = []
    for name, payload in payloads.items():
        leaks.extend(_find_secret_leaks(payload, f"$.{name}"))
    if leaks:
        raise AssertionError(f"potential secret leakage found: {leaks[:5]}")
    return "signoff evidence contains no obvious secret values"


def _find_secret_leaks(payload: Any, path: str) -> list[str]:
    leaks: list[str] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            child_path = f"{path}.{key}"
            normalized_key = key.lower()
            if any(fragment in normalized_key for fragment in SENSITIVE_KEY_FRAGMENTS):
                if _contains_non_empty_sensitive_value(value):
                    leaks.append(child_path)
            leaks.extend(_find_secret_leaks(value, child_path))
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            leaks.extend(_find_secret_leaks(item, f"{path}[{index}]"))
    elif isinstance(payload, str):
        if any(pattern.search(payload) for pattern in SENSITIVE_VALUE_PATTERNS):
            leaks.append(path)
    return leaks


def _contains_non_empty_sensitive_value(value: Any) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def _payload(payloads: dict[str, Any], name: str) -> dict[str, Any]:
    payload = payloads.get(name)
    if not isinstance(payload, dict):
        raise AssertionError(f"missing or invalid report payload: {name}")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate staging signoff evidence.")
    parser.add_argument("--report-dir", required=True)
    parser.add_argument("--allow-postgres-skipped", action="store_true")
    parser.add_argument("--require-central-audit", action="store_true")
    parser.add_argument("--expected-risk-base-url", default="")
    parser.add_argument("--expected-agent-base-url", default="")
    parser.add_argument("--output")
    args = parser.parse_args(argv)

    report = validate_signoff_evidence(
        Path(args.report_dir),
        allow_postgres_skipped=args.allow_postgres_skipped,
        require_central_audit=args.require_central_audit,
        expected_risk_base_url=args.expected_risk_base_url,
        expected_agent_base_url=args.expected_agent_base_url,
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
