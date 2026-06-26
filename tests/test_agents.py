from __future__ import annotations

import unittest
import json
import tempfile
from pathlib import Path

from agents.copilot import CopilotAgent
from agents.copilot_planner import CopilotPlanCandidate, CopilotPlanner
from agents.investigation import InvestigationAgent
from app import build_demo_runtime, build_runtime
from core.models import AgentRequest, ToolResult
from retrieval.knowledge_base import RetrievalService
from settings import AppConfig
from tools.registry import ToolRegistry


class StaticPlanner(CopilotPlanner):
    name = "static"

    def __init__(self, candidate: CopilotPlanCandidate) -> None:
        self._candidate = candidate

    def plan(self, request: AgentRequest) -> CopilotPlanCandidate:
        return self._candidate


class AgentPlatformTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = build_demo_runtime()

    def test_knowledge_agent_returns_citations(self) -> None:
        _, response = self.runtime.execute(
            "knowledge",
            AgentRequest(query="营销套利案件的标准排查 SOP 是什么？"),
        )

        self.assertTrue(response.summary)
        self.assertGreaterEqual(len(response.citations), 1)
        self.assertIn("营销套利", response.summary)

    def test_metric_investigation_returns_expected_findings(self) -> None:
        _, response = self.runtime.execute(
            "investigation",
            AgentRequest(query="为什么巴西信用卡支付失败率从昨晚开始突然升高？"),
        )

        self.assertIn("BR", response.summary)
        self.assertTrue(any("异常开始时间" in finding for finding in response.findings))
        self.assertTrue(any(trace.name == "metric_snapshot" for trace in response.tool_traces))
        self.assertTrue(any(trace.name == "case_lookup" for trace in response.tool_traces))
        self.assertTrue(any(trace.name == "case_lookup" and trace.status == "success" for trace in response.tool_traces))
        self.assertTrue(any("历史相似案例" in finding for finding in response.findings))

    def test_metric_investigation_uses_time_range_context(self) -> None:
        _, response = self.runtime.execute(
            "investigation",
            AgentRequest(
                query="为什么巴西信用卡支付失败率持续升高？",
                context={"country": "BR", "channel": "credit_card", "time_range": "recent_7d"},
            ),
        )

        self.assertIn("2026-05-18 08:00", response.summary)
        self.assertTrue(any("时间窗口：recent_7d" == finding for finding in response.findings))

    def test_metric_investigation_handles_failed_metric_tool(self) -> None:
        registry = ToolRegistry()
        registry.register(
            "metric_snapshot",
            lambda **kwargs: ToolResult.failed_result(
                name="metric_snapshot",
                payload={},
                summary="工具调用失败",
                error="upstream timeout",
                error_type="timeout",
            ),
        )
        registry.register(
            "case_lookup",
            lambda **kwargs: ToolResult.success_result(
                name="case_lookup",
                payload=[
                    {
                        "case_id": "BR-1",
                        "country": "BR",
                        "channel": "credit_card",
                        "title": "阈值回退案例",
                    }
                ],
                summary="返回 1 条历史相似案例",
            ),
        )
        agent = InvestigationAgent(registry, RetrievalService())

        response = agent.run(
            AgentRequest(
                query="为什么巴西信用卡支付失败率升高？",
                context={"country": "BR", "channel": "credit_card"},
            )
        )

        self.assertIn("指标快照调用失败", response.summary)
        self.assertTrue(any(trace.status == "failed" for trace in response.tool_traces))
        self.assertTrue(any("历史相似案例" in finding for finding in response.findings))

    def test_order_investigation_uses_order_context(self) -> None:
        _, response = self.runtime.execute(
            "investigation",
            AgentRequest(
                query="请分析这个订单为什么被判高风险",
                context={"order_id": "O10001"},
            ),
        )

        self.assertIn("O10001", response.summary)
        self.assertTrue(any("命中规则" in finding for finding in response.findings))
        self.assertTrue(any(trace.name == "order_profile" for trace in response.tool_traces))
        self.assertTrue(any(trace.name == "graph_relation" for trace in response.tool_traces))
        self.assertTrue(any("关键路径" in finding for finding in response.findings))

    def test_order_investigation_degrades_when_order_is_missing(self) -> None:
        _, response = self.runtime.execute(
            "investigation",
            AgentRequest(
                query="请分析这个订单为什么被判高风险",
                context={"order_id": "MISSING"},
            ),
        )

        self.assertIn("暂时无法完成订单 MISSING 的完整调查", response.summary)
        self.assertTrue(any(trace.status == "degraded" for trace in response.tool_traces))
        self.assertTrue(any("订单画像：未找到订单画像" in finding for finding in response.findings))

    def test_unknown_agent_raises_key_error(self) -> None:
        with self.assertRaises(KeyError):
            self.runtime.execute("unknown", AgentRequest(query="test"))

    def test_runtime_persists_session_history(self) -> None:
        session_id, _ = self.runtime.execute(
            "knowledge",
            AgentRequest(query="营销套利案件的标准排查 SOP 是什么？"),
        )
        self.runtime.execute(
            "investigation",
            AgentRequest(query="为什么巴西信用卡支付失败率从昨晚开始突然升高？"),
            session_id=session_id,
        )

        session = self.runtime.get_session(session_id)
        self.assertIsNotNone(session)
        self.assertEqual(len(session.turns), 2)
        self.assertEqual(session.turns[0].agent_name, "knowledge")
        self.assertEqual(session.turns[1].agent_name, "investigation")

    def test_runtime_persists_copilot_intent_and_plan(self) -> None:
        session_id, _ = self.runtime.execute(
            "copilot",
            AgentRequest(
                query="请联合分析订单 O10001 和策略 STRAT-001，判断是否存在团伙风险并给出策略建议",
                context={"order_id": "O10001", "strategy_id": "STRAT-001", "entity_id": "U10001"},
            ),
        )

        session = self.runtime.get_session(session_id)
        self.assertIsNotNone(session)
        self.assertEqual(len(session.turns), 1)
        self.assertEqual(session.turns[0].intent, "composite")
        self.assertEqual(session.turns[0].plan_steps, ["调查", "策略", "图谱"])
        self.assertEqual(
            [(trace.step, trace.selected) for trace in session.turns[0].planner_trace],
            [("调查", True), ("策略", True), ("图谱", True)],
        )

    def test_strategy_agent_returns_simulation_guidance(self) -> None:
        _, response = self.runtime.execute(
            "strategy",
            AgentRequest(
                query="请评估策略 STRAT-001 是否应该调整阈值",
                context={"strategy_id": "STRAT-001"},
            ),
        )

        self.assertIn("STRAT-001", response.summary)
        self.assertTrue(any("仿真结果" in finding for finding in response.findings))
        self.assertTrue(any(trace.name == "strategy_profile" for trace in response.tool_traces))
        self.assertTrue(any(trace.name == "strategy_simulation" for trace in response.tool_traces))
        self.assertTrue(any(trace.name == "graph_relation" for trace in response.tool_traces))
        self.assertTrue(any("图谱风险" in finding for finding in response.findings))
        self.assertEqual(
            response.artifacts["strategy_recommendation"]["strategy_id"],
            "STRAT-001",
        )

    def test_strategy_agent_degrades_when_strategy_is_missing(self) -> None:
        _, response = self.runtime.execute(
            "strategy",
            AgentRequest(
                query="请评估策略 MISSING 是否应该调整阈值",
                context={"strategy_id": "MISSING"},
            ),
        )

        self.assertIn("暂时无法完成策略 MISSING 的完整分析", response.summary)
        self.assertTrue(any(trace.status == "degraded" for trace in response.tool_traces))
        self.assertTrue(any("策略画像：未找到策略画像" in finding for finding in response.findings))

    def test_graph_agent_returns_relation_summary(self) -> None:
        _, response = self.runtime.execute(
            "graph",
            AgentRequest(
                query="请分析用户 U10001 是否属于团伙网络",
                context={"user_id": "U10001"},
            ),
        )

        self.assertIn("U10001", response.summary)
        self.assertTrue(any("共享设备" in finding for finding in response.findings))
        self.assertTrue(any(trace.name == "graph_relation" for trace in response.tool_traces))

    def test_graph_agent_degrades_when_relation_is_missing(self) -> None:
        _, response = self.runtime.execute(
            "graph",
            AgentRequest(
                query="请分析用户 MISSING 是否属于团伙网络",
                context={"entity_id": "MISSING"},
            ),
        )

        self.assertIn("暂时无法完成实体 MISSING 的图谱分析", response.summary)
        self.assertEqual(response.tool_traces[0].status, "degraded")

    def test_copilot_agent_merges_investigation_strategy_and_graph(self) -> None:
        _, response = self.runtime.execute(
            "copilot",
            AgentRequest(
                query="请联合分析订单 O10001 和策略 STRAT-001，判断是否存在团伙风险并给出策略建议",
                context={"order_id": "O10001", "strategy_id": "STRAT-001", "entity_id": "U10001"},
            ),
        )

        self.assertIn("联合分析", response.summary)
        self.assertIn("识别意图为 composite", response.summary)
        self.assertIn("调查 -> 策略 -> 图谱", response.summary)
        self.assertEqual(response.intent, "composite")
        self.assertEqual(response.plan_steps, ["调查", "策略", "图谱"])
        self.assertEqual(len(response.planner_trace), 3)
        self.assertEqual(
            [(trace.step, trace.selected) for trace in response.planner_trace],
            [("调查", True), ("策略", True), ("图谱", True)],
        )
        self.assertTrue(any(finding == "[意图] composite" for finding in response.findings))
        self.assertTrue(any(finding.startswith("[规划] 调查") for finding in response.findings))
        self.assertTrue(any(finding.startswith("[规划] 策略") for finding in response.findings))
        self.assertTrue(any(finding.startswith("[规划] 图谱") for finding in response.findings))
        self.assertTrue(any(finding.startswith("[调查]") for finding in response.findings))
        self.assertTrue(any(finding.startswith("[策略]") for finding in response.findings))
        self.assertTrue(any(finding.startswith("[图谱]") for finding in response.findings))
        self.assertTrue(any(trace.name.startswith("调查::") for trace in response.tool_traces))
        self.assertTrue(any(trace.name.startswith("策略::") for trace in response.tool_traces))
        self.assertTrue(any(trace.name.startswith("图谱::") for trace in response.tool_traces))
        decision = response.artifacts["risk_decision"]
        self.assertEqual(decision["decision"], "escalate_review")
        self.assertEqual(decision["risk_level"], "high")
        self.assertEqual(decision["recommended_action"], "manual_review")
        self.assertEqual(decision["evidence_strength"], "strong")
        self.assertIn("manual_review_queue", decision["policy_controls"])
        self.assertEqual(decision["action_plan"]["queue"], "manual_review_queue")
        self.assertEqual(decision["action_plan"]["priority"], "high")
        self.assertEqual(decision["action_plan"]["sla_hours"], 4)

    def test_copilot_agent_only_runs_investigation_for_plain_metric_question(self) -> None:
        _, response = self.runtime.execute(
            "copilot",
            AgentRequest(query="为什么巴西信用卡支付失败率从昨晚开始突然升高？"),
        )

        self.assertIn("识别意图为 metric_anomaly", response.summary)
        self.assertIn("执行计划为 调查", response.summary)
        self.assertEqual(response.intent, "metric_anomaly")
        self.assertEqual(response.plan_steps, ["调查"])
        self.assertEqual(
            [(trace.step, trace.selected) for trace in response.planner_trace],
            [("调查", True), ("策略", False), ("图谱", False)],
        )
        self.assertTrue(any(finding == "[意图] metric_anomaly" for finding in response.findings))
        self.assertTrue(any(finding.startswith("[规划] 调查") for finding in response.findings))
        self.assertFalse(any(finding.startswith("[规划] 策略") for finding in response.findings))
        self.assertFalse(any(finding.startswith("[规划] 图谱") for finding in response.findings))
        self.assertTrue(all(trace.name.startswith("调查::") for trace in response.tool_traces))

    def test_copilot_agent_classifies_graph_only_question(self) -> None:
        _, response = self.runtime.execute(
            "copilot",
            AgentRequest(
                query="请分析用户 U10001 是否属于团伙网络",
                context={"user_id": "U10001"},
            ),
        )

        self.assertIn("识别意图为 fraud_ring", response.summary)
        self.assertIn("执行计划为 调查 -> 图谱", response.summary)
        self.assertEqual(response.intent, "fraud_ring")
        self.assertEqual(response.plan_steps, ["调查", "图谱"])
        self.assertEqual(
            [(trace.step, trace.selected) for trace in response.planner_trace],
            [("调查", True), ("策略", False), ("图谱", True)],
        )
        self.assertTrue(any(finding == "[意图] fraud_ring" for finding in response.findings))
        self.assertFalse(any(finding.startswith("[规划] 策略") for finding in response.findings))

    def test_copilot_agent_classifies_order_only_question_as_order_case(self) -> None:
        _, response = self.runtime.execute(
            "copilot",
            AgentRequest(
                query="请分析这个订单为什么被判高风险",
                context={"order_id": "O10001"},
            ),
        )

        self.assertEqual(response.intent, "order_case")
        self.assertEqual(response.plan_steps, ["调查", "图谱"])
        self.assertTrue(any(trace.name.startswith("图谱::") for trace in response.tool_traces))
        self.assertEqual(response.artifacts["risk_decision"]["risk_level"], "medium")
        self.assertEqual(
            response.artifacts["risk_decision"]["recommended_action"],
            "manual_review",
        )

    def test_copilot_agent_validates_candidate_plan_and_inserts_required_investigation(self) -> None:
        planner = StaticPlanner(
            CopilotPlanCandidate(
                intent="fraud_ring",
                selected_steps=["图谱"],
                step_reasons={"图谱": "候选计划认为图谱证据最关键。"},
                planner_backend="static",
            )
        )
        agent = CopilotAgent(
            investigation_agent=self.runtime._agents["investigation"],
            strategy_agent=self.runtime._agents["strategy"],
            graph_agent=self.runtime._agents["graph"],
            planner=planner,
        )

        response = agent.run(
            AgentRequest(
                query="请分析用户 U10001 是否属于团伙网络",
                context={"user_id": "U10001"},
            )
        )

        self.assertEqual(response.intent, "fraud_ring")
        self.assertEqual(response.plan_steps, ["调查", "图谱"])
        self.assertFalse(response.artifacts["planner"]["fallback_used"])
        self.assertIn("candidate omitted required step: 调查", response.artifacts["planner"]["validation_errors"])
        self.assertTrue(any(trace.name.startswith("调查::") for trace in response.tool_traces))
        self.assertTrue(any(trace.name.startswith("图谱::") for trace in response.tool_traces))

    def test_copilot_agent_falls_back_to_rule_planner_for_invalid_candidate_intent(self) -> None:
        planner = StaticPlanner(
            CopilotPlanCandidate(
                intent="unknown_intent",
                selected_steps=["策略", "图谱"],
                planner_backend="static",
            )
        )
        agent = CopilotAgent(
            investigation_agent=self.runtime._agents["investigation"],
            strategy_agent=self.runtime._agents["strategy"],
            graph_agent=self.runtime._agents["graph"],
            planner=planner,
        )

        response = agent.run(
            AgentRequest(
                query="为什么巴西信用卡支付失败率从昨晚开始突然升高？",
            )
        )

        self.assertEqual(response.intent, "metric_anomaly")
        self.assertEqual(response.plan_steps, ["调查"])
        self.assertTrue(response.artifacts["planner"]["fallback_used"])
        self.assertEqual(response.artifacts["planner"]["backend"], "rule")
        self.assertIn("unknown intent: unknown_intent", response.artifacts["planner"]["validation_errors"])

    def test_copilot_agent_uses_configured_decision_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            policy_path = Path(tmp_dir) / "risk-decision-policy.json"
            policy_path.write_text(
                json.dumps(
                    {
                        "signals": {"high_graph_levels": ["medium"]},
                        "outcomes": {
                            "high_risk_review": {
                                "decision": "queue_l2_review",
                                "risk_level": "high",
                                "recommended_action": "manual_review",
                                "escalation_reason": "中风险订单图谱需要二线复核。",
                                "policy_controls": ["l2_review_queue"],
                            }
                        },
                        "action_plans": {
                            "queue_l2_review": {
                                "queue": "l2_review_queue",
                                "priority": "high",
                                "sla_hours": 2,
                                "owner_role": "l2_risk_reviewer",
                                "next_actions": ["二线复核图谱证据"],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            runtime = build_runtime(AppConfig(risk_decision_policy_path=policy_path))

            _, response = runtime.execute(
                "copilot",
                AgentRequest(
                    query="请分析这个订单为什么被判高风险",
                    context={"order_id": "O10001"},
                ),
            )

        self.assertEqual(response.artifacts["risk_decision"]["decision"], "queue_l2_review")
        self.assertEqual(response.artifacts["risk_decision"]["risk_level"], "high")
        self.assertIn("l2_review_queue", response.artifacts["risk_decision"]["policy_controls"])
        self.assertEqual(
            response.artifacts["risk_decision"]["action_plan"]["queue"],
            "l2_review_queue",
        )
        self.assertEqual(
            response.artifacts["risk_decision"]["action_plan"]["sla_hours"],
            2,
        )

    def test_copilot_agent_preserves_strategy_recommendation_artifact(self) -> None:
        _, response = self.runtime.execute(
            "copilot",
            AgentRequest(
                query="请联合分析订单 O10001 和策略 STRAT-001，判断是否存在团伙风险并给出策略建议",
                context={"order_id": "O10001", "strategy_id": "STRAT-001", "entity_id": "U10001"},
            ),
        )

        self.assertEqual(
            response.artifacts["strategy_recommendation"]["recommended_threshold"],
            0.66,
        )
        self.assertEqual(
            response.artifacts["risk_decision"]["decision"],
            "escalate_review",
        )


if __name__ == "__main__":
    unittest.main()
