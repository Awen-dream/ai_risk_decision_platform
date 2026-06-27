from __future__ import annotations

import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from agents.strategy_planner import OpenAIStrategyPlanner
from core.models import AgentRequest


class _FakeResponse:
    def __init__(self, payload) -> None:
        self._buffer = io.BytesIO(json.dumps(payload).encode("utf-8"))

    def __enter__(self):
        return self._buffer

    def __exit__(self, exc_type, exc, tb) -> None:
        self._buffer.close()


class OpenAIStrategyPlannerTests(unittest.TestCase):
    def test_openai_strategy_planner_posts_structured_request_and_parses_candidate(self) -> None:
        with patch(
            "agents.strategy_planner.urlopen",
            return_value=_FakeResponse(
                {
                    "output_text": json.dumps(
                        {
                            "selected_tools": [
                                "strategy_profile",
                                "strategy_simulation",
                                "rule_explain",
                            ],
                            "plan_reason": "需要画像、仿真和规则解释。",
                            "tool_reasons": [
                                {"tool": "strategy_profile", "reason": "先确认策略状态。"},
                                {"tool": "strategy_simulation", "reason": "评估阈值调整影响。"},
                                {"tool": "rule_explain", "reason": "解释近期规则变更。"},
                            ],
                        },
                        ensure_ascii=False,
                    )
                }
            ),
        ) as mocked:
            planner = OpenAIStrategyPlanner(
                api_key="strategy-key",
                model="gpt-4o-mini",
                base_url="https://api.openai.example/v1",
                timeout_sec=8.0,
            )
            candidate = planner.plan(
                AgentRequest(
                    query="请评估策略 STRAT-001 是否应该调整阈值",
                    context={"strategy_id": "STRAT-001"},
                )
            )

        self.assertEqual(
            candidate.selected_tools,
            ["strategy_profile", "strategy_simulation", "rule_explain"],
        )
        self.assertEqual(candidate.tool_reasons["rule_explain"], "解释近期规则变更。")
        self.assertEqual(candidate.planner_backend, "openai")
        request = mocked.call_args[0][0]
        self.assertEqual(request.full_url, "https://api.openai.example/v1/responses")
        self.assertEqual(request.headers["Authorization"], "Bearer strategy-key")
        self.assertEqual(json.loads(request.data.decode("utf-8"))["text"]["format"]["type"], "json_schema")

    def test_openai_strategy_planner_falls_back_to_rule_plan_on_http_error(self) -> None:
        http_error = HTTPError(
            url="https://api.openai.com/v1/responses",
            code=503,
            msg="service unavailable",
            hdrs=None,
            fp=None,
        )

        with patch("agents.strategy_planner.urlopen", side_effect=http_error):
            planner = OpenAIStrategyPlanner(
                api_key="strategy-key",
                model="gpt-4o-mini",
            )
            candidate = planner.plan(
                AgentRequest(
                    query="请评估策略 STRAT-001 是否应该调整阈值",
                    context={"strategy_id": "STRAT-001"},
                )
            )

        self.assertEqual(
            candidate.selected_tools,
            ["strategy_profile", "strategy_simulation", "graph_relation", "rule_explain"],
        )
        self.assertEqual(candidate.planner_backend, "openai_fallback_rule")
        self.assertIn("HTTPError", candidate.planner_error)


if __name__ == "__main__":
    unittest.main()
