from __future__ import annotations

import unittest

from app import build_demo_runtime
from core.models import AgentRequest


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

    def test_copilot_agent_only_runs_investigation_for_plain_metric_question(self) -> None:
        _, response = self.runtime.execute(
            "copilot",
            AgentRequest(query="为什么巴西信用卡支付失败率从昨晚开始突然升高？"),
        )

        self.assertIn("识别意图为 metric_anomaly", response.summary)
        self.assertIn("执行计划为 调查", response.summary)
        self.assertEqual(response.intent, "metric_anomaly")
        self.assertEqual(response.plan_steps, ["调查"])
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
        self.assertTrue(any(finding == "[意图] fraud_ring" for finding in response.findings))
        self.assertFalse(any(finding.startswith("[规划] 策略") for finding in response.findings))


if __name__ == "__main__":
    unittest.main()
