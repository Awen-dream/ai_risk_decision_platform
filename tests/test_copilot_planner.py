from __future__ import annotations

import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from agents.copilot_planner import OpenAICopilotPlanner
from core.models import AgentRequest


class _FakeResponse:
    def __init__(self, payload) -> None:
        self._buffer = io.BytesIO(json.dumps(payload).encode("utf-8"))

    def __enter__(self):
        return self._buffer

    def __exit__(self, exc_type, exc, tb) -> None:
        self._buffer.close()


class OpenAICopilotPlannerTests(unittest.TestCase):
    def test_openai_planner_posts_structured_output_request_and_parses_candidate(self) -> None:
        with patch(
            "agents.copilot_planner.urlopen",
            return_value=_FakeResponse(
                {
                    "output_text": json.dumps(
                        {
                            "intent": "composite",
                            "selected_steps": ["调查", "策略", "图谱"],
                            "intent_reason": "同时命中策略和图谱信号。",
                            "step_reasons": [
                                {"step": "调查", "reason": "先核查基础证据。"},
                                {"step": "策略", "reason": "需要评估阈值影响。"},
                                {"step": "图谱", "reason": "需要补充关联网络。"},
                            ],
                        },
                        ensure_ascii=False,
                    )
                }
            ),
        ) as mocked:
            planner = OpenAICopilotPlanner(
                api_key="planner-key",
                model="gpt-4o-mini",
                base_url="https://api.openai.example/v1",
                timeout_sec=9.0,
            )
            candidate = planner.plan(
                AgentRequest(
                    query="请联合分析订单 O10001 和策略 STRAT-001",
                    context={"order_id": "O10001", "strategy_id": "STRAT-001"},
                )
            )

        self.assertEqual(candidate.intent, "composite")
        self.assertEqual(candidate.selected_steps, ["调查", "策略", "图谱"])
        self.assertEqual(candidate.step_reasons["策略"], "需要评估阈值影响。")
        self.assertEqual(candidate.planner_backend, "openai")
        self.assertEqual(candidate.planner_error, "")
        request = mocked.call_args[0][0]
        self.assertEqual(request.full_url, "https://api.openai.example/v1/responses")
        self.assertEqual(request.headers["Authorization"], "Bearer planner-key")
        self.assertEqual(json.loads(request.data.decode("utf-8"))["model"], "gpt-4o-mini")
        self.assertEqual(
            json.loads(request.data.decode("utf-8"))["text"]["format"]["type"],
            "json_schema",
        )

    def test_openai_planner_falls_back_to_rule_candidate_on_http_error(self) -> None:
        http_error = HTTPError(
            url="https://api.openai.com/v1/responses",
            code=503,
            msg="service unavailable",
            hdrs=None,
            fp=None,
        )

        with patch("agents.copilot_planner.urlopen", side_effect=http_error):
            planner = OpenAICopilotPlanner(
                api_key="planner-key",
                model="gpt-4o-mini",
            )
            candidate = planner.plan(
                AgentRequest(query="为什么巴西信用卡支付失败率从昨晚开始突然升高？")
            )

        self.assertEqual(candidate.intent, "root_cause_analysis")
        self.assertEqual(candidate.selected_steps, ["调查", "根因"])
        self.assertEqual(candidate.planner_backend, "openai_fallback_rule")
        self.assertIn("HTTPError", candidate.planner_error)


if __name__ == "__main__":
    unittest.main()
