from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlencode
from urllib.request import Request, urlopen


EXPECTED_CAPABILITIES = ["knowledge", "investigation", "strategy", "graph", "copilot"]
EXPECTED_TOOLS = [
    "metric_snapshot",
    "case_lookup",
    "order_profile",
    "strategy_profile",
    "strategy_simulation",
    "graph_relation",
    "sql_query",
    "dashboard_snapshot",
    "rule_explain",
]
AGENT_QUERIES = {
    "knowledge": "营销套利案件的标准排查 SOP 是什么？",
    "investigation": "为什么巴西信用卡支付失败率突然升高？",
    "strategy": "请评估策略 STRAT-001 是否应该调整阈值",
    "graph": "请分析用户 U10001 是否属于团伙网络",
    "copilot": "请联合分析订单 O10001 和策略 STRAT-001，判断是否存在团伙风险并给出策略建议",
}


@dataclass
class ValidationCheck:
    name: str
    status: str
    detail: str
    duration_ms: float


class JsonHttpClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_sec: float = 10.0,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_sec = timeout_sec
        self._headers = headers or {}

    def get(self, path: str) -> Any:
        return self._request("GET", path)

    def post(self, path: str, payload: dict[str, Any]) -> Any:
        return self._request("POST", path, payload)

    def delete(self, path: str) -> Any:
        return self._request("DELETE", path)

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {
            **self._headers,
            **({"Content-Type": "application/json"} if data is not None else {}),
        }
        request = Request(
            f"{self._base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        with urlopen(request, timeout=self._timeout_sec) as response:
            return json.load(response)


class ValidationRunner:
    def __init__(self) -> None:
        self.checks: list[ValidationCheck] = []

    def check(self, name: str, operation: Callable[[], str]) -> None:
        started_at = time.perf_counter()
        try:
            detail = operation()
        except Exception as exc:
            self.checks.append(
                ValidationCheck(
                    name=name,
                    status="failed",
                    detail=f"{type(exc).__name__}: {exc}",
                    duration_ms=(time.perf_counter() - started_at) * 1000,
                )
            )
            return
        self.checks.append(
            ValidationCheck(
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


def run_contract_validation(
    risk_base_url: str,
    agent_base_url: str,
    *,
    agent_headers: dict[str, str] | None = None,
    central_audit_base_url: str | None = None,
    central_audit_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    risk = JsonHttpClient(risk_base_url)
    agent = JsonHttpClient(agent_base_url, headers=agent_headers)
    central_audit = (
        JsonHttpClient(central_audit_base_url, headers=central_audit_headers)
        if central_audit_base_url
        else None
    )
    runner = ValidationRunner()
    runner.check("risk.health", lambda: _expect_equal(risk.get("/healthz")["status"], "ok"))
    runner.check("agent.health", lambda: _expect_equal(agent.get("/healthz")["status"], "ok"))

    endpoint_checks = (
        (
            "risk.metric_snapshot",
            f"/metric-snapshots?{urlencode({'country': 'BR', 'channel': 'credit_card', 'time_range': 'recent_7d'})}",
            {
                "country",
                "channel",
                "time_range",
                "metric_name",
                "anomaly_started_at",
                "current_value",
                "baseline_value",
                "recent_change",
                "suspected_driver",
            },
            False,
        ),
        (
            "risk.case_records",
            f"/case-records?{urlencode({'country': 'ID', 'channel': 'wallet'})}",
            {"case_id", "country", "channel", "title"},
            True,
        ),
        (
            "risk.order_profile",
            "/order-profiles/O10001",
            {
                "order_id",
                "country",
                "channel",
                "recent_attempts",
                "triggered_rules",
                "risk_labels",
                "recommended_action",
            },
            False,
        ),
        (
            "risk.strategy_profile",
            "/strategy-profiles/STRAT-001",
            {
                "strategy_id",
                "name",
                "country",
                "channel",
                "status",
                "current_threshold",
                "hit_rate",
                "risk_capture_rate",
                "false_positive_rate",
                "recent_issue",
                "top_impacted_entities",
            },
            False,
        ),
        (
            "risk.strategy_simulation",
            "/strategy-simulations/STRAT-001",
            {
                "strategy_id",
                "recommended_threshold",
                "delta_intercepts",
                "delta_false_positives",
                "estimated_risk_reduction",
                "estimated_revenue_impact",
                "simulation_window",
                "recommendation_reason",
            },
            False,
        ),
        (
            "risk.graph_relation",
            "/graph-relations/U10001",
            {
                "entity_id",
                "entity_type",
                "risk_level",
                "shared_devices",
                "shared_ips",
                "linked_accounts",
                "linked_orders",
                "community_size",
                "key_path",
                "risk_reason",
            },
            False,
        ),
        (
            "risk.sql_query",
            f"/sql-queries/metric_breakdown?{urlencode({'country': 'BR', 'channel': 'credit_card', 'time_range': 'recent_24h', 'limit': 2})}",
            {
                "query_name",
                "country",
                "channel",
                "time_range",
                "description",
                "columns",
                "rows",
                "row_count",
                "limit",
            },
            False,
        ),
        (
            "risk.dashboard_snapshot",
            f"/dashboard-snapshots/risk_overview?{urlencode({'country': 'BR', 'channel': 'credit_card', 'time_range': 'recent_24h'})}",
            {
                "dashboard_id",
                "title",
                "country",
                "channel",
                "time_range",
                "metric_name",
                "current_value",
                "baseline_value",
                "trend",
                "largest_segment",
                "largest_segment_change",
                "recommended_drilldowns",
            },
            False,
        ),
        (
            "risk.rule_explain",
            f"/rule-explanations?{urlencode({'strategy_id': 'STRAT-001'})}",
            {
                "subject_id",
                "subject_type",
                "strategy_id",
                "decision",
                "explanation",
                "recent_change",
                "owner",
                "hit_rules",
            },
            False,
        ),
    )
    for name, path, fields, is_list in endpoint_checks:
        runner.check(
            name,
            lambda path=path, fields=fields, is_list=is_list: _validate_fields(
                risk.get(path),
                fields,
                is_list=is_list,
            ),
        )

    runner.check("agent.runtime_contract", lambda: _validate_runtime(agent.get("/admin/runtime")))
    runner.check("agent.knowledge", lambda: _validate_agent(agent, "knowledge", {}, []))
    runner.check(
        "agent.investigation",
        lambda: _validate_agent(
            agent,
            "investigation",
            {"country": "BR", "channel": "credit_card"},
            ["metric_snapshot", "case_lookup"],
        ),
    )
    runner.check(
        "agent.strategy",
        lambda: _validate_agent(
            agent,
            "strategy",
            {"strategy_id": "STRAT-001"},
            ["strategy_profile", "strategy_simulation"],
        ),
    )
    runner.check(
        "agent.graph",
        lambda: _validate_agent(
            agent,
            "graph",
            {"entity_id": "U10001"},
            ["graph_relation"],
        ),
    )
    runner.check(
        "agent.copilot",
        lambda: _validate_copilot(
            agent,
            {
                "order_id": "O10001",
                "strategy_id": "STRAT-001",
                "entity_id": "U10001",
            },
        ),
    )
    runner.check("agent.upstream_audit", lambda: _validate_upstream_audit(agent))
    runner.check(
        "agent.upstream_audit_integrity",
        lambda: _validate_upstream_audit_integrity(agent),
    )
    if central_audit is not None:
        runner.check(
            "central_audit.mirrored_events",
            lambda: _validate_central_audit_events(central_audit),
        )
    runner.check(
        "agent.prometheus",
        lambda: _validate_prometheus(agent_base_url, headers=agent_headers),
    )
    return runner.report()


def run_recovery_drill(
    risk_base_url: str,
    agent_base_url: str,
    *,
    reset_wait_sec: float = 0.5,
    agent_headers: dict[str, str] | None = None,
    central_audit_base_url: str | None = None,
    central_audit_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    risk = JsonHttpClient(risk_base_url)
    agent = JsonHttpClient(agent_base_url, headers=agent_headers)
    central_audit = (
        JsonHttpClient(central_audit_base_url, headers=central_audit_headers)
        if central_audit_base_url
        else None
    )
    runner = ValidationRunner()
    risk.delete("/admin/faults")

    runner.check(
        "recovery.transient_retry",
        lambda: _transient_retry_check(risk, agent),
    )
    runner.check(
        "recovery.circuit_opens",
        lambda: _circuit_open_check(risk, agent),
    )
    risk.delete("/admin/faults")
    time.sleep(reset_wait_sec)
    runner.check(
        "recovery.half_open_closes",
        lambda: _half_open_recovery_check(agent),
    )
    runner.check(
        "recovery.audit_evidence",
        lambda: _recovery_audit_evidence_check(agent),
    )
    if central_audit is not None:
        runner.check(
            "recovery.central_audit_evidence",
            lambda: _central_recovery_audit_evidence_check(central_audit),
        )
    risk.delete("/admin/faults")
    return runner.report()


def _transient_retry_check(risk: JsonHttpClient, agent: JsonHttpClient) -> str:
    risk.post(
        "/admin/faults",
        {"target_path": "/metric-snapshots", "status_code": 503, "remaining": 1},
    )
    response = _invoke_investigation(agent)
    trace = _tool_trace(response, "metric_snapshot")
    if trace["status"] != "success":
        raise AssertionError(f"expected retry recovery, got {trace}")
    return "one injected 503 recovered through retry"


def _circuit_open_check(risk: JsonHttpClient, agent: JsonHttpClient) -> str:
    risk.post(
        "/admin/faults",
        {"target_path": "/metric-snapshots", "status_code": 503, "remaining": 6},
    )
    first = _tool_trace(_invoke_investigation(agent), "metric_snapshot")
    second = _tool_trace(_invoke_investigation(agent), "metric_snapshot")
    third = _tool_trace(_invoke_investigation(agent), "metric_snapshot")
    if first["status"] != "failed" or second["status"] != "failed":
        raise AssertionError("expected two exhausted upstream requests")
    if third["status"] != "failed" or "circuit is open" not in third["summary"]:
        raise AssertionError(f"expected open circuit rejection, got {third}")
    return "circuit opened after two exhausted upstream requests"


def _half_open_recovery_check(agent: JsonHttpClient) -> str:
    response = _invoke_investigation(agent)
    trace = _tool_trace(response, "metric_snapshot")
    if trace["status"] != "success":
        raise AssertionError(f"expected half-open recovery, got {trace}")
    metrics = agent.get("/admin/metrics")
    gauge_name = "upstream.circuit.HttpMetricSnapshotClient.open"
    if metrics["gauges"].get(gauge_name) != 0.0:
        raise AssertionError(f"expected closed circuit gauge, got {metrics['gauges'].get(gauge_name)}")
    return "half-open probe succeeded and circuit closed"


def _recovery_audit_evidence_check(agent: JsonHttpClient) -> str:
    events = agent.get(
        "/admin/audit-events?"
        + urlencode({"limit": 200, "upstream_client": "HttpMetricSnapshotClient"})
    )
    outcomes = {event["outcome"] for event in events}
    required = {"success", "http_error", "circuit_rejected"}
    missing = required - outcomes
    if missing:
        raise AssertionError(f"recovery audit evidence missing outcomes: {sorted(missing)}")
    return "retry, circuit rejection, and recovery outcomes are auditable"


def _central_recovery_audit_evidence_check(central_audit: JsonHttpClient) -> str:
    payload = central_audit.get("/admin/events?limit=1000")
    events = [
        event
        for event in payload.get("events", [])
        if event.get("upstream_client") == "HttpMetricSnapshotClient"
    ]
    outcomes = {event.get("outcome") for event in events}
    required = {"success", "http_error", "circuit_rejected"}
    missing = required - outcomes
    if missing:
        raise AssertionError(
            f"central audit evidence missing recovery outcomes: {sorted(missing)}"
        )
    return "central audit sink captured retry, circuit rejection, and recovery outcomes"


def _invoke_investigation(agent: JsonHttpClient) -> dict[str, Any]:
    return agent.post(
        "/agents/investigation",
        {
            "query": "为什么巴西信用卡支付失败率突然升高？",
            "context": {"country": "BR", "channel": "credit_card"},
        },
    )


def _validate_runtime(payload: dict[str, Any]) -> str:
    if payload["supported_capabilities"] != EXPECTED_CAPABILITIES:
        raise AssertionError("supported capabilities do not match Phase 1 contract")
    if payload["registered_tools"] != EXPECTED_TOOLS:
        raise AssertionError("registered tools do not match Phase 1 contract")
    if payload["readiness"]["status"] != "ready":
        raise AssertionError(f"runtime is not ready: {payload['readiness']}")
    return "runtime capabilities, tools, and readiness match"


def _validate_agent(
    agent: JsonHttpClient,
    name: str,
    context: dict[str, Any],
    expected_tools: list[str],
) -> str:
    response = agent.post(
        f"/agents/{name}",
        {"query": AGENT_QUERIES[name], "context": context},
    )
    if response["agent_name"] != name:
        raise AssertionError(f"expected agent {name}, got {response['agent_name']}")
    trace_names = {trace["name"] for trace in response["tool_traces"]}
    missing = set(expected_tools) - trace_names
    if missing:
        raise AssertionError(f"missing tool traces: {sorted(missing)}")
    failed = {
        trace["name"]: trace["summary"]
        for trace in response["tool_traces"]
        if trace["name"] in expected_tools and trace["status"] != "success"
    }
    if failed:
        raise AssertionError(f"expected successful tool traces, got {failed}")
    return f"{name} responded with expected tool traces"


def _validate_copilot(agent: JsonHttpClient, context: dict[str, Any]) -> str:
    response = agent.post(
        "/agents/copilot",
        {"query": AGENT_QUERIES["copilot"], "context": context},
    )
    if response["agent_name"] != "copilot":
        raise AssertionError(f"expected agent copilot, got {response['agent_name']}")
    if response["intent"] != "composite":
        raise AssertionError(f"expected composite intent, got {response['intent']}")
    expected_steps = ["调查", "策略", "图谱"]
    if response["plan_steps"] != expected_steps:
        raise AssertionError(f"expected plan {expected_steps}, got {response['plan_steps']}")
    selected_steps = [
        trace["step"]
        for trace in response["planner_trace"]
        if trace["selected"]
    ]
    if selected_steps != expected_steps:
        raise AssertionError(f"expected selected planner steps {expected_steps}, got {selected_steps}")

    traces = response["tool_traces"]
    missing_prefixes = [
        prefix
        for prefix in expected_steps
        if not any(trace["name"].startswith(f"{prefix}::") for trace in traces)
    ]
    if missing_prefixes:
        raise AssertionError(f"missing orchestrated tool traces: {missing_prefixes}")
    failed = {
        trace["name"]: trace["summary"]
        for trace in traces
        if trace["status"] != "success"
    }
    if failed:
        raise AssertionError(f"expected successful orchestrated tool traces, got {failed}")
    return "copilot selected and completed investigation, strategy, and graph"


def _validate_fields(payload: Any, fields: set[str], *, is_list: bool) -> str:
    item = payload[0] if is_list and payload else payload
    if not isinstance(item, dict):
        raise AssertionError("response payload is not an object")
    missing = fields - set(item)
    if missing:
        raise AssertionError(f"missing fields: {sorted(missing)}")
    return f"required fields present: {len(fields)}"


def _validate_prometheus(
    agent_base_url: str,
    *,
    headers: dict[str, str] | None = None,
) -> str:
    request = Request(
        f"{agent_base_url.rstrip('/')}/metrics",
        headers=headers or {},
        method="GET",
    )
    with urlopen(request, timeout=10.0) as response:
        payload = response.read().decode("utf-8")
    if "ai_risk_http_requests_total" not in payload:
        raise AssertionError("Prometheus request counter is missing")
    return "Prometheus metrics endpoint is scrapeable"


def _validate_upstream_audit(agent: JsonHttpClient) -> str:
    events = agent.get("/admin/audit-events?limit=200")
    if not events:
        raise AssertionError("no upstream audit events found after agent validation")
    required_fields = {
        "event_id",
        "occurred_at",
        "upstream_client",
        "target_url",
        "outcome",
        "request_header_names",
    }
    for event in events:
        missing = required_fields - set(event)
        if missing:
            raise AssertionError(f"audit event missing fields: {sorted(missing)}")
    rendered = json.dumps(
        [unquote(event["target_url"]) for event in events],
        ensure_ascii=False,
    )
    sensitive_values = ("O10001", "U10001", "STRAT-001", "credit_card", "BR")
    leaked = [value for value in sensitive_values if value in rendered]
    if leaked:
        raise AssertionError(f"audit events contain unredacted values: {leaked}")
    return f"upstream audit query returned {len(events)} redacted records"


def _validate_upstream_audit_integrity(agent: JsonHttpClient) -> str:
    payload = agent.get("/admin/audit-integrity")
    if payload["status"] == "failed":
        raise AssertionError(f"upstream audit integrity failed: {payload}")
    if not payload["integrity_enabled"]:
        raise AssertionError("upstream audit integrity is disabled")
    return (
        "upstream audit integrity status="
        f"{payload['status']} verified={payload['verified_records']}"
    )


def _validate_central_audit_events(central_audit: JsonHttpClient) -> str:
    payload = central_audit.get("/admin/events?limit=500")
    events = payload.get("events", [])
    if not events:
        raise AssertionError("no mirrored central audit events found")
    for event in events:
        event_hash = event.get("audit_hash")
        previous_hash = event.get("audit_previous_hash")
        if not isinstance(event_hash, str) or len(event_hash) != 64:
            raise AssertionError("central audit event missing audit_hash")
        if not isinstance(previous_hash, str):
            raise AssertionError("central audit event missing audit_previous_hash")
    rendered = json.dumps(
        [unquote(str(event.get("target_url", ""))) for event in events],
        ensure_ascii=False,
    )
    sensitive_values = ("O10001", "U10001", "STRAT-001", "credit_card", "BR")
    leaked = [value for value in sensitive_values if value in rendered]
    if leaked:
        raise AssertionError(f"central audit events contain unredacted values: {leaked}")
    return f"central audit sink received {len(events)} tamper-evident records"


def _tool_trace(response: dict[str, Any], name: str) -> dict[str, Any]:
    return next(trace for trace in response["tool_traces"] if trace["name"] == name)


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
    parser = argparse.ArgumentParser(description="Validate staging contracts and recovery.")
    parser.add_argument("--risk-base-url", required=True)
    parser.add_argument("--agent-base-url", required=True)
    parser.add_argument("--fault-drill", action="store_true")
    parser.add_argument("--reset-wait-sec", type=float, default=0.5)
    parser.add_argument(
        "--agent-admin-header",
        default=os.getenv("AI_RISK_ADMIN_AUTH_HEADER", "X-Admin-Token"),
    )
    parser.add_argument(
        "--agent-admin-token",
        default=os.getenv("AI_RISK_ADMIN_AUTH_TOKEN", ""),
    )
    parser.add_argument(
        "--agent-admin-token-file",
        default=os.getenv("AI_RISK_ADMIN_AUTH_TOKEN_FILE", ""),
    )
    parser.add_argument("--central-audit-base-url")
    parser.add_argument(
        "--central-audit-header",
        default=os.getenv("AI_RISK_AUDIT_CENTRAL_AUTH_HEADER", "Authorization"),
    )
    parser.add_argument(
        "--central-audit-token",
        default=os.getenv("AI_RISK_AUDIT_CENTRAL_AUTH_TOKEN", ""),
    )
    parser.add_argument(
        "--central-audit-token-file",
        default=os.getenv("AI_RISK_AUDIT_CENTRAL_AUTH_TOKEN_FILE", ""),
    )
    parser.add_argument("--output")
    args = parser.parse_args(argv)

    agent_headers = _build_admin_headers(
        args.agent_admin_header,
        args.agent_admin_token,
        args.agent_admin_token_file,
    )
    report = run_contract_validation(
        args.risk_base_url,
        args.agent_base_url,
        agent_headers=agent_headers,
        central_audit_base_url=args.central_audit_base_url,
        central_audit_headers=_build_admin_headers(
            args.central_audit_header,
            args.central_audit_token,
            args.central_audit_token_file,
        ),
    )
    if args.fault_drill:
        recovery = run_recovery_drill(
            args.risk_base_url,
            args.agent_base_url,
            reset_wait_sec=args.reset_wait_sec,
            agent_headers=agent_headers,
            central_audit_base_url=args.central_audit_base_url,
            central_audit_headers=_build_admin_headers(
                args.central_audit_header,
                args.central_audit_token,
                args.central_audit_token_file,
            ),
        )
        report["recovery_drill"] = recovery
        if recovery["status"] != "passed":
            report["status"] = "failed"
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
