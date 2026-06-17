from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.request import Request, urlopen


DEFAULT_ALERT_RULES_PATH = Path("config/prometheus/ai-risk-alerts.yml")
REQUIRED_ALERTS = [
    "AIRiskApiHigh5xxRatio",
    "AIRiskApiHighP95Latency",
    "AIRiskAgentHighP95Latency",
    "AIRiskUpstreamHighP95Latency",
    "AIRiskSQLiteUnhealthy",
    "AIRiskUpstreamCircuitOpen",
    "AIRiskAuditWriteFailure",
    "AIRiskAdminUnauthorizedSpike",
]


@dataclass
class ReadinessCheck:
    name: str
    status: str
    detail: str
    duration_ms: float


class ReadinessRunner:
    def __init__(self) -> None:
        self.checks: list[ReadinessCheck] = []

    def check(self, name: str, operation: Callable[[], str]) -> None:
        started_at = time.perf_counter()
        try:
            detail = operation()
        except Exception as exc:
            self.checks.append(
                ReadinessCheck(
                    name=name,
                    status="failed",
                    detail=f"{type(exc).__name__}: {exc}",
                    duration_ms=(time.perf_counter() - started_at) * 1000,
                )
            )
            return
        self.checks.append(
            ReadinessCheck(
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


class JsonHttpClient:
    def __init__(
        self,
        base_url: str,
        *,
        headers: dict[str, str] | None = None,
        timeout_sec: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = headers or {}
        self._timeout_sec = timeout_sec

    def get(self, path: str) -> Any:
        request = Request(
            f"{self._base_url}{path}",
            headers=self._headers,
            method="GET",
        )
        with urlopen(request, timeout=self._timeout_sec) as response:
            return json.load(response)

    def get_text(self, path: str) -> str:
        request = Request(
            f"{self._base_url}{path}",
            headers=self._headers,
            method="GET",
        )
        with urlopen(request, timeout=self._timeout_sec) as response:
            return response.read().decode("utf-8")


def run_readiness_gate(
    agent_base_url: str,
    *,
    admin_headers: dict[str, str],
    alert_rules_path: Path = DEFAULT_ALERT_RULES_PATH,
) -> dict[str, Any]:
    public = JsonHttpClient(agent_base_url)
    admin = JsonHttpClient(agent_base_url, headers=admin_headers)
    runner = ReadinessRunner()
    runner.check("api.health", lambda: _expect_equal(public.get("/healthz")["status"], "ok"))
    runner.check("admin.protected", lambda: _validate_admin_protected(agent_base_url))
    runtime_payload: dict[str, Any] = {}

    def runtime_check() -> str:
        nonlocal runtime_payload
        runtime_payload = admin.get("/admin/runtime")
        return _validate_runtime_security(runtime_payload)

    runner.check("runtime.security_contract", runtime_check)
    runner.check("runtime.readiness", lambda: _validate_runtime_readiness(runtime_payload))
    runner.check("metrics.prometheus", lambda: _validate_prometheus(admin))
    runner.check("alerts.rules_file", lambda: validate_alert_rules_file(alert_rules_path))
    return runner.report()


def validate_alert_rules_file(path: Path) -> str:
    if not path.exists():
        raise AssertionError(f"alert rules file does not exist: {path}")
    payload = path.read_text(encoding="utf-8")
    missing = [alert for alert in REQUIRED_ALERTS if f"alert: {alert}" not in payload]
    if missing:
        raise AssertionError(f"missing alert rules: {missing}")
    if "TODO" in payload:
        raise AssertionError("alert rules contain TODO markers")
    return f"required alert rules present: {len(REQUIRED_ALERTS)}"


def _validate_admin_protected(agent_base_url: str) -> str:
    request = Request(f"{agent_base_url.rstrip('/')}/admin/runtime", method="GET")
    try:
        with urlopen(request, timeout=10.0):
            raise AssertionError("/admin/runtime accepted a request without admin token")
    except HTTPError as exc:
        if exc.code != 401:
            raise AssertionError(f"expected 401 without admin token, got {exc.code}") from exc
    return "admin endpoints reject missing admin token"


def _validate_runtime_security(payload: dict[str, Any]) -> str:
    if not payload["admin_auth_enabled"]:
        raise AssertionError("admin authentication is not enabled")
    if not payload["admin_auth_configured"]:
        raise AssertionError("admin authentication token is not configured")
    if payload["admin_auth_token_source"] != "file":
        raise AssertionError("admin token must come from a token file")
    if not payload["tool_http_audit_enabled"]:
        raise AssertionError("external HTTP audit logging is not enabled")
    if payload["tool_http_audit_max_bytes"] < 1024:
        raise AssertionError("external HTTP audit max bytes is too small")
    if payload["tool_http_audit_max_files"] < 2:
        raise AssertionError("external HTTP audit must retain at least two files")
    if payload["tool_backend"] == "http" and payload["tool_http_auth_mode"] != "none":
        if payload["tool_http_auth_token_source"] != "file":
            raise AssertionError("external HTTP token must come from a token file")
    return "admin auth, token source, and audit settings are production-safe"


def _validate_runtime_readiness(payload: dict[str, Any]) -> str:
    if payload["readiness"]["status"] != "ready":
        raise AssertionError(f"runtime is not ready: {payload['readiness']}")
    return "runtime readiness is ready"


def _validate_prometheus(admin: JsonHttpClient) -> str:
    payload = admin.get_text("/metrics")
    required_metrics = [
        "ai_risk_http_requests_total",
        "ai_risk_http_request_duration_seconds_bucket",
    ]
    missing = [metric for metric in required_metrics if metric not in payload]
    if missing:
        raise AssertionError(f"missing Prometheus metrics: {missing}")
    return "Prometheus metrics are scrapeable with admin token"


def _expect_equal(actual: Any, expected: Any) -> str:
    if actual != expected:
        raise AssertionError(f"expected {expected!r}, got {actual!r}")
    return f"value matched: {expected!r}"


def _build_admin_headers(
    header_name: str,
    token: str,
    token_file: str,
) -> dict[str, str]:
    if token_file:
        token = Path(token_file).read_text(encoding="utf-8").strip()
    if not token:
        return {}
    return {header_name: token}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate production readiness gates.")
    parser.add_argument("--agent-base-url", required=True)
    parser.add_argument(
        "--admin-header",
        default=os.getenv("AI_RISK_ADMIN_AUTH_HEADER", "X-Admin-Token"),
    )
    parser.add_argument(
        "--admin-token",
        default=os.getenv("AI_RISK_ADMIN_AUTH_TOKEN", ""),
    )
    parser.add_argument(
        "--admin-token-file",
        default=os.getenv("AI_RISK_ADMIN_AUTH_TOKEN_FILE", ""),
    )
    parser.add_argument(
        "--alert-rules",
        default=str(DEFAULT_ALERT_RULES_PATH),
    )
    parser.add_argument("--output")
    args = parser.parse_args(argv)

    report = run_readiness_gate(
        args.agent_base_url,
        admin_headers=_build_admin_headers(
            args.admin_header,
            args.admin_token,
            args.admin_token_file,
        ),
        alert_rules_path=Path(args.alert_rules),
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
