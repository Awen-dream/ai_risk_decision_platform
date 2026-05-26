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


if __name__ == "__main__":
    unittest.main()
