from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from api import create_app, fastapi_app
from core.models import ToolResult
from services.audit import JsonLinesAuditLog, build_upstream_audit_event
from services.observability import LOGGER_NAME
from settings import AppConfig
from tools.registry import ToolRegistry


class AgentApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(fastapi_app)

    def test_healthz(self) -> None:
        response = self.client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_list_agents(self) -> None:
        response = self.client.get("/agents")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"agents": ["knowledge", "investigation", "strategy", "graph", "copilot"]})

    def test_create_and_get_session(self) -> None:
        created = self.client.post("/sessions")
        session_id = created.json()["session_id"]

        fetched = self.client.get(f"/sessions/{session_id}")
        self.assertEqual(created.status_code, 200)
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["session_id"], session_id)
        self.assertEqual(fetched.json()["turns"], [])
        self.assertEqual(fetched.json()["timeline"], [])

    def test_invoke_knowledge_agent(self) -> None:
        response = self.client.post(
            "/agents/knowledge",
            json={"query": "营销套利案件的标准排查 SOP 是什么？"},
        )

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["session_id"])
        self.assertEqual(payload["agent_name"], "knowledge")
        self.assertTrue(payload["citations"])
        self.assertIn("X-Request-Id", response.headers)
        self.assertIn("X-Trace-Id", response.headers)

    def test_request_id_and_trace_id_headers_are_propagated(self) -> None:
        with self.assertLogs(LOGGER_NAME, level="INFO") as captured:
            response = self.client.post(
                "/agents/knowledge",
                headers={"X-Request-Id": "req-abc", "X-Trace-Id": "trace-def"},
                json={"query": "营销套利案件的标准排查 SOP 是什么？"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Request-Id"], "req-abc")
        self.assertEqual(response.headers["X-Trace-Id"], "trace-def")
        payloads = [json.loads(record.split("INFO:ai_risk_decision_platform:", 1)[1]) for record in captured.output]
        self.assertTrue(any(item["event"] == "http_request_started" for item in payloads))
        self.assertTrue(any(item["event"] == "agent_execution_completed" for item in payloads))
        self.assertTrue(all(item["request_id"] == "req-abc" for item in payloads))
        self.assertTrue(all(item["trace_id"] == "trace-def" for item in payloads))

    def test_invoke_investigation_agent(self) -> None:
        created = self.client.post("/sessions")
        session_id = created.json()["session_id"]
        response = self.client.post(
            "/agents/investigation",
            json={
                "query": "请分析这个订单为什么被判高风险",
                "context": {"order_id": "O10001"},
                "session_id": session_id,
            },
        )

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["session_id"], session_id)
        self.assertEqual(payload["agent_name"], "investigation")
        self.assertTrue(any(trace["name"] == "order_profile" for trace in payload["tool_traces"]))
        self.assertTrue(any(trace["name"] == "graph_relation" for trace in payload["tool_traces"]))
        self.assertTrue(any("关键路径" in finding for finding in payload["findings"]))

        fetched = self.client.get(f"/sessions/{session_id}")
        self.assertEqual(len(fetched.json()["turns"]), 1)
        self.assertEqual(fetched.json()["timeline"][0]["title"], "风险调查")
        self.assertEqual(fetched.json()["timeline"][0]["agent_group"], "analysis")
        self.assertEqual(fetched.json()["timeline"][0]["badge"], "analysis")
        self.assertEqual(fetched.json()["timeline"][0]["severity"], "medium")

    def test_invoke_investigation_agent_with_missing_order_returns_degraded_trace(self) -> None:
        response = self.client.post(
            "/agents/investigation",
            json={
                "query": "请分析这个订单为什么被判高风险",
                "context": {"order_id": "MISSING"},
            },
        )

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertIn("暂时无法完成订单 MISSING 的完整调查", payload["summary"])
        self.assertTrue(any(trace["status"] == "degraded" for trace in payload["tool_traces"]))

    def test_invoke_investigation_agent_with_failed_metric_tool_returns_failed_trace(self) -> None:
        def fake_execute(self, name, **kwargs):  # type: ignore[no-untyped-def]
            if name == "metric_snapshot":
                return ToolResult.failed_result(
                    name=name,
                    payload={},
                    summary="工具调用失败",
                    error="upstream 503",
                    error_type="HTTPError",
                )
            if name == "case_lookup":
                return ToolResult.success_result(
                    name=name,
                    payload=[
                        {
                            "case_id": "BR-1",
                            "country": "BR",
                            "channel": "credit_card",
                            "title": "阈值回退案例",
                        }
                    ],
                    summary="返回 1 条历史相似案例",
                )
            return ToolResult.degraded_result(
                name=name,
                payload={},
                summary="未命中测试桩",
                error="not stubbed",
                error_type="test_stub",
            )

        with patch.object(ToolRegistry, "execute", autospec=True, side_effect=fake_execute):
            response = self.client.post(
                "/agents/investigation",
                json={
                    "query": "为什么巴西信用卡支付失败率从昨晚开始突然升高？",
                    "context": {"country": "BR", "channel": "credit_card"},
                },
            )

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertIn("指标快照调用失败", payload["summary"])
        self.assertTrue(any(trace["status"] == "failed" for trace in payload["tool_traces"]))

    def test_unknown_agent_returns_404(self) -> None:
        response = self.client.post(
            "/agents/unknown",
            json={"query": "test"},
        )

        self.assertEqual(response.status_code, 404)

    def test_get_unknown_session_returns_404(self) -> None:
        response = self.client.get("/sessions/missing-session")

        self.assertEqual(response.status_code, 404)

    def test_reload_knowledge_for_file_backend(self) -> None:
        app = create_app(
            AppConfig(
                knowledge_backend="file",
                tool_backend="file",
                knowledge_dir=Path("data/knowledge"),
                metric_snapshot_path=Path("data/risk/metric_snapshots.json"),
                case_record_path=Path("data/risk/case_records.json"),
                order_profile_path=Path("data/risk/order_profiles.json"),
            )
        )
        client = TestClient(app)

        response = client.post("/admin/knowledge/reload")

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(payload["documents_loaded"], 4)
        self.assertEqual(payload["documents_loaded"], payload["total_documents"])

    def test_runtime_info_endpoint(self) -> None:
        app = create_app(
            AppConfig(
                knowledge_backend="file",
                tool_backend="file",
                knowledge_dir=Path("data/knowledge"),
                metric_snapshot_path=Path("data/risk/metric_snapshots.json"),
                case_record_path=Path("data/risk/case_records.json"),
                order_profile_path=Path("data/risk/order_profiles.json"),
            )
        )
        client = TestClient(app)

        response = client.get("/admin/runtime")

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["knowledge_backend"], "file")
        self.assertEqual(payload["tool_backend"], "file")
        self.assertEqual(payload["planner_backend"], "rule")
        self.assertEqual(payload["planner_source"], "rule")
        self.assertEqual(payload["investigation_backend"], "rule")
        self.assertEqual(payload["investigation_source"], "rule")
        self.assertEqual(payload["strategy_backend"], "rule")
        self.assertEqual(payload["strategy_source"], "rule")
        self.assertEqual(payload["planner_openai_base_url"], "https://api.openai.com/v1")
        self.assertEqual(payload["planner_openai_model"], "gpt-4o-mini")
        self.assertEqual(payload["planner_openai_timeout_sec"], 10.0)
        self.assertEqual(payload["planner_openai_reasoning_effort"], "low")
        self.assertEqual(payload["planner_openai_max_output_tokens"], 400)
        self.assertEqual(payload["planner_openai_api_key_source"], "none")
        self.assertEqual(payload["investigation_openai_base_url"], "https://api.openai.com/v1")
        self.assertEqual(payload["investigation_openai_model"], "gpt-4o-mini")
        self.assertEqual(payload["investigation_openai_timeout_sec"], 10.0)
        self.assertEqual(payload["investigation_openai_reasoning_effort"], "low")
        self.assertEqual(payload["investigation_openai_max_output_tokens"], 400)
        self.assertEqual(payload["investigation_openai_api_key_source"], "none")
        self.assertEqual(payload["strategy_openai_base_url"], "https://api.openai.com/v1")
        self.assertEqual(payload["strategy_openai_model"], "gpt-4o-mini")
        self.assertEqual(payload["strategy_openai_timeout_sec"], 10.0)
        self.assertEqual(payload["strategy_openai_reasoning_effort"], "low")
        self.assertEqual(payload["strategy_openai_max_output_tokens"], 400)
        self.assertEqual(payload["strategy_openai_api_key_source"], "none")
        self.assertEqual(payload["session_store_backend"], "memory")
        self.assertEqual(payload["session_store_path"], ".data/sessions.json")
        self.assertEqual(payload["case_store_backend"], "memory")
        self.assertEqual(payload["case_store_path"], ".data/cases.json")
        self.assertEqual(payload["database_path"], ".data/platform.db")
        self.assertFalse(payload["postgres_dsn_configured"])
        self.assertEqual(payload["postgres_dsn_source"], "none")
        self.assertEqual(payload["tool_http_timeout_sec"], 5.0)
        self.assertEqual(payload["tool_http_retry_attempts"], 2)
        self.assertEqual(payload["tool_http_retry_backoff_sec"], 0.1)
        self.assertEqual(payload["tool_http_circuit_breaker_failure_threshold"], 5)
        self.assertEqual(payload["tool_http_circuit_breaker_reset_sec"], 30.0)
        self.assertEqual(payload["tool_http_auth_mode"], "none")
        self.assertEqual(payload["tool_http_auth_header"], "Authorization")
        self.assertEqual(payload["tool_http_auth_token_source"], "none")
        self.assertTrue(payload["tool_http_audit_enabled"])
        self.assertEqual(payload["tool_http_audit_path"], ".data/upstream-audit.jsonl")
        self.assertEqual(payload["tool_http_audit_max_bytes"], 10 * 1024 * 1024)
        self.assertEqual(payload["tool_http_audit_max_files"], 5)
        self.assertTrue(payload["tool_http_audit_integrity_enabled"])
        self.assertFalse(payload["audit_central_enabled"])
        self.assertFalse(payload["audit_central_url_configured"])
        self.assertEqual(payload["audit_central_timeout_sec"], 3.0)
        self.assertEqual(payload["audit_central_auth_header"], "Authorization")
        self.assertEqual(payload["audit_central_auth_token_source"], "none")
        self.assertEqual(payload["risk_decision_policy_source"], "builtin")
        self.assertIsNone(payload["risk_decision_policy_path"])
        self.assertFalse(payload["admin_auth_enabled"])
        self.assertEqual(payload["admin_auth_header"], "X-Admin-Token")
        self.assertEqual(payload["admin_auth_token_source"], "none")
        self.assertFalse(payload["admin_auth_configured"])
        self.assertEqual(payload["tool_http_metric_path"], "/metric-snapshots")
        self.assertEqual(payload["tool_http_strategy_profile_path_template"], "/strategy-profiles/{strategy_id}")
        self.assertEqual(payload["tool_http_graph_relation_path_template"], "/graph-relations/{entity_id}")
        self.assertEqual(payload["tool_http_sql_query_path_template"], "/sql-queries/{query_name}")
        self.assertEqual(payload["tool_http_dashboard_snapshot_path_template"], "/dashboard-snapshots/{dashboard_id}")
        self.assertEqual(payload["tool_http_rule_explain_path"], "/rule-explanations")
        self.assertEqual(payload["tool_http_country_param"], "country")
        self.assertEqual(payload["tool_http_channel_param"], "channel")
        self.assertEqual(payload["registered_agents"], ["knowledge", "investigation", "strategy", "graph", "copilot"])
        self.assertEqual(
            payload["registered_tools"],
            [
                "metric_snapshot",
                "case_lookup",
                "order_profile",
                "strategy_profile",
                "strategy_simulation",
                "graph_relation",
                "sql_query",
                "dashboard_snapshot",
                "rule_explain",
            ],
        )
        self.assertEqual(
            payload["supported_capabilities"],
            ["knowledge", "investigation", "strategy", "graph", "copilot"],
        )
        self.assertEqual(
            [item["name"] for item in payload["capability_contract"]],
            ["knowledge", "investigation", "strategy", "graph", "copilot"],
        )
        self.assertEqual(
            [item["tool_name"] for item in payload["http_endpoint_contract"]],
            [
                "metric_snapshot",
                "case_lookup",
                "order_profile",
                "strategy_profile",
                "strategy_simulation",
                "graph_relation",
                "sql_query",
                "dashboard_snapshot",
                "rule_explain",
            ],
        )
        self.assertEqual(
            payload["http_endpoint_contract"][0]["query_params"],
            {
                "country_env_var": "AI_RISK_TOOL_HTTP_COUNTRY_PARAM",
                "country_name": "country",
                "channel_env_var": "AI_RISK_TOOL_HTTP_CHANNEL_PARAM",
                "channel_name": "channel",
            },
        )
        self.assertEqual(payload["observability"]["prometheus_metrics_path"], "/metrics")
        self.assertEqual(payload["observability"]["upstream_audit_path"], "/admin/audit-events")
        self.assertEqual(
            payload["observability"]["upstream_audit_integrity_path"],
            "/admin/audit-integrity",
        )
        self.assertIn(
            "http.request.duration_seconds",
            payload["observability"]["duration_histograms"],
        )
        self.assertEqual(payload["readiness"]["status"], "ready")
        self.assertEqual(
            [item["name"] for item in payload["readiness"]["checks"]],
            ["knowledge_index", "agent_registry", "tool_registry", "session_store", "case_store"],
        )

    def test_phase1_tool_endpoints(self) -> None:
        app = create_app()
        client = TestClient(app)

        sql_response = client.post(
            "/tools/sql/query",
            json={
                "query_name": "metric_breakdown",
                "parameters": {"country": "BR", "channel": "credit_card", "time_range": "recent_24h"},
                "limit": 2,
            },
        )
        dashboard_response = client.post(
            "/tools/dashboard/snapshot",
            json={
                "dashboard_id": "risk_overview",
                "country": "BR",
                "channel": "credit_card",
                "time_range": "recent_24h",
            },
        )
        rule_response = client.post(
            "/tools/rules/explain",
            json={"order_id": "O10001"},
        )

        self.assertEqual(sql_response.status_code, 200)
        self.assertEqual(sql_response.json()["status"], "success")
        self.assertEqual(sql_response.json()["payload"]["row_count"], 2)
        self.assertEqual(dashboard_response.status_code, 200)
        self.assertEqual(dashboard_response.json()["payload"]["largest_segment"], "shared_device")
        self.assertEqual(rule_response.status_code, 200)
        self.assertEqual(rule_response.json()["payload"]["subject_id"], "O10001")

    def test_audit_events_endpoint_filters_redacted_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            audit_path = Path(tmp_dir) / "audit.jsonl"
            audit_log = JsonLinesAuditLog(audit_path)
            audit_log.record(
                build_upstream_audit_event(
                    upstream_client="HttpOrderProfileClient",
                    method="GET",
                    url="https://risk.example.com/orders/O10001",
                    outcome="success",
                    attempt=1,
                    total_attempts=1,
                    status_code=200,
                )
            )
            app = create_app(AppConfig(tool_http_audit_path=audit_path))
            client = TestClient(app)

            response = client.get(
                "/admin/audit-events",
                params={"outcome": "success", "upstream_client": "HttpOrderProfileClient"},
            )

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["outcome"], "success")
        self.assertNotIn("O10001", payload[0]["target_url"])
        self.assertEqual(len(payload[0]["audit_hash"]), 64)

    def test_audit_integrity_endpoint_reports_hash_chain_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            audit_path = Path(tmp_dir) / "audit.jsonl"
            audit_log = JsonLinesAuditLog(audit_path)
            audit_log.record(
                build_upstream_audit_event(
                    upstream_client="HttpOrderProfileClient",
                    method="GET",
                    url="https://risk.example.com/orders/O10001",
                    outcome="success",
                    attempt=1,
                    total_attempts=1,
                    status_code=200,
                )
            )
            app = create_app(AppConfig(tool_http_audit_path=audit_path))
            client = TestClient(app)

            response = client.get("/admin/audit-integrity")

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["status"], "passed")
        self.assertEqual(payload["verified_records"], 1)
        self.assertEqual(payload["invalid_records"], 0)

    def test_admin_endpoints_require_token_when_enabled(self) -> None:
        app = create_app(
            AppConfig(
                admin_auth_enabled=True,
                admin_auth_token="admin-secret",
            )
        )
        client = TestClient(app)

        runtime_without_token = client.get("/admin/runtime")
        metrics_without_token = client.get("/metrics")
        reload_without_token = client.post("/admin/knowledge/reload")
        public_health = client.get("/healthz")
        runtime_with_token = client.get(
            "/admin/runtime",
            headers={"X-Admin-Token": "admin-secret"},
        )
        runtime_with_bad_token = client.get(
            "/admin/runtime",
            headers={"X-Admin-Token": "wrong"},
        )

        self.assertEqual(runtime_without_token.status_code, 401)
        self.assertEqual(metrics_without_token.status_code, 401)
        self.assertEqual(reload_without_token.status_code, 401)
        self.assertEqual(public_health.status_code, 200)
        self.assertEqual(runtime_with_bad_token.status_code, 401)
        self.assertEqual(runtime_with_token.status_code, 200)
        payload = runtime_with_token.json()
        self.assertTrue(payload["admin_auth_enabled"])
        self.assertTrue(payload["admin_auth_configured"])
        self.assertEqual(payload["admin_auth_token_source"], "env")
        self.assertNotIn("admin-secret", json.dumps(payload))

    def test_runtime_info_checks_sqlite_database_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            database_path = Path(tmp_dir) / "platform.db"
            app = create_app(
                AppConfig(
                    session_store_backend="sqlite",
                    case_store_backend="sqlite",
                    database_path=database_path,
                )
            )
            client = TestClient(app)

            response = client.get("/admin/runtime")

            payload = response.json()
            checks = {item["name"]: item for item in payload["readiness"]["checks"]}
            self.assertEqual(response.status_code, 200)
            self.assertEqual(payload["database_path"], str(database_path))
            self.assertEqual(payload["readiness"]["status"], "ready")
            self.assertEqual(checks["session_store"]["status"], "ready")
            self.assertEqual(checks["case_store"]["status"], "ready")
            self.assertIn(str(database_path), checks["session_store"]["detail"])

    def test_metrics_endpoint_exposes_runtime_counters(self) -> None:
        self.client.post(
            "/agents/knowledge",
            json={"query": "营销套利案件的标准排查 SOP 是什么？"},
        )

        response = self.client.get("/admin/metrics")

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(payload["counters"]["events.total"], 1)
        self.assertGreaterEqual(payload["counters"]["agent.executions.completed"], 1)
        self.assertGreaterEqual(payload["counters"]["http.requests.completed"], 1)
        self.assertIn("cases.total", payload["gauges"])
        self.assertIn("http.request.duration_seconds", payload["histograms"])
        self.assertIn("agent.execution.duration_seconds", payload["histograms"])

    def test_prometheus_metrics_endpoint_exposes_standard_format(self) -> None:
        self.client.post(
            "/agents/knowledge",
            json={"query": "营销套利案件的标准排查 SOP 是什么？"},
        )

        response = self.client.get("/metrics")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/plain", response.headers["content-type"])
        self.assertIn("# TYPE ai_risk_http_requests_total counter", response.text)
        self.assertIn(
            "# TYPE ai_risk_http_request_duration_seconds histogram",
            response.text,
        )
        self.assertIn(
            'ai_risk_http_request_duration_seconds_bucket{le="+Inf"}',
            response.text,
        )
        self.assertIn("# TYPE ai_risk_cases_total gauge", response.text)

    def test_invoke_strategy_agent(self) -> None:
        response = self.client.post(
            "/agents/strategy",
            json={
                "query": "请评估策略 STRAT-001 是否应该调整阈值",
                "context": {"strategy_id": "STRAT-001"},
            },
        )

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["agent_name"], "strategy")
        self.assertTrue(any(trace["name"] == "strategy_profile" for trace in payload["tool_traces"]))
        self.assertTrue(any(trace["name"] == "graph_relation" for trace in payload["tool_traces"]))
        self.assertTrue(any("图谱风险" in finding for finding in payload["findings"]))

    def test_invoke_graph_agent(self) -> None:
        response = self.client.post(
            "/agents/graph",
            json={
                "query": "请分析订单 O10001 是否属于团伙网络",
                "context": {"entity_id": "O10001"},
            },
        )

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["agent_name"], "graph")
        self.assertTrue(any(trace["name"] == "graph_relation" for trace in payload["tool_traces"]))

    def test_invoke_copilot_agent(self) -> None:
        created = self.client.post("/sessions")
        session_id = created.json()["session_id"]
        response = self.client.post(
            "/agents/copilot",
            json={
                "query": "请联合分析订单 O10001 和策略 STRAT-001，判断是否存在团伙风险并给出策略建议",
                "context": {"order_id": "O10001", "strategy_id": "STRAT-001", "entity_id": "U10001"},
                "session_id": session_id,
            },
        )

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["agent_name"], "copilot")
        self.assertEqual(payload["session_id"], session_id)
        self.assertEqual(payload["intent"], "composite")
        self.assertEqual(payload["plan_steps"], ["调查", "策略", "图谱"])
        self.assertEqual(
            [(trace["step"], trace["selected"]) for trace in payload["planner_trace"]],
            [("调查", True), ("策略", True), ("图谱", True)],
        )
        self.assertIn("识别意图为 composite", payload["summary"])
        self.assertIn("调查 -> 策略 -> 图谱", payload["summary"])
        self.assertTrue(any(finding == "[意图] composite" for finding in payload["findings"]))
        self.assertTrue(any(finding.startswith("[规划] 调查") for finding in payload["findings"]))
        self.assertTrue(any(trace["name"].startswith("调查::") for trace in payload["tool_traces"]))
        self.assertTrue(any(trace["name"].startswith("策略::") for trace in payload["tool_traces"]))
        self.assertTrue(any(trace["name"].startswith("图谱::") for trace in payload["tool_traces"]))
        self.assertEqual(payload["artifacts"]["risk_decision"]["decision"], "escalate_review")
        self.assertEqual(payload["artifacts"]["risk_decision"]["risk_level"], "high")
        self.assertEqual(
            payload["artifacts"]["risk_decision"]["action_plan"]["queue"],
            "manual_review_queue",
        )
        self.assertEqual(
            payload["artifacts"]["risk_decision"]["action_plan"]["sla_hours"],
            4,
        )

        fetched = self.client.get(f"/sessions/{session_id}")
        turn = fetched.json()["turns"][0]
        self.assertEqual(turn["agent_name"], "copilot")
        self.assertEqual(turn["title"], "联合分析")
        self.assertEqual(turn["status"], "completed")
        self.assertEqual(turn["agent_group"], "workflow")
        self.assertEqual(turn["badge"], "workflow")
        self.assertEqual(turn["severity"], "high")
        self.assertEqual(
            turn["expanded_sections"],
            ["intent", "plan", "decision", "planner_trace", "findings", "actions"],
        )
        self.assertEqual(turn["artifacts"]["risk_decision"]["recommended_action"], "manual_review")
        self.assertEqual(
            turn["artifacts"]["risk_decision"]["action_plan"]["priority"],
            "high",
        )
        self.assertEqual(turn["intent"], "composite")
        self.assertEqual(turn["plan_steps"], ["调查", "策略", "图谱"])
        self.assertEqual(
            [(trace["step"], trace["selected"]) for trace in turn["planner_trace"]],
            [("调查", True), ("策略", True), ("图谱", True)],
        )
        timeline_item = fetched.json()["timeline"][0]
        self.assertEqual(timeline_item["turn_index"], 1)
        self.assertEqual(timeline_item["title"], "联合分析")
        self.assertEqual(timeline_item["agent_group"], "workflow")
        self.assertEqual(timeline_item["badge"], "workflow")
        self.assertEqual(timeline_item["severity"], "high")
        self.assertEqual(timeline_item["intent"], "composite")
        self.assertEqual(timeline_item["plan_steps"], ["调查", "策略", "图谱"])

    def test_invoke_copilot_agent_with_order_only_context(self) -> None:
        response = self.client.post(
            "/agents/copilot",
            json={
                "query": "请分析这个订单为什么被判高风险",
                "context": {"order_id": "O10001"},
            },
        )

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["intent"], "order_case")
        self.assertEqual(payload["plan_steps"], ["调查", "图谱"])

    def test_create_case_from_copilot_session_and_update_status(self) -> None:
        client = TestClient(create_app())
        created = client.post("/sessions")
        session_id = created.json()["session_id"]
        self.assertEqual(created.status_code, 200)
        client.post(
            "/agents/copilot",
            json={
                "query": "请联合分析订单 O10001 和策略 STRAT-001，判断是否存在团伙风险并给出策略建议",
                "context": {"order_id": "O10001", "strategy_id": "STRAT-001", "entity_id": "U10001"},
                "session_id": session_id,
            },
        )

        created_case = client.post(f"/cases/from-session/{session_id}")

        payload = created_case.json()
        self.assertEqual(created_case.status_code, 200)
        self.assertEqual(payload["session_id"], session_id)
        self.assertEqual(payload["source_agent"], "copilot")
        self.assertEqual(payload["status"], "strategy_pending")
        self.assertEqual(payload["severity"], "high")
        self.assertEqual(payload["risk_decision"]["decision"], "escalate_review")
        self.assertEqual(payload["risk_decision"]["risk_level"], "high")
        self.assertEqual(
            payload["risk_decision"]["action_plan"]["queue"],
            "manual_review_queue",
        )
        self.assertEqual(payload["risk_decision"]["action_plan"]["sla_hours"], 4)
        self.assertEqual(payload["risk_decision"]["action_plan"]["status"], "queued")
        self.assertIsNone(payload["risk_decision"]["action_plan"]["assigned_to"])
        self.assertIsNone(payload["risk_decision"]["action_plan"]["completed_at"])
        created_at_dt = datetime.fromisoformat(payload["created_at"].replace("Z", "+00:00"))
        due_at_dt = datetime.fromisoformat(
            payload["risk_decision"]["action_plan"]["due_at"].replace("Z", "+00:00")
        )
        self.assertEqual(due_at_dt, created_at_dt + timedelta(hours=4))
        self.assertEqual(payload["strategy_recommendation"]["strategy_id"], "STRAT-001")
        self.assertEqual(
            payload["strategy_recommendation"]["validation_window"],
            "shadow evaluation",
        )
        self.assertTrue(payload["suggested_actions"])
        self.assertTrue(payload["created_at"].endswith("Z"))
        self.assertEqual(payload["created_at"], payload["updated_at"])

        listed = client.get("/cases")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()), 1)

        updated = client.patch(
            f"/cases/{payload['case_id']}",
            json={
                "status": "closed",
                "note": "人工复核完成",
                "assigned_to": "risk-reviewer-01",
                "action_outcome": "approved_after_review",
            },
        )
        updated_payload = updated.json()
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated_payload["status"], "closed")
        self.assertEqual(
            updated_payload["risk_decision"]["action_plan"]["status"],
            "completed",
        )
        self.assertEqual(
            updated_payload["risk_decision"]["action_plan"]["assigned_to"],
            "risk-reviewer-01",
        )
        self.assertEqual(
            updated_payload["risk_decision"]["action_plan"]["outcome"],
            "approved_after_review",
        )
        self.assertEqual(
            updated_payload["risk_decision"]["action_plan"]["completed_at"],
            updated_payload["updated_at"],
        )
        self.assertEqual(len(updated_payload["history"]), 2)
        self.assertEqual(updated_payload["history"][1]["summary"], "人工复核完成")
        self.assertNotEqual(updated_payload["updated_at"], updated_payload["created_at"])

    def test_list_cases_supports_filters(self) -> None:
        client = TestClient(create_app())
        created = client.post("/sessions")
        first_session_id = created.json()["session_id"]
        client.post(
            "/agents/copilot",
            json={
                "query": "请联合分析订单 O10001 和策略 STRAT-001，判断是否存在团伙风险并给出策略建议",
                "context": {"order_id": "O10001", "strategy_id": "STRAT-001", "entity_id": "U10001"},
                "session_id": first_session_id,
            },
        )
        first_case = client.post(f"/cases/from-session/{first_session_id}").json()

        second_session = client.post("/sessions")
        second_session_id = second_session.json()["session_id"]
        client.post(
            "/agents/graph",
            json={
                "query": "请分析用户 U10001 是否属于团伙网络",
                "context": {"user_id": "U10001"},
                "session_id": second_session_id,
            },
        )
        client.post(f"/cases/from-session/{second_session_id}")

        filtered = client.get(
            "/cases",
            params={
                "status": "strategy_pending",
                "source_agent": "copilot",
                "session_id": first_session_id,
                "severity": "high",
            },
        )

        payload = filtered.json()
        self.assertEqual(filtered.status_code, 200)
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["case_id"], first_case["case_id"])
        self.assertEqual(filtered.headers["X-Total-Count"], "1")
        self.assertEqual(filtered.headers["X-Has-More"], "false")
        self.assertEqual(filtered.headers["X-Offset"], "0")

    def test_list_cases_supports_action_plan_filters_and_overdue_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            policy_path = Path(tmp_dir) / "risk-decision-policy.json"
            policy_path.write_text(
                json.dumps(
                    {
                        "action_plans": {
                            "escalate_review": {
                                "queue": "urgent_manual_review",
                                "priority": "high",
                                "sla_hours": 0,
                                "owner_role": "risk_reviewer",
                                "next_actions": ["立即复核"],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            client = TestClient(create_app(AppConfig(risk_decision_policy_path=policy_path)))
            session_id = client.post("/sessions").json()["session_id"]
            client.post(
                "/agents/copilot",
                json={
                    "query": "请联合分析订单 O10001 和策略 STRAT-001，判断是否存在团伙风险并给出策略建议",
                    "context": {
                        "order_id": "O10001",
                        "strategy_id": "STRAT-001",
                        "entity_id": "U10001",
                    },
                    "session_id": session_id,
                },
            )
            created_case = client.post(f"/cases/from-session/{session_id}").json()
            client.patch(
                f"/cases/{created_case['case_id']}",
                json={
                    "status": "strategy_pending",
                    "assigned_to": "risk-reviewer-01",
                },
            )

            filtered = client.get(
                "/cases",
                params={
                    "action_queue": "urgent_manual_review",
                    "action_status": "queued",
                    "assigned_to": "risk-reviewer-01",
                    "action_overdue": "true",
                },
            )

        payload = filtered.json()
        self.assertEqual(filtered.status_code, 200)
        self.assertEqual(filtered.headers["X-Total-Count"], "1")
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["case_id"], created_case["case_id"])
        self.assertTrue(payload[0]["risk_decision"]["action_plan"]["is_overdue"])

    def test_list_action_queues_returns_operational_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            policy_path = Path(tmp_dir) / "risk-decision-policy.json"
            policy_path.write_text(
                json.dumps(
                    {
                        "action_plans": {
                            "escalate_review": {
                                "queue": "urgent_manual_review",
                                "priority": "high",
                                "sla_hours": 0,
                                "owner_role": "risk_reviewer",
                                "next_actions": ["立即复核"],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            client = TestClient(create_app(AppConfig(risk_decision_policy_path=policy_path)))
            session_id = client.post("/sessions").json()["session_id"]
            client.post(
                "/agents/copilot",
                json={
                    "query": "请联合分析订单 O10001 和策略 STRAT-001，判断是否存在团伙风险并给出策略建议",
                    "context": {
                        "order_id": "O10001",
                        "strategy_id": "STRAT-001",
                        "entity_id": "U10001",
                    },
                    "session_id": session_id,
                },
            )
            created_case = client.post(f"/cases/from-session/{session_id}").json()
            client.patch(
                f"/cases/{created_case['case_id']}",
                json={
                    "status": "strategy_pending",
                    "assigned_to": "risk-reviewer-01",
                },
            )

            response = client.get("/cases/action-queues")

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["queue"], "urgent_manual_review")
        self.assertEqual(payload[0]["total_cases"], 1)
        self.assertEqual(payload[0]["overdue_cases"], 1)
        self.assertEqual(payload[0]["high_priority_cases"], 1)
        self.assertEqual(payload[0]["statuses"], {"queued": 1})
        self.assertEqual(payload[0]["priorities"], {"high": 1})
        self.assertEqual(payload[0]["assignees"], ["risk-reviewer-01"])
        self.assertEqual(payload[0]["highest_priority"], "high")
        self.assertEqual(
            payload[0]["next_due_at"],
            created_case["risk_decision"]["action_plan"]["due_at"],
        )

    def test_action_queue_cases_can_be_listed_and_assigned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            policy_path = Path(tmp_dir) / "risk-decision-policy.json"
            policy_path.write_text(
                json.dumps(
                    {
                        "action_plans": {
                            "escalate_review": {
                                "queue": "urgent_manual_review",
                                "priority": "high",
                                "sla_hours": 0,
                                "owner_role": "risk_reviewer",
                                "next_actions": ["立即复核"],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            client = TestClient(create_app(AppConfig(risk_decision_policy_path=policy_path)))
            session_id = client.post("/sessions").json()["session_id"]
            client.post(
                "/agents/copilot",
                json={
                    "query": "请联合分析订单 O10001 和策略 STRAT-001，判断是否存在团伙风险并给出策略建议",
                    "context": {
                        "order_id": "O10001",
                        "strategy_id": "STRAT-001",
                        "entity_id": "U10001",
                    },
                    "session_id": session_id,
                },
            )
            created_case = client.post(f"/cases/from-session/{session_id}").json()

            queue_cases = client.get(
                "/cases/action-queues/urgent_manual_review/cases",
                params={"limit": 5},
            )
            assigned = client.post(
                "/cases/action-queues/urgent_manual_review/assign",
                json={
                    "assigned_to": "risk-reviewer-02",
                    "case_ids": [created_case["case_id"]],
                    "note": "队列批量分派",
                },
            )

        queue_payload = queue_cases.json()
        assigned_payload = assigned.json()
        self.assertEqual(queue_cases.status_code, 200)
        self.assertEqual([item["case_id"] for item in queue_payload], [created_case["case_id"]])
        self.assertEqual(assigned.status_code, 200)
        self.assertEqual(assigned_payload["queue"], "urgent_manual_review")
        self.assertEqual(assigned_payload["assigned_to"], "risk-reviewer-02")
        self.assertEqual(assigned_payload["updated_count"], 1)
        self.assertEqual(
            assigned_payload["cases"][0]["risk_decision"]["action_plan"]["assigned_to"],
            "risk-reviewer-02",
        )
        self.assertEqual(
            assigned_payload["cases"][0]["history"][-1]["summary"],
            "队列批量分派",
        )

    def test_list_cases_supports_pagination_and_updated_at_filters(self) -> None:
        client = TestClient(create_app())
        first_session_id = client.post("/sessions").json()["session_id"]
        client.post(
            "/agents/graph",
            json={
                "query": "请分析用户 U10001 是否属于团伙网络",
                "context": {"user_id": "U10001"},
                "session_id": first_session_id,
            },
        )
        first_case = client.post(f"/cases/from-session/{first_session_id}").json()

        second_session_id = client.post("/sessions").json()["session_id"]
        client.post(
            "/agents/copilot",
            json={
                "query": "请联合分析订单 O10001 和策略 STRAT-001，判断是否存在团伙风险并给出策略建议",
                "context": {"order_id": "O10001", "strategy_id": "STRAT-001", "entity_id": "U10001"},
                "session_id": second_session_id,
            },
        )
        second_case = client.post(f"/cases/from-session/{second_session_id}").json()
        updated_second_case = client.patch(
            f"/cases/{second_case['case_id']}",
            json={"status": "closed", "note": "完成"},
        ).json()

        paged = client.get("/cases", params={"limit": 1, "offset": 1})
        filtered = client.get(
            "/cases",
            params={"updated_after": updated_second_case["created_at"]},
        )

        paged_payload = paged.json()
        filtered_payload = filtered.json()
        self.assertEqual(paged.status_code, 200)
        self.assertEqual(len(paged_payload), 1)
        self.assertEqual(paged_payload[0]["case_id"], first_case["case_id"])
        self.assertEqual(paged.headers["X-Total-Count"], "2")
        self.assertEqual(paged.headers["X-Has-More"], "false")
        self.assertEqual(paged.headers["X-Offset"], "1")
        self.assertEqual(paged.headers["X-Limit"], "1")
        self.assertEqual(filtered.status_code, 200)
        self.assertEqual(len(filtered_payload), 1)
        self.assertEqual(filtered_payload[0]["case_id"], second_case["case_id"])
        self.assertEqual(filtered.headers["X-Total-Count"], "1")
        self.assertEqual(filtered.headers["X-Has-More"], "false")

    def test_list_cases_rejects_invalid_timestamp_filter(self) -> None:
        client = TestClient(create_app())

        response = client.get("/cases", params={"updated_after": "not-a-timestamp"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid isoformat string", response.json()["detail"])

    def test_list_cases_defaults_to_recently_updated_first(self) -> None:
        client = TestClient(create_app())
        first_session = client.post("/sessions").json()["session_id"]
        client.post(
            "/agents/graph",
            json={
                "query": "请分析用户 U10001 是否属于团伙网络",
                "context": {"user_id": "U10001"},
                "session_id": first_session,
            },
        )
        first_case = client.post(f"/cases/from-session/{first_session}").json()

        second_session = client.post("/sessions").json()["session_id"]
        client.post(
            "/agents/copilot",
            json={
                "query": "请联合分析订单 O10001 和策略 STRAT-001，判断是否存在团伙风险并给出策略建议",
                "context": {"order_id": "O10001", "strategy_id": "STRAT-001", "entity_id": "U10001"},
                "session_id": second_session,
            },
        )
        second_case = client.post(f"/cases/from-session/{second_session}").json()
        client.patch(
            f"/cases/{first_case['case_id']}",
            json={"status": "in_review", "note": "重新置顶"},
        )

        response = client.get("/cases")
        payload = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload[0]["case_id"], first_case["case_id"])
        self.assertEqual(payload[1]["case_id"], second_case["case_id"])
        self.assertEqual(response.headers["X-Total-Count"], "2")
        self.assertEqual(response.headers["X-Has-More"], "false")

        created_sorted = client.get(
            "/cases",
            params={"sort_by": "created_at", "sort_order": "asc"},
        )
        created_payload = created_sorted.json()
        self.assertEqual(created_sorted.status_code, 200)
        self.assertEqual(created_payload[0]["case_id"], first_case["case_id"])
        self.assertEqual(created_payload[1]["case_id"], second_case["case_id"])

    def test_list_cases_pagination_headers_report_has_more(self) -> None:
        client = TestClient(create_app())
        for _ in range(3):
            session_id = client.post("/sessions").json()["session_id"]
            client.post(
                "/agents/graph",
                json={
                    "query": "请分析用户 U10001 是否属于团伙网络",
                    "context": {"user_id": "U10001"},
                    "session_id": session_id,
                },
            )
            client.post(f"/cases/from-session/{session_id}")

        response = client.get("/cases", params={"limit": 2, "offset": 0})

        payload = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(payload), 2)
        self.assertEqual(response.headers["X-Total-Count"], "3")
        self.assertEqual(response.headers["X-Has-More"], "true")
        self.assertEqual(response.headers["X-Limit"], "2")

    def test_metrics_endpoint_reports_case_gauges_and_counters(self) -> None:
        client = TestClient(create_app())
        session_id = client.post("/sessions").json()["session_id"]
        client.post(
            "/agents/copilot",
            json={
                "query": "请联合分析订单 O10001 和策略 STRAT-001，判断是否存在团伙风险并给出策略建议",
                "context": {"order_id": "O10001", "strategy_id": "STRAT-001", "entity_id": "U10001"},
                "session_id": session_id,
            },
        )
        created_case = client.post(f"/cases/from-session/{session_id}").json()
        client.patch(
            f"/cases/{created_case['case_id']}",
            json={"status": "closed", "note": "完成"},
        )

        response = client.get("/admin/metrics")
        payload = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(payload["counters"]["cases.created"], 1)
        self.assertGreaterEqual(payload["counters"]["cases.status_updated"], 1)
        self.assertGreaterEqual(payload["gauges"]["cases.total"], 1)
        self.assertGreaterEqual(payload["gauges"]["cases.status.closed"], 1)
        self.assertGreaterEqual(payload["gauges"]["cases.action_plan.total"], 1)
        self.assertGreaterEqual(
            payload["gauges"]["cases.action_plan.status.completed"],
            1,
        )
        self.assertGreaterEqual(
            payload["gauges"]["cases.action_plan.queue.manual_review_queue"],
            1,
        )
        self.assertIn("cases.action_plan.overdue", payload["gauges"])


if __name__ == "__main__":
    unittest.main()
