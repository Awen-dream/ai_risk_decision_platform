from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse


@dataclass
class PreflightCheck:
    name: str
    status: str
    detail: str
    duration_ms: float


class PreflightRunner:
    def __init__(self) -> None:
        self.checks: list[PreflightCheck] = []

    def check(self, name: str, operation: Callable[[], str]) -> None:
        started_at = time.perf_counter()
        try:
            detail = operation()
        except Exception as exc:
            self.checks.append(
                PreflightCheck(
                    name=name,
                    status="failed",
                    detail=f"{type(exc).__name__}: {exc}",
                    duration_ms=(time.perf_counter() - started_at) * 1000,
                )
            )
            return
        self.checks.append(
            PreflightCheck(
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


def run_signoff_preflight(
    *,
    risk_base_url: str,
    agent_base_url: str,
    admin_token_file: str,
    postgres_dsn_file: str = "",
    postgres_required: bool = True,
    central_audit_base_url: str = "",
    central_audit_token_file: str = "",
    central_audit_required: bool = False,
) -> dict[str, Any]:
    runner = PreflightRunner()
    runner.check(
        "preflight.base_urls",
        lambda: _validate_base_urls(risk_base_url, agent_base_url),
    )
    runner.check(
        "preflight.admin_token_file",
        lambda: _validate_secret_file(admin_token_file, "admin token file"),
    )
    runner.check(
        "preflight.postgres_dsn_file",
        lambda: _validate_postgres_dsn_file(
            postgres_dsn_file,
            postgres_required=postgres_required,
        ),
    )
    runner.check(
        "preflight.central_audit",
        lambda: _validate_central_audit(
            central_audit_base_url,
            central_audit_token_file,
            central_audit_required=central_audit_required,
        ),
    )
    return runner.report()


def _validate_base_urls(risk_base_url: str, agent_base_url: str) -> str:
    for name, value in (
        ("risk base URL", risk_base_url),
        ("agent base URL", agent_base_url),
    ):
        _validate_http_url(value, name)
    return "risk and agent base URLs are valid HTTP(S) URLs"


def _validate_http_url(value: str, label: str) -> None:
    if not value:
        raise AssertionError(f"{label} is required")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AssertionError(f"{label} must be an HTTP(S) URL")
    if parsed.username or parsed.password:
        raise AssertionError(f"{label} must not contain inline credentials")
    if parsed.query or parsed.fragment:
        raise AssertionError(f"{label} must not contain query strings or fragments")


def _validate_secret_file(path: str, label: str) -> str:
    if not path:
        raise AssertionError(f"{label} is required")
    secret_path = Path(path)
    if not secret_path.is_file():
        raise AssertionError(f"{label} does not exist or is not a file: {path}")
    value = secret_path.read_text(encoding="utf-8").strip()
    if not value:
        raise AssertionError(f"{label} is empty")
    return f"{label} is readable and non-empty"


def _validate_postgres_dsn_file(path: str, *, postgres_required: bool) -> str:
    if not path:
        if postgres_required:
            raise AssertionError("PostgreSQL DSN file is required")
        return "PostgreSQL DSN file is explicitly skipped"
    detail = _validate_secret_file(path, "PostgreSQL DSN file")
    return detail


def _validate_central_audit(
    base_url: str,
    token_file: str,
    *,
    central_audit_required: bool,
) -> str:
    if not base_url:
        if central_audit_required:
            raise AssertionError("central audit base URL is required")
        return "central audit query verification is not required"
    _validate_http_url(base_url, "central audit base URL")
    if token_file:
        _validate_secret_file(token_file, "central audit token file")
        return "central audit URL and token file are valid"
    return "central audit URL is valid; no token file configured"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run staging signoff preflight checks.")
    parser.add_argument("--risk-base-url", required=True)
    parser.add_argument("--agent-base-url", required=True)
    parser.add_argument("--admin-token-file", required=True)
    parser.add_argument("--postgres-dsn-file", default="")
    parser.add_argument("--postgres-required", action="store_true")
    parser.add_argument("--central-audit-base-url", default="")
    parser.add_argument("--central-audit-token-file", default="")
    parser.add_argument("--central-audit-required", action="store_true")
    parser.add_argument("--output")
    args = parser.parse_args(argv)

    report = run_signoff_preflight(
        risk_base_url=args.risk_base_url,
        agent_base_url=args.agent_base_url,
        admin_token_file=args.admin_token_file,
        postgres_dsn_file=args.postgres_dsn_file,
        postgres_required=args.postgres_required,
        central_audit_base_url=args.central_audit_base_url,
        central_audit_token_file=args.central_audit_token_file,
        central_audit_required=args.central_audit_required,
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
