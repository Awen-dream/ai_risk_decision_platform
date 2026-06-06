from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from api import create_app, fastapi_app
from core.models import ToolResult
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
        self.assertEqual(payload["session_store_backend"], "memory")
        self.assertEqual(payload["session_store_path"], ".data/sessions.json")
        self.assertEqual(payload["tool_http_timeout_sec"], 5.0)
        self.assertEqual(payload["tool_http_auth_mode"], "none")
        self.assertEqual(payload["tool_http_auth_header"], "Authorization")
        self.assertEqual(payload["tool_http_metric_path"], "/metric-snapshots")
        self.assertEqual(payload["tool_http_strategy_profile_path_template"], "/strategy-profiles/{strategy_id}")
        self.assertEqual(payload["tool_http_graph_relation_path_template"], "/graph-relations/{entity_id}")
        self.assertEqual(payload["tool_http_country_param"], "country")
        self.assertEqual(payload["tool_http_channel_param"], "channel")
        self.assertEqual(payload["registered_agents"], ["knowledge", "investigation", "strategy", "graph", "copilot"])
        self.assertEqual(
            payload["registered_tools"],
            ["metric_snapshot", "case_lookup", "order_profile", "strategy_profile", "strategy_simulation", "graph_relation"],
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
        self.assertEqual(payload["readiness"]["status"], "ready")
        self.assertEqual(
            [item["name"] for item in payload["readiness"]["checks"]],
            ["knowledge_index", "agent_registry", "tool_registry", "session_store"],
        )

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

        fetched = self.client.get(f"/sessions/{session_id}")
        turn = fetched.json()["turns"][0]
        self.assertEqual(turn["agent_name"], "copilot")
        self.assertEqual(turn["title"], "联合分析")
        self.assertEqual(turn["status"], "completed")
        self.assertEqual(turn["agent_group"], "workflow")
        self.assertEqual(turn["badge"], "workflow")
        self.assertEqual(turn["severity"], "high")
        self.assertEqual(turn["expanded_sections"], ["intent", "plan", "planner_trace", "findings", "actions"])
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
        created = self.client.post("/sessions")
        session_id = created.json()["session_id"]
        self.client.post(
            "/agents/copilot",
            json={
                "query": "请联合分析订单 O10001 和策略 STRAT-001，判断是否存在团伙风险并给出策略建议",
                "context": {"order_id": "O10001", "strategy_id": "STRAT-001", "entity_id": "U10001"},
                "session_id": session_id,
            },
        )

        created_case = self.client.post(f"/cases/from-session/{session_id}")

        payload = created_case.json()
        self.assertEqual(created_case.status_code, 200)
        self.assertEqual(payload["session_id"], session_id)
        self.assertEqual(payload["source_agent"], "copilot")
        self.assertEqual(payload["status"], "strategy_pending")
        self.assertEqual(payload["severity"], "high")
        self.assertEqual(payload["strategy_recommendation"]["strategy_id"], "STRAT-001")
        self.assertEqual(
            payload["strategy_recommendation"]["validation_window"],
            "shadow evaluation",
        )
        self.assertTrue(payload["suggested_actions"])

        listed = self.client.get("/cases")
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(listed.json()), 1)

        updated = self.client.patch(
            f"/cases/{payload['case_id']}",
            json={"status": "closed", "note": "人工复核完成"},
        )
        updated_payload = updated.json()
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated_payload["status"], "closed")
        self.assertEqual(len(updated_payload["history"]), 2)
        self.assertEqual(updated_payload["history"][1]["summary"], "人工复核完成")


if __name__ == "__main__":
    unittest.main()
