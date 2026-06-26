from __future__ import annotations

import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from agents.investigation_planner import OpenAIInvestigationPlanner
from core.models import AgentRequest


class _FakeResponse:
    def __init__(self, payload) -> None:
        self._buffer = io.BytesIO(json.dumps(payload).encode("utf-8"))

    def __enter__(self):
        return self._buffer

    def __exit__(self, exc_type, exc, tb) -> None:
        self._buffer.close()


class OpenAIInvestigationPlannerTests(unittest.TestCase):
    def test_openai_investigation_planner_posts_structured_request_and_parses_candidate(self) -> None:
        with patch(
            "agents.investigation_planner.urlopen",
            return_value=_FakeResponse(
                {
                    "output_text": json.dumps(
                        {
                            "mode": "metric",
                            "selected_tools": [
                                "metric_snapshot",
                                "case_lookup",
                                "sql_query",
                            ],
                            "mode_reason": "需要确认异常并做分层下钻。",
                            "tool_reasons": [
                                {"tool": "metric_snapshot", "reason": "先确认核心指标。"},
                                {"tool": "case_lookup", "reason": "补充历史案例。"},
                                {"tool": "sql_query", "reason": "需要更细的分层明细。"},
                            ],
                        },
                        ensure_ascii=False,
                    )
                }
            ),
        ) as mocked:
            planner = OpenAIInvestigationPlanner(
                api_key="investigation-key",
                model="gpt-4o-mini",
                base_url="https://api.openai.example/v1",
                timeout_sec=8.0,
            )
            candidate = planner.plan(
                AgentRequest(
                    query="为什么巴西信用卡支付失败率突然升高？",
                    context={"country": "BR", "channel": "credit_card"},
                )
            )

        self.assertEqual(candidate.mode, "metric")
        self.assertEqual(candidate.selected_tools, ["metric_snapshot", "case_lookup", "sql_query"])
        self.assertEqual(candidate.tool_reasons["sql_query"], "需要更细的分层明细。")
        self.assertEqual(candidate.planner_backend, "openai")
        request = mocked.call_args[0][0]
        self.assertEqual(request.full_url, "https://api.openai.example/v1/responses")
        self.assertEqual(request.headers["Authorization"], "Bearer investigation-key")
        self.assertEqual(json.loads(request.data.decode("utf-8"))["text"]["format"]["type"], "json_schema")

    def test_openai_investigation_planner_falls_back_to_rule_plan_on_http_error(self) -> None:
        http_error = HTTPError(
            url="https://api.openai.com/v1/responses",
            code=503,
            msg="service unavailable",
            hdrs=None,
            fp=None,
        )

        with patch("agents.investigation_planner.urlopen", side_effect=http_error):
            planner = OpenAIInvestigationPlanner(
                api_key="investigation-key",
                model="gpt-4o-mini",
            )
            candidate = planner.plan(
                AgentRequest(
                    query="请分析这个订单为什么被判高风险",
                    context={"order_id": "O10001"},
                )
            )

        self.assertEqual(candidate.mode, "order")
        self.assertEqual(candidate.selected_tools, ["order_profile", "graph_relation", "rule_explain"])
        self.assertEqual(candidate.planner_backend, "openai_fallback_rule")
        self.assertIn("HTTPError", candidate.planner_error)


if __name__ == "__main__":
    unittest.main()
